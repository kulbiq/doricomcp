"""Notes: writing, replacing and deleting notes, edits on existing notes (pitch, duration, respelling), copy,
move and swap, and note input (tuplets, new voices).

Depends on: ops.common, catalog, model, session.
"""
import re
from fractions import Fraction

from ..catalog import validate
from ..model import PITCH, Event, bar_at, fstr, spelling_to_midi
from ..session import Session, WriteError, diff
from .common import (
    CLEARABLE,
    OpError,
    _events_by_id,
    anchor_steps,
    bar_beat,
    brief,
    check_pitch,
    clear_steps,
    new_events,
    parse_duration,
    parse_notes,
    resolve_pos,
    select_apply,
    select_step,
    staff_voices,
    voice_stream,
)

# ------------------------------------------------------------------ notes

# 24-EDO accidentals by alteration (a fraction of an octave, as Dorico spells it)
QUARTER_TONES = {Fraction(1, 24): "quarter-sharp", Fraction(-1, 24): "quarter-flat",
                 Fraction(1, 8): "three-quarters-sharp", Fraction(-1, 8): "three-quarters-flat"}


def note_steps(voice: int, t: Fraction, d: Fraction, p: str) -> list[list]:
    """Lua's pitch parser ignores microtonal alterations, so such a note is written as its letter and octave, then
    selected and given its accidental (Stein-Zimmermann symbols; the score needs a 24-EDO key signature)."""
    m = PITCH.match(p)
    if not m or "/" not in (m.group(2) or ""):
        return [["note", voice, fstr(t), fstr(d), p]]
    acc = QUARTER_TONES.get(Fraction(m.group(2)))
    if acc is None:
        raise OpError(f"{p}: only quarter-tone alterations are supported (1/24, -1/24, 1/8, -1/8 of an octave)")
    return [["note", voice, fstr(t), fstr(d), m.group(1) + m.group(3)], ["select_created", voice, -1],
            ["cmd", f"NoteInput.SetAccidental?AccidentalDefinitionID=accidental.24et.western.{acc}.stein"], ["selectnone"]]


