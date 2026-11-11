"""Dynamics and hairpins: immediate dynamics, hairpins by events or positions, hairpin lengths. Dorico keeps
a dynamic line in one group (e.g. p<f), so new parts are found by position and kind, not by event id.

Depends on: ops.common, catalog, model, session.
"""
import re
from collections import Counter
from fractions import Fraction

from ..catalog import validate
from ..model import Event, bar_at, frac, fstr, rational
from ..session import Session, WriteError
from .common import (
    SPAN_COMMANDS,
    OpError,
    _anchor_steps,
    advance_steps,
    anchor_steps,
    bar_beat,
    brief,
    caret_steps,
    instrument_voices,
    new_events,
    voice_stream,
)

DYNAMIC_RX = re.compile(r"^(n|p{1,6}|f{1,6}|mp|mf|s?fz|sfp|sffz|rfz?|rf|fp|pf|sf|sfpp|fzp|[pfm<>.\w ]{1,20})$")
HAIRPINS = {"cresc", "dim", "messa_di_voce"}
LENGTH = "kDynamicGradualChangeDuration"


async def _dynamic_groups(s: Session, flow: int, pos: Fraction) -> list[tuple[Event, list[dict]]]:
    """Dynamic-group events starting at pos, each with its element's sub-elements ({id, props})."""
    evs = [e for e in await s.events(flow, None, pos, pos + Fraction(1, 64)) if e.type == "kDynamicGroupEvent" and e.pos == pos]
    elems = {g["id"]: g for g in (await s.bridge.run("elements", flow=flow))["dynamics"]}
    return [(e, elems.get(e.element, {}).get("subs", [])) for e in evs]


def _gradual(subs: list[dict]) -> dict | None:
    return next((x for x in reversed(subs) if any("Gradual" in k for k in x["props"])), None)


def _length(sub: dict | None) -> Fraction | None:
    if sub is None:
        return None
    try:
        return frac(sub["props"][LENGTH])
    except (TypeError, KeyError, ValueError, ZeroDivisionError):
        return None


async def _hairpin_part(s: Session, flow: int, group: Event, part_id: int | None = None) -> dict | None:
    subs = {g.id: x for g, x in await _dynamic_groups(s, flow, group.pos)}.get(group.id, [])
    return next((x for x in subs if x["id"] == part_id), None) if part_id is not None else _gradual(subs)


async def _parts(s: Session, flow: int, lo: Fraction, hi: Fraction) -> list[tuple[Event, dict]]:
    """(dynamic-group event, sub-element) for every group overlapping [lo, hi)."""
    evs = [e for e in await s.events(flow, None, lo, hi) if e.type == "kDynamicGroupEvent"]
    elems = {g["id"]: g for g in (await s.bridge.run("elements", flow=flow))["dynamics"]}
    return [(e, x) for e in evs for x in elems.get(e.element, {}).get("subs", [])]


def _key(g: Event, x: dict) -> tuple:
    """A dynamic part by what it is: its group's element, absolute position and whether it is a hairpin. Sub ids are
    indexes in the group: a dynamic put before a hairpin renumbers it."""
    return g.element, g.pos + (rational(x["props"].get("kDynamicPosition")) or 0), any("Gradual" in k for k in x["props"])


def new_parts(before: list[tuple[Event, dict]], after: list[tuple[Event, dict]]) -> list[tuple[Event, dict]]:
    left = Counter(_key(g, x) for g, x in before)
    out = []
    for g, x in after:
        if left[_key(g, x)]:
            left[_key(g, x)] -= 1
        else:
            out.append((g, x))
    return out


