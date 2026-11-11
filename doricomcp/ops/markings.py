"""Markings: articulations, spans (slurs, lines), note markings (ornaments, holds, techniques), signatures,
tempo, barlines, repeats, rehearsal marks, breaks, text, clefs, and event properties.

Depends on: ops.dynamics, ops.common, catalog, model, session.
"""
import re
from fractions import Fraction

from ..catalog import technique
from ..model import Event, frac, fstr
from ..session import Session, WriteError
from .common import (
    SPAN_COMMANDS,
    OpError,
    _events_by_id,
    _positional,
    all_voices,
    brief,
    new_events,
    select_apply,
    select_step,
    staff_stream,
    staff_voices,
)
from .dynamics import HAIRPINS, LENGTH, _add_hairpin, set_hairpin_length

ARTICULATIONS = {"staccato": "kStaccato", "staccatissimo": "kStaccatissimo", "tenuto": "kTenuto", "accent": "kAccent",
                 "marcato": "kMarcato", "stress": "kStress", "unstress": "kUnstress", "staccato_tenuto": "kStaccatoTenuto"}
# note property and values that mean the articulation is already there (values as reads.ARTIC_NAMES)
ARTICULATION_PROPS = {"staccato": ("kArticulationDuration", {0, 1}), "staccatissimo": ("kArticulationDuration", {2}),
                      "tenuto": ("kArticulationDuration", {3}), "staccato_tenuto": ("kArticulationDuration", {4}),
                      "accent": ("kArticulationForce", {0}), "marcato": ("kArticulationForce", {1}),
                      "stress": ("kArticulationStress", {0}), "unstress": ("kArticulationStress", {1})}


def articulation_targets(evs: list[Event], kind: str) -> list[int]:
    """SetArticulation is a toggle that acts on the whole chord (measured: selecting both notes of a chord in turn
    set it, then cleared it). So one note per chord, and none where the articulation is already set."""
    prop, values = ARTICULATION_PROPS[kind]

    def has(e):
        try:
            return int(e.props.get(prop)) in values
        except (TypeError, ValueError):
            return False

    chords = {}
    for e in evs:
        chords.setdefault((e.stream, e.pos), []).append(e)
    return [next(e.id for e in g if not has(e)) for g in chords.values() if not all(has(e) for e in g)]


async def add_articulation(s: Session, flow: int, event_ids: list[int], kind: str) -> dict:
    if kind not in ARTICULATIONS:
        raise OpError(f"unknown articulation {kind!r}; one of {sorted(ARTICULATIONS)}")
    evs = await _events_by_id(s, flow, event_ids)
    targets = articulation_targets([evs[i] for i in event_ids], kind)
    if not targets:
        return {"added": [], "removed": [], "changed": [], "note": f"every chord given already has {kind}"}
    return await select_apply(s, flow, targets, [f"NoteInput.SetArticulation?Value={ARTICULATIONS[kind]}"])


async def set_property(s: Session, flow: int, event_ids: list[int], name: str, value: str | None, part: int | None = None) -> dict:
    """part: for kDynamicGradualChangeDuration, the hairpin's sub id in its dynamic group (read_markings parts), when a
    group holds several hairpins (> <); without it the group's last hairpin is set."""
    if not re.fullmatch(r"k[A-Za-z0-9]+", name):
        raise OpError(f"bad property name {name!r}")
    if value is not None and re.search(r"[&?\s]", value):
        raise OpError("property values cannot contain spaces, & or ?")
    evs = await _events_by_id(s, flow, event_ids)
    if name == LENGTH and value is not None:
        if bad := [i for i in event_ids if evs[i].type != "kDynamicGroupEvent"]:
            raise OpError(f"{LENGTH} applies to hairpins (dynamic groups); events {bad} are not")
        return {"values": {i: (await set_hairpin_length(s, flow, evs[i], frac(value), part))["length"] for i in event_ids}}
    steps = [["prop", evs[i].stream, i, name, value] for i in event_ids]

    def verify(before, after, created):
        a = {e.id: e for e in after}
        bad = []
        for i in event_ids:
            got = a[i].props.get(name) if i in a else None
            if value is None and got is not None:
                bad.append(f"{i}: still {got!r}")
            if value is not None and got is None and a.get(i) and a[i].source == "events":
                bad.append(f"{i}: not set")
        return "; ".join(bad) or None

    lo = min(e.pos for e in evs.values()) - 1
    hi = max(e.end for e in evs.values()) + 1
    r = await s.transact(flow, steps, verify, None, lo, hi)
    a = {e.id: e for e in r["after"]}
    return {"values": {i: (a[i].props.get(name) if i in a else None) for i in event_ids}}


