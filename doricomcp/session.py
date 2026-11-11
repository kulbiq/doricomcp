"""One live Dorico session: Remote Control + Lua bridge + sealed-value prober + change detection.

Reads assemble the digital twin; writes go through `transact`, which runs one Lua transaction (one undo
step), reads the affected range back, checks it with a caller-supplied verifier and, if that fails,
undoes the transaction immediately (nothing in between) and confirms the range is restored.

Depends on: bridge, catalog, logtail, model, probe, rc.
"""
import asyncio
import contextlib
import json as _json
from fractions import Fraction

from .bridge import Bridge, LuaError, StillRunning
from .catalog import library_dump
from .logtail import LogTail
from .model import (
    KEY_NAMES,
    Event,
    bar_at,
    bar_regions,
    bar_start,
    build_events,
    frac,
    fstr,
    in_range,
    rational,
    staff_map,
)
from .probe import Prober
from .rc import HOME, RCError, RemoteControl

# "complex": a bar division whose signature matches no n/d candidate (an X/additive signature, or Dorico's own
# division in a project made without a time signature); it counts as one bar, like open meter
TIMESIG_SHOWN = {None: "none (open meter)", "complex": "unreadable (not a plain n/d signature; counted as one bar - "
                                                       "set one with set_time_signature to get regular bars)"}
VOICES_FILE = HOME / "voices.json"  # staff of voices this server created: {title: {flow: {voice: staff_stream}}}


class WriteError(RuntimeError):
    pass


class TaskLock:
    """Re-entrant asyncio lock (per task). Tool calls can run concurrently, but a probe must be followed by
    its Edit.Undo, and a transaction by its read-back/undo, with nothing in between: every tool holds this."""

    def __init__(self):
        self._lock, self._owner, self._depth = asyncio.Lock(), None, 0

    async def __aenter__(self):
        me = asyncio.current_task()
        if self._owner is not me:
            await self._lock.acquire()
            self._owner = me
        self._depth += 1

    async def __aexit__(self, *exc):
        self._depth -= 1
        if self._depth == 0:
            self._owner = None
            self._lock.release()