async def add_notes(s: Session, flow: int, voice: int, notes: str, bar=None, beat=None, pos=None, replace: bool = False) -> dict:
    """Write notes/chords/rests sequentially from a position into a voice. replace=True clears the span's notes and
    rests first; its text and other markings stay, and its slurs are put back on the new notes (Dorico deletes a slur
    with its notes)."""
    await voice_stream(s, flow, voice)
    start = await resolve_pos(s, flow, bar, beat, pos)
    items = parse_notes(notes)
    steps, t, expect, onset_step = [], start, [], {}
    total = sum((d for _, d in items), Fraction(0))
    end = start + total
    slurs, staff, near = [], [voice], []
    if replace:
        staff = await staff_voices(s, flow, voice)
        near = await s.events(flow, staff, start - 16, end + 16)
        slurs = [e for e in near if e.stream == voice and e.type == "kSlurEvent" and e.pos < end and e.end > start and e.block is not None]
        steps += [["cmd", f"EventEdit.Delete?FlowID={flow}&EventID={e.id}&EventBlockID={e.block}"] for e in slurs]
        steps += clear_steps(flow, near, voice, start, end)
    for pitches, d in items:
        if pitches is None:
            steps.append(["rest", voice, fstr(t), fstr(d)])
            expect.append(("kRestEvent", t, d, None))
        else:
            onset_step[t] = len(steps) + 1  # Lua step index (1-based) of the note to select
            for p in pitches:
                steps += note_steps(voice, t, d, p)
                expect.append(("kNoteEvent", t, d, p))
        t += d
    lost = []
    if slurs:  # the notes around each slur after writing: the new ones inside the span, the old ones outside it
        outside = [e for e in near if e.stream == voice and e.type == "kNoteEvent" and not start <= e.pos < end]
        mine = sorted(set(onset_step) | {e.pos for e in outside})
        other = {e.pos for e in near if e.stream != voice and e.type in ("kNoteEvent", "kRestEvent")}
        rests = set(_rest_onsets(items, start))
        voice_rests = {e.pos for e in near if e.stream == voice and e.type == "kRestEvent" and not start <= e.pos < end}
        for sl in slurs:
            first = next((x for x in mine if x == sl.pos), None)
            last = max((x for x in mine if sl.pos < x <= sl.end), default=None)  # a slur ends where its end note starts
            if first is None or last is None:
                lost.append(sl)
                continue
            pick = ["select_created", voice, onset_step[first]] if first in onset_step else \
                select_step(flow, next(e for e in outside if e.pos == first))
            hops = {x for x in set(mine) | other | rests | voice_rests if first < x <= last}
            steps += ([["mark", "kSlurEvent", staff]] if len(staff) > 1 else []) + [pick] + \
                [["cmd", "EventEdit.NavigateRightExtend"]] * len(hops) + [["cmd", "NoteInput.SlurStart"], ["selectnone"]] + \
                ([["delete_new", "kSlurEvent", voice]] if len(staff) > 1 else [])

    def verify(before, after, created):
        added, _ = diff(before, after)
        for ty, p, d, sp in expect:
            if not any(e.type == ty and e.pos == p and e.dur == d and (sp is None or e.spelling == sp
                       or e.midi == spelling_to_midi(sp)) for e in added + after):
                hint = (" (a quarter-tone needs the score in 24-EDO at that point: set it in Dorico's Key Signatures "
                        "panel; Dorico's interfaces cannot change the tonality system)") if sp and "/" in sp else ""
                return f"expected {ty} {sp or ''} at {fstr(p)} dur {fstr(d)} not found after writing{hint}"
        back = [e for e in added if e.type == "kSlurEvent" and e.stream == voice]
        if len(back) != len(slurs) - len(lost):
            return f"{len(back)} of {len(slurs) - len(lost)} slurs put back on the new notes"
        return None

    r = await s.transact(flow, steps, verify, staff if replace else [voice], start - 16, max(t, end) + 16)
    added, removed = diff(r["before"], r["after"])
    regions, _ = await s.regions(flow)
    out = {"written": [brief(e, regions) for e in added if e.type in ("kNoteEvent", "kRestEvent")], "from": fstr(start), "to": fstr(t)}
    if replace:
        out["replaced"] = len([e for e in removed if e.type in CLEARABLE])
        if kept := [e for e in r["after"] if e.stream == voice and e.type not in CLEARABLE | {"kTieEvent"} and e.pos < t and e.end > start]:
            out["markings_kept"] = [brief(e, regions) for e in kept]
        if lost:
            out["slurs_lost"] = [{"from": bar_beat(regions, e.pos), "to": bar_beat(regions, e.end)}
                                 for e in lost]
            out["note"] = "these slurs had no note at their start or end after writing; add them again with add_span"
    return out


def _rest_onsets(items, start: Fraction) -> list[Fraction]:
    out, t = [], start
    for ps, d in items:
        if ps is None:
            out.append(t)
        t += d
    return out


def deleted_summary(removed: list[Event]) -> dict:
    kinds = {}
    for e in removed:
        k = {"kNoteEvent": "notes", "kRestEvent": "rests"}.get(e.type, e.type)
        kinds[k] = kinds.get(k, 0) + 1
    return {"deleted": len(removed), "by_type": kinds, "ids": [e.id for e in removed]}


async def delete_range(s: Session, flow: int, voice: int, start: Fraction, end: Fraction, include_markings: bool = False) -> dict:
    """Notes, rests, grace notes and tuplets of a voice starting in [start, end); with include_markings also the
    slurs, text and other markings in the voice (Dorico's deleteEventsInRange)."""
    await voice_stream(s, flow, voice)
    if end <= start:
        raise OpError("end must be after start")

    def verify(before, after, created):
        left = [e for e in after if e.stream == voice and start <= e.pos < end and e.type in ("kNoteEvent", "kRestEvent")]
        return f"{len(left)} notes/rests still in range" if left else None

    steps = [["delete", voice, fstr(start), fstr(end)]] if include_markings else \
        clear_steps(flow, await s.events(flow, [voice], start - 16, end), voice, start, end)
    if not steps:
        return {"deleted": 0, "note": "no notes or rests start in the range"}
    r = await s.transact(flow, steps, verify, [voice], start - 16, end + 1)
    return {**deleted_summary(diff(r["before"], r["after"])[1]), "from": fstr(start), "to": fstr(end)}