# ------------------------------------------------------------------ spans (select start, extend to end)

LINES = {"8va", "8vb", "15ma", "15mb", "glissando"}  # Dorico extends these to the next onset


async def span_steps(s: Session, flow: int, a: Event, b: Event, cmd: str, kind: str) -> list:
    """Select a and extend the selection to b, then run cmd. Extending steps through the onsets of every voice on
    the staff and selects all of them, so Dorico gives each voice its own slur; the slurs
    the command adds to the other voices are deleted in the same script."""
    staff = await staff_voices(s, flow, a.stream)
    evs = await s.events(flow, staff, a.pos, b.pos + Fraction(1, 64))
    onsets = {e.pos for e in evs if e.type in ("kNoteEvent", "kRestEvent") and a.pos < e.pos <= b.pos}
    core = [select_step(flow, a)] + [["cmd", "EventEdit.NavigateRightExtend"]] * len(onsets) + [["cmd", cmd], ["selectnone"]]
    if kind != "slur" or len(staff) == 1:
        return core
    return [["mark", "kSlurEvent", staff]] + core + [["delete_new", "kSlurEvent", a.stream]]


async def add_span(s: Session, flow: int, kind: str, start_id: int | None = None, end_id: int | None = None,
                   spans: list[list[int]] | None = None) -> dict:
    """Slurs/hairpins/ottavas/glissandi from one note to another in the same voice; spans: several [start, end]
    pairs in one call (one undo step for slurs, ottavas and glissandi). Only that voice gets a slur."""
    if kind not in SPAN_COMMANDS:
        raise OpError(f"unknown span kind {kind!r}; one of {sorted(SPAN_COMMANDS)}")
    given = [tuple(x) for x in spans] if spans else [(start_id, end_id)]
    if any(len(x) != 2 or None in x for x in given):
        raise OpError("give start_event_id and end_event_id, or spans as [[start_id, end_id], ...]")
    pairs = [(i, j) for i, j in given if i is not None and j is not None]
    cmd, types = SPAN_COMMANDS[kind]
    evs = await _events_by_id(s, flow, sorted({i for x in pairs for i in x}))
    for i, j in pairs:
        if evs[i].stream != evs[j].stream:
            raise OpError(f"{i} -> {j}: start and end must be in the same voice")
        if evs[j].pos <= evs[i].pos:
            raise OpError(f"{i} -> {j}: the end note must come after the start note")
    if kind in HAIRPINS:
        out = [await _add_hairpin(s, flow, evs[i].pos, evs[j].end, kind, await span_steps(s, flow, evs[i], evs[j], cmd, kind))
               for i, j in pairs]
        return out[0] if len(out) == 1 else {"hairpins": out}
    steps = [st for i, j in pairs for st in await span_steps(s, flow, evs[i], evs[j], cmd, kind)]
    slack = Fraction(4) if kind in LINES else Fraction(0)

    def match(new, a, b):
        # slurs live in their voice's stream; octave lines may sit on the staff, so they are matched by position
        return [e for e in new if (kind != "slur" or e.stream == a.stream) and e.pos == a.pos
                and (not e.dur or b.pos <= e.end <= b.end + slack)]

    def verify(before, after, created):
        new = new_events(before, after, types)
        bad = [f"{i} -> {j}" for i, j in pairs if not match(new, evs[i], evs[j])]
        if bad:
            return f"no {kind} from the start to the end note for {', '.join(bad)}"
        mine = {e.id for i, j in pairs for e in match(new, evs[i], evs[j])}
        if kind == "slur" and (stray := [e for e in new if e.id not in mine]):
            return f"{len(stray)} extra slur(s) appeared in streams {sorted({e.stream for e in stray})}"
        return None

    lo = min(evs[i].pos for i, _ in pairs) - 1
    hi = max(evs[j].end for _, j in pairs) + 4
    r = await s.transact(flow, steps, verify, None, lo, hi)
    regions, _ = await s.regions(flow)
    return {"created": [brief(e, regions) for e in new_events(r["before"], r["after"], types)]}