async def set_hairpin_length(s: Session, flow: int, group: Event, length: Fraction, part_id: int | None = None) -> dict:
    """Set a hairpin's drawn length in crotchets. Dorico draws it from the gradual sub-element of the dynamic
    group, for a hairpin on its own as well as one joined to a dynamic (p<); the event's property of the same name
    is not drawn. Only Lua can address the sub-element, so the element table is read back."""
    part = await _hairpin_part(s, flow, group, part_id)
    if part is None or not any("Gradual" in k for k in part["props"]):
        raise OpError(f"dynamic group {group.id} has no hairpin" + (f" with sub id {part_id}" if part_id is not None else ""))
    if _length(part) == length:
        return {"length": fstr(length)}
    # element edits are invisible to transact's event read-back, so this checks the element table itself
    await s.transact(flow, [["subprop", group.element, part["id"], LENGTH, fstr(length)]])
    after = await _hairpin_part(s, flow, group, part["id"])
    if after is None or after["props"] == part["props"]:
        raise WriteError(f"the hairpin in dynamic group {group.id} still reads length {part['props'].get(LENGTH)}; "
                         "nothing readable changed")
    if _length(after) != length:
        await s.rc.undo()
        s.mark_written()
        raise WriteError(f"the hairpin's length reads {after['props'].get(LENGTH)}, expected {fstr(length)}; the change was undone")
    return {"length": fstr(length)}


async def _add_hairpin(s: Session, flow: int, start: Fraction, end: Fraction, kind: str, steps: list[list]) -> dict:
    """Run `steps` (which start a hairpin at `start`) and make it end at `end`, whichever way Dorico builds it: a
    hairpin starting where a dynamic already is joins that group (no new event, a new sub-element), and the
    selection-based length can stop short or overshoot. So the drawn length is always read and set."""
    lo, hi = start - 64, end + 4
    known = await _parts(s, flow, lo, hi)
    r = await s.transact(flow, steps, None, None, start - 1, end + 4)
    new = [e for e in new_events(r["before"], r["after"], "kDynamicGroupEvent") if e.pos == start]
    # a hairpin joins the group of a dynamic at its start note, or of a hairpin ending exactly there
    added = new_parts(known, await _parts(s, flow, lo, hi))
    if not new and not added:
        await s.rc.undo()  # the transaction is an undo step even when it created nothing (it selected)
        s.mark_written()
        raise WriteError(f"no {kind} was created at {fstr(start)}; the change was undone")
    group = new[0] if new else added[0][0]
    part = None if new else (_gradual([x for _, x in added]) or added[0][1])
    target = end - start
    regions, _ = await s.regions(flow)
    res = {"hairpin": kind, "from": bar_beat(regions, start), "to": bar_beat(regions, end)}
    part_id = part["id"] if part else None
    if new:
        res["created"] = [brief(group, regions)]
    else:
        res["merged_into"] = brief(group, regions)
        res["note"] = (f"Dorico joined the {kind} to the dynamic group starting at bar {res['merged_into']['bar']} beat "
                       f"{res['merged_into']['beat']} (a dynamic at its start, or a hairpin ending there); its part is "
                       f"sub {part_id}")
    try:
        res.update(await set_hairpin_length(s, flow, group, target, part_id))
    except (WriteError, OpError) as e:
        drawn = _length(await _hairpin_part(s, flow, group, part_id))
        res["length"] = fstr(drawn) if drawn else None
        res["warning"] = (f"the {kind} was created, but its drawn length is {res['length'] or 'unreadable'}, not "
                          f"{fstr(target)}; setting it failed: {e}")
    got = await _hairpin_part(s, flow, group, part_id)
    off = rational(got["props"].get("kDynamicPosition")) if got else None
    if off is not None and group.pos + off != start:
        res["warning"] = (res.get("warning", "") + f" the hairpin starts at {fstr(group.pos + off)}, not {fstr(start)}").strip()
    return res


async def add_hairpin(s: Session, flow: int, voice: int, start: Fraction, end: Fraction, kind: str,
                      voices: list[int] | None = None) -> dict:
    """A hairpin from one position to another on the instrument of each voice. It starts on a note or rest starting
    at `start` in any voice of the instrument (or a temporary rest in a silent voice, or the note-input caret where
    a note is held through `start`), then its drawn length is set to end - start."""
    if kind not in HAIRPINS:
        raise OpError(f"kind one of {sorted(HAIRPINS)}")
    if end <= start:
        raise OpError("the hairpin must end after it starts")
    cmd = SPAN_COMMANDS[kind][0]
    out = []
    for v in voices or [voice]:
        await voice_stream(s, flow, v)
        near = await instrument_voices(s, flow, v)
        try:
            sel, cleanup, _ = await _anchor_steps(s, flow, start, near)
            steps = sel + [["cmd", cmd]] + cleanup
        except OpError:
            sel, cleanup, g = await caret_steps(s, flow, start, near, extra=(end - start,))
            steps = sel + [["cmd", cmd]] + advance_steps(g, end - start) + [["cmd", "NoteInput.HairpinStop"]] + cleanup
        out.append({"voice": v, **await _add_hairpin(s, flow, start, end, kind, steps)})
    return out[0] if len(out) == 1 else {"hairpins": out}