async def delete_events(s: Session, flow: int, event_ids: list[int]) -> dict:
    """Delete events by id: notes, rests and markings (dynamics, hairpins, slurs, text, clefs...). Uses
    EventEdit.Delete with each event's own block: selecting a marking and running Edit.Delete deletes nothing."""
    evs = await _events_by_id(s, flow, event_ids)
    if noblock := [i for i in event_ids if evs[i].block is None]:
        raise OpError(f"no block known for events {noblock}")
    steps = []
    for i in event_ids:
        cmd = f"EventEdit.Delete?FlowID={flow}&EventID={i}&EventBlockID={evs[i].block}"
        validate(cmd)
        steps.append(["cmd", cmd])

    def verify(before, after, created):
        left = [i for i in event_ids if i in {e.id for e in after}]
        return f"events {left} are still there" if left else None

    lo = min(e.pos for e in evs.values()) - 1
    hi = max(e.end for e in evs.values()) + 1
    r = await s.transact(flow, steps, verify, None, lo, hi)
    regions, _ = await s.regions(flow)
    return {"deleted": [brief(e, regions) for e in diff(r["before"], r["after"])[1]]}


async def add_grace_note(s: Session, flow: int, voice: int, pitch: str, before_pos: Fraction, value: str = "e") -> dict:
    check_pitch(pitch)
    d = parse_duration(value)

    def verify(before, after, created):
        return None if new_events(before, after, "kGraceNoteEvent", before_pos) else "grace note not created"

    r = await s.transact(flow, [["grace", voice, fstr(before_pos), fstr(-d), fstr(d), pitch]], verify, [voice], before_pos - 1, before_pos + 1)
    return {"created": [e.json() for e in new_events(r["before"], r["after"], "kGraceNoteEvent")]}


# ------------------------------------------------------------------ edits on existing notes (select + command)

NOTE_ACTIONS = {
    "pitch_up": "NoteEdit.PitchUp", "pitch_down": "NoteEdit.PitchDown",
    "chromatic_up": "NoteEdit.PitchUpChromatic", "chromatic_down": "NoteEdit.PitchDownChromatic",
    "octave_up": "NoteEdit.PitchUpOctave", "octave_down": "NoteEdit.PitchDownOctave",
    "respell_above": "NoteEdit.RespellUsingNoteNameAbove", "respell_below": "NoteEdit.RespellUsingNoteNameBelow",
    "double_duration": "EventEdit.DurationDouble", "halve_duration": "EventEdit.DurationHalve",
    "delete": "Edit.Delete", "tie": "NoteInput.Tie", "remove_rests": "Edit.RemoveRests",
}


async def edit_notes(s: Session, flow: int, event_ids: list[int], action: str, count: int = 1) -> dict:
    if action == "transpose":
        raise OpError("use transpose_notes for intervals")
    if action not in NOTE_ACTIONS:
        raise OpError(f"unknown action {action!r}; one of {sorted(NOTE_ACTIONS)}")
    cmd = NOTE_ACTIONS[action]
    return await select_apply(s, flow, event_ids, [cmd] * max(1, count))


INTERVAL_RX = re.compile(r"^(-?\d+|(maj|min|p|aug|dim)\d+( below)?|octave( below)?)$", re.IGNORECASE)


async def transpose_notes(s: Session, flow: int, event_ids: list[int], interval: str, add: bool = False) -> dict:
    """Transpose (or with add=True, add a note at) an interval: 3, -3, maj3, min6 below, p5, octave..."""
    if not INTERVAL_RX.match(interval.strip()):
        raise OpError(f"bad interval {interval!r}: e.g. 3, -2, maj3, min6 below, p5, aug4, octave")
    if add:
        return await select_apply(s, flow, event_ids, [f"NoteInput.TransposeOrAddNotesToSelection?Definition={interval}"])
    raise OpError("plain transposition by popover is not confirmed; use edit_notes pitch_up/chromatic_up or set_pitch")