# ------------------------------------------------------------------ markings on a note (select + popover/command)

HOLDS = {"fermata", "fermata short", "fermata long", "breath", "caesura", "fermata very short", "fermata very long"}
ORNAMENT_RX = re.compile(r"^(tr|trill|mordent|inv|inverted mordent|turn|inverted turn|haydn|shake|[a-z ]{2,30})$", re.IGNORECASE)


async def add_note_marking(s: Session, flow: int, event_ids: list[int], kind: str, value: str = "") -> dict:
    """ornament (value: tr, mordent, turn...), hold (fermata, breath, caesura), playing_technique (value: a name
    like pizz., arco, con sord., sul pont., ord., or a library id like pta.pizzText), tie, articulation (staccato...)."""
    if kind == "ornament":
        if not ORNAMENT_RX.match(value):
            raise OpError("ornament value: tr, mordent, inv, turn ...")
        cmds = [f"NoteInput.CreateOrnament?Definition={value}"]
    elif kind == "hold":
        if value not in HOLDS:
            raise OpError(f"hold value one of {sorted(HOLDS)}")
        cmds = [f"NoteInput.CreatePause?Definition={value}"]
    elif kind == "playing_technique":
        try:
            value = technique(value, await s.library("kPlayingTechniqueAppearanceCollection"))["entityID"]
        except ValueError as e:
            raise OpError(str(e)) from None
        cmds = [f"NoteInput.CreatePlayingTechnique?PlayingTechniqueAppearanceEntityID={value}"]
    elif kind == "articulation":
        return await add_articulation(s, flow, event_ids, value)
    elif kind == "tie":
        cmds = ["NoteInput.Tie"]
    else:
        raise OpError("kind one of ornament, hold, playing_technique, articulation, tie")
    return await select_apply(s, flow, event_ids, cmds)


# ------------------------------------------------------------------ positional markings (anchored selection)

TIMESIG_RX = re.compile(r"^(\[?\d+(\+\d+)*\]?/\d+|c|cut|C|X/\d+|\d+/\d+\s*\(.*\))$")
KEY_RX = re.compile(r"^(\d[#sbf]|[A-Ga-g](#|b)?( ?(major|minor|m))?|0|open|atonal)$")
TEMPO_RX = re.compile(r"^[^&?]{1,60}$")
BARLINES = {"|": "single", "||": "double", "|:": "start repeat", ":|": "end repeat", ":|:": "end-start repeat",
            "|||": "final", ":": "dashed", "'": "tick"}
REPEATS = {"segno", "coda", "fine", "to coda", "D.C.", "D.C. al Fine", "D.C. al Coda", "D.S.", "D.S. al Fine", "D.S. al Coda"}


async def set_time_signature(s: Session, flow: int, pos: Fraction, value: str) -> dict:
    if not TIMESIG_RX.match(value):
        raise OpError("time signature like 3/4, 6/8, 2+3/8, [2+2+3]/8, c, cut, X/4")
    res = await _positional(s, flow, pos, f"NoteInput.CreateTimeSignature?Definition={value}", {"kBarDivisionEvent"}, await all_voices(s, flow))
    if re.fullmatch(r"\d+/\d+", value) and res["created"]:
        el = res["created"][0].get("element")
        ts, _ = await s.prober.sealed(flow, [el], [])
        res["read_back"] = ts[el]
        if ts[el] != value:
            await s.rc.undo()
            s.mark_written()
            raise WriteError(f"time signature read back as {ts[el]}, expected {value}; the change was undone")
    return res


