"""Sealed-value readers with a cache invalidated on score changes.

- Time signatures and dynamic levels: the equality method. The probe script creates orphan candidate
  elements that no binding can delete, so we issue Edit.Undo *immediately* after it (no selection in
  between) and verify the element counts are back to their pre-probe values.
- Key signatures: letter-name entry into an empty span of a voice, read Dorico's spelling, delete the
  probe notes in the same script. Lazy (only on request): it auditions 7 notes and needs empty music.

Depends on: bridge, logtail, model, rc.
"""
from fractions import Fraction

from .bridge import Bridge
from .logtail import LogTail
from .model import Event, fstr, key_from_spelling
from .rc import RemoteControl


class ProbeError(RuntimeError):
    pass


class Prober:
    def __init__(self, rc: RemoteControl, bridge: Bridge, log: LogTail):
        self.rc, self.bridge, self.log = rc, bridge, log
        self.timesigs: dict[tuple[int, int], str] = {}  # (flow, bar-division element) -> "3/4"
        self.dynamics: dict[tuple[int, int, int], str] = {}  # (flow, group, sub) -> "pp"
        self.keys: dict[tuple[int, int], str] = {}  # (flow, tonality event id) -> "3b"

    def invalidate(self):
        self.timesigs.clear()
        self.dynamics.clear()
        self.keys.clear()

    async def sealed(self, flow: int, bardivs: list[int], dynamics: list[tuple[int, int]]):
        """Identify time signatures (by element id) and immediate dynamics ((group, sub)); cached."""
        need_bd = [b for b in bardivs if (flow, b) not in self.timesigs]
        need_dy = [d for d in dynamics if (flow, *d) not in self.dynamics]
        if need_bd or need_dy:
            res = await self.bridge.run("probe_sealed", flow=flow, bardivs=need_bd, dynamics=[list(d) for d in need_dy])
            if res["created"]:
                # the probe script is one undo step holding only the orphan candidates
                await self.rc.undo()
                after = await self.bridge.run("element_counts", flow=flow)
                if after != res["before"]:
                    raise ProbeError(f"probe cleanup failed: element counts {after} != before {res['before']}")
            self.log.skip()
            for r in res["timesigs"]:
                self.timesigs[(flow, r["id"])] = r["value"]
            for r in res["dynamics"]:
                self.dynamics[(flow, r["group"], r["sub"])] = r["value"]
        return ({b: self.timesigs[(flow, b)] for b in bardivs},
                {d: self.dynamics[(flow, *d)] for d in dynamics})

    async def key(self, flow: int, tonality: Event, region_end: Fraction | None, voices: list[int],
                  events: list[Event], flow_music_end: Fraction) -> dict:
        """Key signature in force from `tonality` (a kTonalityDivisionEvent) up to region_end."""
        cache = (flow, tonality.id)
        if cache in self.keys:
            return {"key": self.keys[cache], "method": "letter-probe (cached)"}
        status = await self.rc.status()
        if status.get("insertActive") or status.get("noteInputActive"):
            return {"key": None, "reason": "note input or insert mode is active; key probe skipped"}
        span = Fraction(7)
        limit = min(x for x in (region_end, flow_music_end) if x is not None)
        for v in voices:
            busy = sorted((e.pos, max(e.end, e.pos + Fraction(1, 64))) for e in events if e.stream == v)
            start = tonality.pos
            for b0, b1 in busy + [(limit, limit)]:
                if b0 >= start + span and start + span <= limit:
                    break
                start = max(start, b1)
            else:
                continue
            if start + span > limit:
                continue
            res = await self.bridge.run("probe_key", flow=flow, stream=v, pos=fstr(start), end=fstr(start + span))
            self.log.skip()
            if res["left"]:
                raise ProbeError(f"key probe left {res['left']} events in stream {v} at {fstr(start)}")
            key = key_from_spelling(res["spelled"])
            if key is None or len(res["spelled"]) != 7:
                return {"key": None, "reason": f"unexpected probe spelling {res['spelled']}"}
            self.keys[cache] = key
            return {"key": key, "method": "letter-probe", "probe_at": {"stream": v, "pos": fstr(start)}}
        return {"key": None, "reason": "no empty 7-crotchet span inside the key region before the end of the music"}