async def set_pitch(s: Session, flow: int, event_id: int, pitch: str) -> dict:
    """Move a note to `pitch` in place, keeping its id and properties: chromatic steps, then Dorico's respell
    commands until the spelling matches (Lua's pitchWithSpelling setter is a silent no-op)."""
    check_pitch(pitch)
    ev = (await _events_by_id(s, flow, [event_id]))[event_id]
    if ev.type != "kNoteEvent":
        raise OpError(f"event {event_id} is a {ev.type}, not a note")
    steps = [["select", ev.stream, event_id], ["repitch", ev.stream, event_id, pitch], ["selectnone"]]

    def verify(before, after, created):
        now = next((e for e in after if e.id == event_id), None)
        return None if now and now.spelling == pitch else f"note {event_id} reads {now and now.spelling}, not {pitch}"

    await s.transact(flow, steps, verify, [ev.stream], ev.pos - 1, ev.end + 1)
    return {"event": event_id, "from": ev.spelling, "pitch": pitch}


async def set_duration(s: Session, flow: int, event_id: int, duration: str) -> dict:
    d = parse_duration(duration)
    ev = (await _events_by_id(s, flow, [event_id]))[event_id]

    def verify(before, after, created):
        a = {e.id: e for e in after}.get(event_id)
        return None if a and a.dur == d else f"duration reads {fstr(a.dur) if a else 'missing'}, expected {fstr(d)}"

    await s.transact(flow, [["duration", event_id, fstr(d)]], verify, [ev.stream], ev.pos - 1, ev.pos + d + 1)
    return {"event": event_id, "duration": fstr(d)}


# ------------------------------------------------------------------ copy / move

async def copy_range(s: Session, flow: int, voice: int, start: Fraction, end: Fraction, dest_voice: int, dest_pos: Fraction,
                     move: bool = False) -> dict:
    """Copy (or move) the notes and rests of [start, end) in a voice to dest_pos in dest_voice.

    Lua copyRange/moveRange are silent no-ops in Dorico 6.2, so notes and rests are re-created
    (pitch, spelling, rhythm); markings attached to them are not copied.
    """
    await voice_stream(s, flow, voice)
    await voice_stream(s, flow, dest_voice)
    evs = await s.events(flow, [voice], start, end)
    if tuplets := [e for e in evs if e.type == "kTupletEvent" and start <= e.pos < end]:
        regions, _ = await s.regions(flow)
        at = ", ".join(f"bar {b} beat {fstr(o)}" for b, o in (bar_at(regions, e.pos) for e in tuplets))
        raise OpError(f"the range holds {len(tuplets)} tuplet(s) ({at}), which copy_range cannot re-create: copy the "
                      "parts around them and enter each tuplet at the destination with add_tuplet")
    src = [e for e in evs if e.type in ("kNoteEvent", "kRestEvent") and start <= e.pos < end]
    if not src:
        raise OpError("no notes or rests in the source range")
    shift = dest_pos - start
    if move and voice == dest_voice and abs(shift) < end - start:
        raise OpError("source and destination overlap")
    steps = clear_steps(flow, evs, voice, start, end) if move else []
    steps += recreate_steps(src, dest_voice, shift)

    def verify(before, after, created):
        dst = {(e.pos, e.dur, e.spelling) for e in after if e.stream == dest_voice}
        missing = [e for e in src if (e.pos + shift, e.dur, e.spelling) not in dst]
        return f"{len(missing)} of {len(src)} events missing at the destination" if missing else None

    lo, hi = min(start, dest_pos) - 1, max(end, dest_pos + (end - start)) + 1
    r = await s.transact(flow, steps, verify, sorted({voice, dest_voice}), lo, hi)
    added, removed = diff(r["before"], r["after"])
    regions, _ = await s.regions(flow)
    return {"copied": len(src), "added": [brief(e, regions) for e in added], "removed": len(removed)}


def recreate_steps(src: list[Event], dest_voice: int, shift: Fraction = Fraction(0)) -> list:
    out = []
    for e in src:
        if e.type == "kRestEvent":
            out.append(["rest", dest_voice, fstr(e.pos + shift), fstr(e.dur)])
        elif e.spelling:
            out.append(["note", dest_voice, fstr(e.pos + shift), fstr(e.dur), e.spelling])
    return out