async def set_key_signature(s: Session, flow: int, pos: Fraction, value: str) -> dict:
    if not KEY_RX.match(value):
        raise OpError("key like 2# (sharps), 3b (flats), 0, Eb, F#m, c minor, open")
    return await _positional(s, flow, pos, f"NoteInput.CreateKeySignature?Definition={value}", {"kTonalityDivisionEvent"}, await all_voices(s, flow))


async def set_tempo(s: Session, flow: int, pos: Fraction, value: str) -> dict:
    if not TEMPO_RX.match(value):
        raise OpError("tempo text like q=120, Allegro q=132, h.=60, rit., a tempo")
    return await _positional(s, flow, pos, f"NoteInput.CreateTempo?Definition={value}",
                             {"kImmediateTempoChangeEvent", "kGradualTempoChangeEvent", "kTempoEvent"}, await all_voices(s, flow))


async def add_barline(s: Session, flow: int, bar: int, kind: str) -> dict:
    if kind not in BARLINES:
        raise OpError(f"barline one of {BARLINES}")
    pos = await s.to_pos(flow, bar)
    return await _positional(s, flow, pos, f"NoteInput.CreateBarLine?Definition={kind}",
                             {"kBarDivisionEvent", "kBarlineEvent"}, await all_voices(s, flow))


async def add_repeat_marker(s: Session, flow: int, pos: Fraction, value: str) -> dict:
    if value not in REPEATS:
        raise OpError(f"repeat marker one of {sorted(REPEATS)}")
    return await _positional(s, flow, pos, f"NoteInput.AddRepeatsToSelection?Definition={value}", {"kRepeatMarkerEvent"}, await all_voices(s, flow))


async def add_rehearsal_mark(s: Session, flow: int, pos: Fraction) -> dict:
    return await _positional(s, flow, pos, "NoteInput.CreateRehearsalMark", {"kRehearsalMarkEvent"}, await all_voices(s, flow))


async def add_break(s: Session, flow: int, bar: int, kind: str = "system") -> dict:
    cmd = {"system": "Edit.CreateSystemBreak", "frame": "Edit.CreateFrameBreak"}.get(kind)
    if not cmd:
        raise OpError("kind: system or frame")
    pos = await s.to_pos(flow, bar)
    return await _positional(s, flow, pos, cmd, {"kBreakEvent"}, await all_voices(s, flow))


async def add_hold_at(s: Session, flow: int, pos: Fraction, value: str = "fermata") -> dict:
    if value not in HOLDS:
        raise OpError(f"hold one of {sorted(HOLDS)}")
    return await _positional(s, flow, pos, f"NoteInput.CreatePause?Definition={value}", {"kPauseEvent"}, await all_voices(s, flow))


# ------------------------------------------------------------------ Lua-created markings

async def add_text(s: Session, flow: int, voice: int, pos: Fraction, text: str) -> dict:
    if not text or len(text) > 500:
        raise OpError("text must be 1-500 characters")

    def verify(before, after, created):
        return None if new_events(before, after, "kTextEvent", pos) else "text not created"

    r = await s.transact(flow, [["text", voice, fstr(pos), "0", text]], verify, [voice], pos - 1, pos + 1)
    return {"created": [e.json() for e in new_events(r["before"], r["after"], "kTextEvent")]}


async def add_clef(s: Session, flow: int, voice: int, pos: Fraction, clef: str) -> dict:
    """clef: library id (clef.treble, clef.bass, clef.alto, clef.tenor, clef.treble8ba...) on the voice's staff."""
    if not re.fullmatch(r"clef\.[A-Za-z0-9.\-]+", clef):
        raise OpError("clef must be a library id like clef.treble, clef.bass, clef.alto (list_library kClefCollection)")
    stave = await staff_stream(s, flow, voice)

    def verify(before, after, created):
        new = new_events(before, after, "kClefEvent", pos)
        if not new:
            return "clef not created"
        return None if clef in new[0].desc else f"clef created as {new[0].desc}, expected {clef}"

    r = await s.transact(flow, [["clef", stave, fstr(pos), clef]], verify, [stave], pos - 1, pos + 1)
    return {"created": [e.json() for e in new_events(r["before"], r["after"], "kClefEvent")]}