async def add_dynamic(s: Session, flow: int, voices: list[int], targets: list[tuple[Fraction, str]]) -> dict:
    """Immediate dynamics: each (pos, value) of targets on the instrument of each voice, all in one undo step.

    Anchored on a note or rest starting there in any voice of the instrument, a temporary rest in a silent voice, or
    the note-input caret where a note is held through the position. A dynamic next to a hairpin or another dynamic
    joins that group (Dorico's dynamic line: no new event), so success is read from the groups' parts. A dynamic where
    one already is replaces it."""
    for _, value in targets:
        if not DYNAMIC_RX.match(value):
            raise OpError(f"bad dynamic {value!r}: like p, pp, mf, ff, sfz, fp")
    steps = []
    for v in voices:
        await voice_stream(s, flow, v)
        near = await instrument_voices(s, flow, v)
        for pos, value in targets:
            command = f"NoteInput.CreateDynamic?Definition={value}"
            validate(command)
            sel, cleanup, _ = await anchor_steps(s, flow, pos, near, caret=True)
            steps += sel + [["cmd", command]] + cleanup
    lo, hi = min(p for p, _ in targets) - 64, max(p for p, _ in targets) + 1
    known = await _parts(s, flow, lo, hi)
    # verified after the transaction: a merged dynamic only shows in the element table
    await s.transact(flow, steps, None, None, lo + 63, hi + 8)
    now = await _parts(s, flow, lo, hi)
    added = [(g, x) for g, x in new_parts(known, now) if not _key(g, x)[2]]
    at = {_key(g, x)[1] for g, x in added}
    # a dynamic where one already is replaces it (no new part): accept it when the part there now reads the new level
    old = {_key(g, x)[1]: (g, x) for g, x in known if not _key(g, x)[2]}
    redo = [(p, v) for p, v in targets if p not in at and p in old]
    if redo:
        cur = {_key(g, x)[1]: (g, x) for g, x in now if not _key(g, x)[2]}
        lv = await s.dynamics(flow, list({g.id: g for g, _ in (cur[p] for p, _ in redo if p in cur)}.values()))
        for p, v in redo:
            if p not in cur:
                continue
            g, x = cur[p]
            part = next((q for q in lv.get(g.id, {}).get("parts", []) if q["sub"] == x["id"]), {})
            if part.get("level") in (v, None):  # sfz, fp...: levels not readable
                added.append((g, x))
                at.add(p)
    missing = [p for p, _ in targets if p not in at]
    if len(added) < len(targets) * len(voices) or missing:
        await s.rc.undo()
        s.mark_written()
        where = ", ".join(fstr(p) for p in missing) or ", ".join(fstr(p) for p, _ in targets)
        raise WriteError(f"{len(added)} of {len(targets) * len(voices)} dynamics created (none at {where}); the change was undone")
    regions, _ = await s.regions(flow)
    groups = {g.id: g for g, _ in added}
    levels = await s.dynamics(flow, list(groups.values()))
    new_subs = {(g.id, x["id"]) for g, x in added}
    out = []
    for gid, d in levels.items():
        for part in d["parts"]:
            if (gid, part["sub"]) in new_subs:
                pos = frac(part["pos"]) if "pos" in part else groups[gid].pos
                bar, beat = bar_at(regions, pos)
                out.append({"group": gid, "sub": part["sub"], "level": part.get("level"), "bar": bar, "beat": fstr(beat),
                            **({"replaced_existing": True} if pos in {q for q, _ in redo} else {}),
                            **({"joined_group_at": fstr(groups[gid].pos)} if groups[gid].pos != pos or len(d["parts"]) > 1 else {})})
    return {"dynamics": sorted(out, key=lambda x: (x["bar"], frac(x["beat"])))}