async def swap_voices(s: Session, flow: int, voice: int, other: int, start: Fraction, end: Fraction) -> dict:
    """Exchange the notes and rests of two voices in [start, end) (divisi lines trading places), in one undo step.
    Notes are re-created (pitch, spelling, rhythm) like copy_range; slurs, text and other markings stay in their voice."""
    for v in (voice, other):
        await voice_stream(s, flow, v)
    if voice == other or end <= start:
        raise OpError("give two different voices and a non-empty range")
    evs = await s.events(flow, [voice, other], start - 16, end)
    if tuplets := [e for e in evs if e.type == "kTupletEvent" and start <= e.pos < end]:
        raise OpError(f"the range holds {len(tuplets)} tuplet(s), which cannot be re-created; swap the parts around them")
    side = {v: [e for e in evs if e.stream == v and e.type in ("kNoteEvent", "kRestEvent") and start <= e.pos < end] for v in (voice, other)}
    steps = clear_steps(flow, evs, voice, start, end) + clear_steps(flow, evs, other, start, end)
    steps += recreate_steps(side[voice], other) + recreate_steps(side[other], voice)

    def verify(before, after, created):
        have = {(e.stream, e.type, e.pos, e.dur, e.spelling) for e in after}
        lost = [e for v, w in ((voice, other), (other, voice)) for e in side[v] if (w, e.type, e.pos, e.dur, e.spelling) not in have]
        return f"{len(lost)} notes/rests missing after the swap" if lost else None

    await s.transact(flow, steps, verify, [voice, other], start - 16, end + 8)
    return {"swapped": {str(voice): len(side[other]), str(other): len(side[voice])}, "from": fstr(start), "to": fstr(end)}


# ------------------------------------------------------------------ note input (tuplets, new voices)

LOG_DURATIONS = {Fraction(4): "kSemibreve", Fraction(2): "kMinim", Fraction(1): "kCrotchet", Fraction(1, 2): "kQuaver",
                 Fraction(1, 4): "kSemiQuaver", Fraction(1, 8): "kDemiSemiQuaver", Fraction(1, 16): "kHemiDemiSemiQuaver",
                 Fraction(8): "kBreve"}
ACCIDENTAL = {None: "kNatural", "b": "kFlat", "bb": "kDoubleFlat", "#": "kSharp", "##": "kDoubleSharp", "x": "kDoubleSharp"}


def note_value(d: Fraction) -> tuple[str, int]:
    """Notated duration -> (LogDuration, dots)."""
    for dots in (0, 1, 2):
        base = d / (2 - Fraction(1, 2 ** dots))
        if base in LOG_DURATIONS:
            return LOG_DURATIONS[base], dots
    raise OpError(f"duration {fstr(d)} is not a plain or dotted note value")


def note_input_steps(items) -> list[list]:
    """Steps that type notes in Dorico's note input. Every NoteInput toggle ignores its Set= value (measured),
    so the steps are written to be deterministic: NoteValue on every item (it also resets dots), one dot toggle
    when dotted, chord toggles in pairs, an explicit accidental right before each pitch (it applies to one
    note; letters alone would be spelled by the key), rest mode toggled around a rest. Chord mode itself is
    hidden state that persists between sessions; _note_input detects and repairs it."""
    steps = []
    for pitches, d in items:
        value, dots = note_value(d)
        if dots > 1:
            raise OpError("double-dotted values are not supported in note input")
        steps.append(["cmd", f"NoteInput.NoteValue?LogDuration={value}"])
        if dots:
            steps.append(["cmd", "NoteInput.SetDotted"])
        if pitches is None:
            steps += [["cmd", "NoteInput.RestMode"], ["cmd", "NoteInput.Pitch?Pitch=B&OctaveValue=4"], ["cmd", "NoteInput.RestMode"]]
            continue
        if len(pitches) > 1:
            steps.append(["cmd", "NoteInput.StartEndChord"])
        for p in pitches:
            m = re.match(r"^([A-G])(bb|b|##|#|x)?(-?\d)$", p)
            steps += [["cmd", f"NoteInput.SetAccidental?Type={ACCIDENTAL[m.group(2)]}"],
                      ["cmd", f"NoteInput.Pitch?Pitch={m.group(1)}&OctaveValue={m.group(3)}"]]
        if len(pitches) > 1:
            steps.append(["cmd", "NoteInput.StartEndChord"])
    return steps