class Session:
    def __init__(self):
        self.rc = RemoteControl()
        self.bridge = Bridge(self.rc)
        self.log = LogTail()
        self.prober = Prober(self.rc, self.bridge, self.log)
        self._overview = None
        self.lock = TaskLock()
        self.written: set[tuple[int, int]] = set()  # (flow, event id) this server added/removed/changed
        self._library: dict[str, list[dict]] = {}  # collection -> live entities, until the score changes by hand
        self._panel: dict[tuple[int, int], dict] = {}  # (flow, event id) -> selected_props() cache
        self.selections_on_top = 0  # undo steps our reads' selections added since the last write/undo

    # ---------------------------------------------------------------- change tracking
    def _check_changes(self):
        if self.log.changes():
            self.prober.invalidate()
            self._overview = None
            self._panel.clear()
            self._library.clear()
            self.selections_on_top = 0

    def mark_written(self, panel: bool = True):
        """Our own edit happened: drop caches. panel=False keeps the tempo-read cache (transact drops what it touched)."""
        self.prober.invalidate()
        self._overview = None
        if panel:
            self._panel.clear()
        self.selections_on_top = 0
        self.log.skip()

    async def library(self, collection: str) -> list[dict]:
        """The open score's library entities (including ones the user added), live; the catalogued dump offline."""
        if collection not in self._library:
            try:
                r = await self.rc.request({"message": "getlibraryentities", "collection": collection})
                self._library[collection] = r.get("libraryentities") or library_dump(collection)
            except (RCError, OSError, TimeoutError):
                return library_dump(collection)
        return self._library[collection]

    async def undo(self, count: int = 1) -> int:
        """Undo `count` edits, first skipping the selection steps our own reads left on top. Returns Dorico steps."""
        n = count + self.selections_on_top
        await self.rc.undo(n)
        self.mark_written()
        return n

    async def selected_props(self, flow: int, events: list[Event]) -> dict[int, dict]:
        """Event id -> the properties Dorico shows as set on it, read by selecting it (Remote Control getproperties).
        The only read path for events Lua cannot wrap (tempo). Each selection is an undo step, counted in
        selections_on_top so undo() skips them; results are cached until the score changes."""
        self._check_changes()
        todo = [e for e in events if (flow, e.id) not in self._panel]
        for e in todo:
            await self.rc.command(f"EventEdit.Select?FlowID={flow}&EventID={e.id}&EventBlockID={e.block}")
            self.selections_on_top += 1
            for _ in range(3):  # a late selection push can answer the request; it names its event type
                pl = await self.rc.request({"message": "getproperties"})
                if pl.get("eventTypes") == [e.type]:
                    break
            self._panel[(flow, e.id)] = {p["name"]: p["currentValue"] for p in pl.get("properties", []) if "currentValue" in p}
        if todo:
            await self.rc.command("Edit.SelectNone")
            self.selections_on_top += 1
        return {e.id: self._panel[(flow, e.id)] for e in events}

    # ---------------------------------------------------------------- structure
    async def overview(self) -> dict:
        self._check_changes()
        if self._overview is None:
            ov = await self.bridge.run("overview")
            names = {}
            with contextlib.suppress(RCError, OSError, TimeoutError, KeyError):  # names and layouts are extras
                fl = await self.rc.request({"message": "getflows"})
                names = {f["flowID"]: f["flowName"] for f in fl.get("flows", [])}
                ly = await self.rc.request({"message": "getlayouts"})
                lmap = {lay["layoutID"]: lay for lay in ly.get("layouts", [])}
                for lay in ov["layouts"]:
                    lay.update({k: v for k, v in lmap.get(lay["id"], {}).items() if k != "layoutID"})
            rec = self._recorded().get(ov.get("title") or "", {})
            for f in ov["flows"]:
                f["name"] = names.get(f["id"])
                known = {int(k): v for k, v in rec.get(str(f["id"]), {}).items()}
                f["voices"] = {str(k): v for k, v in staff_map(f, known).items()}
            self._overview = ov
        return self._overview

    @staticmethod
    def _recorded() -> dict:
        try:
            return _json.loads(VOICES_FILE.read_text())
        except (FileNotFoundError, ValueError):
            return {}

    async def record_voice(self, flow: int, voice: int, staff_stream: int):
        title = (await self.overview()).get("title") or ""
        data = self._recorded()
        data.setdefault(title, {}).setdefault(str(flow), {})[str(voice)] = staff_stream
        VOICES_FILE.parent.mkdir(parents=True, exist_ok=True)
        VOICES_FILE.write_text(_json.dumps(data, indent=1))
        self._overview = None

    async def flow_info(self, flow: int) -> dict:
        for f in (await self.overview())["flows"]:
            if f["id"] == flow:
                return f
        raise ValueError(f"no flow {flow}")

    async def voices(self, flow: int) -> dict[int, dict]:
        return {int(k): v for k, v in (await self.flow_info(flow))["voices"].items()}

    async def events(self, flow: int, streams: list[int] | None = None, lo=None, hi=None) -> list[Event]:
        rows = await self.bridge.run("read", flow=flow, streams=streams,
                                     **({"from": fstr(lo)} if lo is not None else {}), **({"to": fstr(hi)} if hi is not None else {}))
        return [e for e in build_events(rows) if in_range(e, lo, hi)]

    # ---------------------------------------------------------------- bar map
    async def timebase(self, flow: int) -> list[Event]:
        f = await self.flow_info(flow)
        tb = [s["id"] for s in f["streams"] if s["kind"] == "kGlobalTimebaseStream"]
        return await self.events(flow, tb)

    async def regions(self, flow: int, timebase: list[Event] | None = None):
        tb = timebase if timebase is not None else await self.timebase(flow)
        bds = [e for e in tb if e.type == "kBarDivisionEvent"]
        ts, _ = await self.prober.sealed(flow, [e.element for e in bds], [])
        elems = {b["id"]: b for b in (await self.bridge.run("elements", flow=flow))["bardivs"]}
        divs = []
        for e in bds:
            pick = elems.get(e.element, {}).get("props", {}).get("kBarDivisionIrregularBarLength", "0")
            pk = frac(pick) if pick not in (None, "", "0") else None
            divs.append((e.pos, ts[e.element], pk))
        return bar_regions(divs), bds

    async def bar_map(self, flow: int, keys: bool = False) -> dict:
        tb = await self.timebase(flow)
        regions, _ = await self.regions(flow, tb)
        allev = await self.events(flow)
        music_end = max((e.end for e in allev if e.type not in ("kBarDivisionEvent", "kTonalityDivisionEvent")), default=Fraction(0))
        last_bar, off = bar_at(regions, music_end) if music_end else (1, 0)
        if off == 0 and music_end:
            last_bar -= 1
        key_rows = await self.keys(flow, tb, allev, music_end) if keys else []
        sigs, same = [], []
        for i, r in enumerate(regions):
            row = {"bar": r.first_bar, "pos": fstr(r.start), "timesig": TIMESIG_SHOWN.get(r.timesig, r.timesig),
                   **({"pickup": fstr(r.pickup)} if r.pickup else {})}
            # Dorico stores barlines as bar divisions carrying the current signature; the API cannot tell a
            # barline from a restated signature, so same-as-previous divisions are listed separately
            (same if i and r.timesig == regions[i - 1].timesig and not r.pickup else sigs).append(row)
        return {
            "flow": flow,
            "time_signatures": sigs,
            "barlines_or_restated_signatures": same,
            "key_signatures": key_rows,
            "last_bar_with_music": max(last_bar, 1),
            "note": "bars continue past the last music to the flow end (flow length is not exposed); "
                    "bar_at/bar_start work for any bar",
            "bars": [{"bar": b, "pos": fstr(bar_start(regions, b))} for b in range(1, max(last_bar, 1) + 1)],
        }

    async def keys(self, flow: int, tb: list[Event], allev: list[Event], music_end: Fraction) -> list[dict]:
        regions, _ = await self.regions(flow, tb)
        tons = [e for e in tb if e.type == "kTonalityDivisionEvent"]
        voices = sorted(await self.voices(flow))
        rows = []
        for i, t in enumerate(tons):
            nxt = tons[i + 1].pos if i + 1 < len(tons) else None
            r = await self.prober.key(flow, t, nxt, voices, allev, music_end)
            if r.get("key") is not None:
                r["meaning"] = KEY_NAMES.get(r["key"])
                r["tonic"] = "not readable (major/minor/mode share a signature)"
            rows.append({"bar": bar_at(regions, t.pos)[0], "pos": fstr(t.pos), "event": t.id, **r})
        return rows

    async def to_pos(self, flow: int, bar: int, beat: Fraction = Fraction(0)) -> Fraction:
        """bar number (1-based) + offset in crotchets -> position."""
        regions, _ = await self.regions(flow)
        return bar_start(regions, bar) + frac(beat)

    async def where(self, flow: int, pos: Fraction) -> tuple[int, Fraction]:
        regions, _ = await self.regions(flow)
        return bar_at(regions, pos)

    # ---------------------------------------------------------------- dynamics
    async def dynamics(self, flow: int, events: list[Event]) -> dict[int, dict]:
        """dynamic-group event id -> {value, subs...} for the given events."""
        groups = [e for e in events if e.type == "kDynamicGroupEvent"]
        if not groups:
            return {}
        elems = {g["id"]: g for g in (await self.bridge.run("elements", flow=flow))["dynamics"]}
        refs = []
        for e in groups:
            for s in elems.get(e.element, {}).get("subs", []):
                if s["props"].get("kDynamicImmediateChangeIntensity") == {"sealed": True}:
                    refs.append((e.element, s["id"]))
        _, levels = await self.prober.sealed(flow, [], refs)
        out = {}
        for e in groups:
            parts = []
            for s in elems.get(e.element, {}).get("subs", []):
                p = s["props"]
                part = {"sub": s["id"]}
                if (off := rational(p.get("kDynamicPosition"))) is not None:  # offset from the group's start
                    part["pos"] = fstr(e.pos + off)
                if (e.element, s["id"]) in levels:
                    part["level"] = levels[(e.element, s["id"])]
                    if p.get("kDynamicSubitoFlag"):
                        part["subito"] = True
                if (force := FORCE.get(p.get("kDynamicForceType"))) is not None:
                    no_z = force in ("rfz", "sfz") and not p.get("kDynamicRinforzandoAndSforzandoHaveZ", True)
                    part["level"] = force[:-1] if no_z else force
                if any("Gradual" in k for k in p):
                    kind = "messa di voce" if str(p.get("kDynamicGradualChangeType")) == "1" else \
                        "dim" if str(p.get("kDynamicGradualChangeDirection")) == "1" else "cresc"
                    part["hairpin"] = kind
                    if (length := rational(p.get(HAIRPIN_LENGTH))) is not None:
                        part["length"] = fstr(length)
                parts.append(part)
            out[e.id] = {"parts": parts}
        return out

    # ---------------------------------------------------------------- write transaction
    async def transact(self, flow: int, steps: list[list], verify=None, streams: list[int] | None = None,
                       lo=None, hi=None, timeout: float = 30) -> dict:
        """Run `steps` (lib.lua OPS.tx) as one undo step, read the range back and check it.

        verify(before, after, created) -> error string | None. On a verify failure, or a Lua error after a
        partial change, the transaction is undone immediately (nothing in between) and the range re-checked.
        """
        before = await self.events(flow, streams, lo, hi)
        try:
            res = await self.bridge.run("tx", timeout=timeout, flow=flow, steps=steps)
            error = None
        except StillRunning as e:
            self.mark_written()
            raise WriteError(f"{e}. Nothing was undone: the edit may still complete, so read the range back "
                             "(read_music) before writing there again") from None
        except LuaError as e:
            res, error = {}, str(e).splitlines()[0]
        created = {int(k): v for k, v in res["created"].items()} if isinstance(res.get("created"), dict) else {}
        self.mark_written(panel=False)
        after = await self.events(flow, streams, lo, hi)
        if error is None and verify is not None:
            error = verify(before, after, created)
        if error:
            if _sig(after) != _sig(before):
                await self.rc.undo()
                restored = await self.events(flow, streams, lo, hi)
                self.mark_written()
                tail = "; the change was undone" + ("" if _sig(restored) == _sig(before) else
                                                    " BUT the range does not match the original - check the score")
            else:
                tail = "; nothing was changed"
            raise WriteError(error + tail)
        added, removed = diff(before, after)
        b = {e.id: e for e in before}
        changed = [e for e in after if e.id in b and (e.desc != b[e.id].desc or e.props != b[e.id].props)]
        self.written |= {(flow, e.id) for e in added + removed + changed}
        # tempo properties are invisible to the read-back, so also forget the events the steps selected or set
        touched = {e.id for e in added + removed + changed} | {st[2] for st in steps if st[0] in ("select", "prop")}
        for i in touched:
            self._panel.pop((flow, i), None)
        return {"created": created, "before": before, "after": after}


HAIRPIN_LENGTH = "kDynamicGradualChangeDuration"  # drawn length, on the group's gradual part
FORCE = {0: "fz", 1: "rfz", 2: "sfz", 3: "mfz"}  # kDynamicForceType; sffz reads as sfz, fp is not readable


def _sig(evs: list[Event]):
    return sorted((e.type, e.stream, e.pos, e.dur, e.desc) for e in evs)


def diff(before: list[Event], after: list[Event]) -> tuple[list[Event], list[Event]]:
    b, a = {e.id: e for e in before}, {e.id: e for e in after}
    return [e for i, e in a.items() if i not in b], [e for i, e in b.items() if i not in a]