def expected_onsets(items, pos: Fraction, scale: Fraction = Fraction(1)) -> tuple[list[tuple], Fraction]:
    """parse_notes items -> ([(onset, sounding dur, sorted pitches)] for notes and chords, end position)."""
    out, t = [], pos
    for ps, d in items:
        if ps:
            out.append((t, d * scale, sorted(ps)))
        t += d * scale
    return out, t


def check_onsets(expect: list[tuple], notes: list[Event], durations: bool = True) -> str | None:
    """Every expected chord at its own onset, nothing else. When the same pitches came out grouped into other
    onsets (stacked into one chord, or a chord split into single notes), the message starts with CHORDMODE:
    Dorico's hidden chord-mode toggle was in the opposite state."""
    at = {}
    for e in notes:
        at.setdefault(e.pos, []).append(e)
    bad = []
    for t, d, ps in expect:
        g = at.pop(t, [])
        if sorted(e.spelling for e in g) != ps or (durations and any(e.dur != d for e in g)):
            got = " ".join(f"{e.spelling}:{fstr(e.dur)}" for e in g) or "nothing"
            bad.append(f"at {fstr(t)} read {got}, expected {'+'.join(ps)}:{fstr(d)}")
    bad += [f"unexpected {' '.join(e.spelling or '?' for e in g)} at {fstr(t)}" for t, g in sorted(at.items())]
    if not bad:
        return None
    same = sorted(e.spelling for e in notes) == sorted(p for _, _, ps in expect for p in ps)
    return ("CHORDMODE: " if same and len(notes) > 1 else "") + "; ".join(bad[:4]) + (" ..." if len(bad) > 4 else "")


async def _note_input(s: Session, flow: int, voice: int, pos: Fraction, body: list[list], span: Fraction, verify) -> dict:
    """Run a note-input body at pos (one undo step). If chords came out stacked or split, Dorico's hidden chord
    mode was in the other state: the step is undone, chord mode toggled in a selection-only step, and retried once."""
    st = await s.rc.status()
    if st.get("noteInputActive") or st.get("insertActive"):
        raise OpError("Dorico is in note input or insert mode; leave it (Esc) before using this tool")
    if st.get("noteInputMode") not in (None, "kOverwrite"):
        raise OpError(f"note input mode is {st.get('noteInputMode')}; switch Dorico to overwrite mode")

    for attempt in (1, 2):
        sel, _, _ = await anchor_steps(s, flow, pos, [voice])
        steps = sel + [["cmd", "NoteInput.Enter?Set=true"]] + body + [["cmd", "NoteInput.Exit"], ["selectnone"]]
        try:
            return await s.transact(flow, steps, verify, None, pos - 1, pos + span + 4)
        except WriteError as e:
            if not str(e).startswith("CHORDMODE") or attempt == 2:
                raise
            sel, cleanup, _ = await anchor_steps(s, flow, pos, [voice])
            await s.bridge.run("tx", flow=flow, steps=sel + [["cmd", "NoteInput.Enter?Set=true"], ["cmd", "NoteInput.StartEndChord"],
                                                             ["cmd", "NoteInput.Exit"]] + cleanup)
            s.mark_written()


TUPLET_RX = re.compile(r"^(\d+):(\d+)$")


async def add_tuplet(s: Session, flow: int, voice: int, pos: Fraction, ratio: str, unit: str, notes: str) -> dict:
    """Tuplets (e.g. ratio 3:2 of quavers) typed by note input at pos, overwriting what is there.
    notes use add_notes syntax with *notated* values inside the tuplet, e.g. "C5:e D5 E5". Notes that fill several
    groups make consecutive tuplets (Dorico's tuplet run), e.g. 12 semiquavers with 6:4 s = two sextuplets."""
    m = TUPLET_RX.match(ratio.strip())
    if not m:
        raise OpError("ratio like 3:2, 5:4, 6:4")
    unit_len = parse_duration(unit)
    uv, udots = note_value(unit_len)
    letter = {"kSemibreve": "w", "kMinim": "h", "kCrotchet": "q", "kQuaver": "e", "kSemiQuaver": "x", "kDemiSemiQuaver": "y"}.get(uv)
    if not letter or udots:
        raise OpError("tuplet unit: w h q e s t (undotted)")
    items = parse_notes(notes)
    n, d = int(m.group(1)), int(m.group(2))
    notated = sum((dur for _, dur in items), Fraction(0))
    groups = notated / (n * unit_len)
    if groups.denominator != 1:
        raise OpError(f"the notes add up to {fstr(notated)} crotchets (notated) but one {n}:{d} group of {unit} holds "
                      f"{fstr(n * unit_len)}: give whole groups")
    expect, end = expected_onsets(items, pos, Fraction(d, n))
    body = [["cmd", f"NoteInput.StartTupletRun?Definition={n}:{d}{letter}"]] + note_input_steps(items) + [["cmd", "NoteInput.EndTupletRun"]]

    def inside(before, after, types):
        return [e for e in new_events(before, after, types) if pos <= e.pos < end]

    def verify(before, after, created):
        if not inside(before, after, "kTupletEvent"):
            return f"no tuplet created at {fstr(pos)}"
        # onsets and pitches only; how Dorico reports durations inside a tuplet is not confirmed live
        return check_onsets(expect, inside(before, after, "kNoteEvent"), durations=False)

    r = await _note_input(s, flow, voice, pos, body, end - pos, verify)
    return {"tuplets": [e.json() for e in inside(r["before"], r["after"], "kTupletEvent")], "groups": int(groups),
            "notes": [e.json() for e in inside(r["before"], r["after"], "kNoteEvent")]}


def notes_text(items) -> str:
    return " ".join(("+".join(ps) if ps else "r") + ":" + fstr(d) for ps, d in items)


async def add_voice(s: Session, flow: int, voice: int, pos: Fraction, notes: str) -> dict:
    """Start a new voice on the staff of `voice` and write `notes` (add_notes syntax) into it from pos.

    Note input is only needed to create the voice, so it types just the first item; the rest is written like
    add_notes (fast, and free of note input's hidden chord-mode state). That is two undo steps; if the second
    fails, both are undone."""
    vinfo = await voice_stream(s, flow, voice)
    items = parse_notes(notes)
    # a new voice starts with a typed note (typing a rest first creates no voice, measured): leading rests are
    # written afterwards with the rest of the items
    lead = next((i for i, (ps, _) in enumerate(items) if ps), None)
    if lead is None:
        raise OpError("a new voice needs at least one note")
    start, pos = pos, pos + sum((d for _, d in items[:lead]), Fraction(0))
    items, rests = items[lead:], items[:lead]
    note_value(items[0][1])  # the first note must be typeable
    old = {st["id"] for st in (await s.flow_info(flow))["streams"]}
    expect, end = expected_onsets(items[:1], pos)

    def fresh(evs):
        return [e for e in evs if e.stream not in old and e.type in ("kNoteEvent", "kRestEvent")]

    def verify(before, after, created):
        new = fresh(after)
        if not new:
            return "no new voice was created"
        return check_onsets(expect, [e for e in new if e.type == "kNoteEvent"])

    r = await _note_input(s, flow, voice, pos, [["cmd", "NoteInput.CreateVoice"]] + note_input_steps(items[:1]), end - pos, verify)
    new_streams = sorted({e.stream for e in fresh(r["after"])})
    if len(new_streams) != 1:
        raise WriteError(f"expected one new voice, found streams {new_streams}; check the score")
    new_voice = new_streams[0]
    if vinfo.get("staff_stream") is not None:
        await s.record_voice(flow, new_voice, vinfo["staff_stream"])
    regions, _ = await s.regions(flow)
    written = [brief(e, regions) for e in fresh(r["after"])]
    more = [(start, rests), (end, items[1:])]
    for at, chunk in (m for m in more if m[1]):
        try:
            written += (await add_notes(s, flow, new_voice, notes_text(chunk), pos=fstr(at)))["written"]
        except Exception as e:  # noqa: BLE001 - whatever failed, the earlier undo steps must not stay alone
            await s.rc.undo(1 + (at == end and bool(rests)))
            s.mark_written()
            raise WriteError(f"{e}; the new voice was removed as well") from None
    return {"new_voice": new_voice, "staff_stream": vinfo.get("staff_stream"), "notes": written,
            "undo_steps": 1 + sum(bool(c) for _, c in more)}
