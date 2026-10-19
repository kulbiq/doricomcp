"""Shared write helpers: note-text parsing, positions, anchors (a selection for commands that act on "the
selection"), the note-input caret, clearing a range, and select-and-command on events.

Depends on: catalog, model, session.
"""
import re
from fractions import Fraction

from ..catalog import validate
from ..model import Event, bar_at, frac, fstr
from ..session import Session, diff

PITCH_RX = re.compile(r"^[A-G](bb|b|##|#|x)?-?\d$")
VALUE_LETTERS = {"w": Fraction(4), "h": Fraction(2), "q": Fraction(1), "e": Fraction(1, 2), "s": Fraction(1, 4),
                 "t": Fraction(1, 8), "x": Fraction(1, 16), "b": Fraction(8)}
TIMEBASE_MARKS = {"kBarDivisionEvent", "kTonalityDivisionEvent", "kImmediateTempoChangeEvent", "kPauseEvent",
                  "kBreakEvent", "kRehearsalMarkEvent", "kRepeatMarkerEvent"}


class OpError(ValueError):
    pass


# ------------------------------------------------------------------ parsing helpers

def parse_duration(tok: str) -> Fraction:
    """"3/2", "1", "0.5" (crotchets) or note-value letters with dots: "q", "h.", "e..", "w"."""
    if m := re.fullmatch(r"([bwhqestx])(\.*)", tok):
        base = VALUE_LETTERS[m.group(1)]
        return base * (2 - Fraction(1, 2 ** len(m.group(2))))
    try:
        d = Fraction(tok)
    except (ValueError, ZeroDivisionError):
        raise OpError(f"bad duration {tok!r}: use crotchets like 1, 3/2, 0.5 or note values w h q e s t with dots") from None
    if d <= 0:
        raise OpError(f"duration must be positive: {tok!r}")
    return d


def check_pitch(p: str) -> str:
    if not PITCH_RX.match(p):
        raise OpError(f"bad pitch {p!r}: use letter + optional #/b/##/bb + octave, e.g. C4, F#5, Bb3 (middle C = C4)")
    return p


def parse_notes(text: str) -> list[tuple[list[str] | None, Fraction]]:
    """"Eb4+G4+C5:3/2 G4:e r:q" -> [([Eb4,G4,C5], 3/2), ([G4], 1/2), (None, 1)]. A missing duration repeats the last."""
    out, last = [], None
    for tok in text.split():
        head, _, dur = tok.partition(":")
        d = parse_duration(dur) if dur else last
        if d is None:
            raise OpError(f"first item {tok!r} needs a duration, e.g. {tok}:q")
        last = d
        out.append((None, d) if head.lower() in ("r", "rest") else ([check_pitch(p) for p in head.split("+")], d))
    if not out:
        raise OpError("no notes given")
    return out


# ------------------------------------------------------------------ position helpers

async def resolve_pos(s: Session, flow: int, bar: int | None = None, beat: str | None = None, pos: str | None = None) -> Fraction:
    """Either an absolute position in crotchets, or a bar number (1-based) + offset in crotchets within it."""
    if pos is not None:
        return frac(pos)
    if bar is None:
        raise OpError("give a position: bar (+ beat offset in crotchets) or pos")
    return await s.to_pos(flow, bar, frac(beat or 0))


async def voice_stream(s: Session, flow: int, voice: int) -> dict:
    vs = await s.voices(flow)
    if voice not in vs:
        raise OpError(f"voice {voice} is not a voice stream in flow {flow}; voices: {sorted(vs)} (see get_score_overview)")
    return vs[voice]


async def staff_stream(s: Session, flow: int, voice: int) -> int:
    v = await voice_stream(s, flow, voice)
    if v.get("staff_stream") is None:
        raise OpError(f"no staff stream known for voice {voice}")
    return v["staff_stream"]


def window(pos: Fraction, end: Fraction | None = None) -> tuple[Fraction, Fraction]:
    return pos - 1, (end if end is not None else pos) + 4


async def anchor_steps(s: Session, flow: int, pos: Fraction, voices: list[int], caret: bool = False) -> tuple[list, list, int]:
    """Steps that select something starting exactly at `pos` in one of `voices`, and cleanup steps.

    Prefers an existing note/rest at pos. Otherwise creates a temporary rest in a voice that is silent
    over [pos, pos+len) and deletes exactly that span afterwards (only used for commands whose result lives
    outside the voice stream: timebase and stave markings). caret=True: where every voice has a note sounding
    through pos, put the note-input caret there instead (for commands that apply at the caret: dynamics).
    """
    try:
        return await _anchor_steps(s, flow, pos, voices)
    except OpError:
        if not caret:
            raise
    steps, cleanup, _ = await caret_steps(s, flow, pos, voices)
    return steps, cleanup, voices[0]


async def _anchor_steps(s: Session, flow: int, pos: Fraction, voices: list[int]) -> tuple[list, list, int]:
    evs = await s.events(flow, voices, pos - 8, pos + 8)
    # a tuplet that opens with a rest has no rest event there, but its bracket starts at pos and takes the command
    for types in (("kNoteEvent", "kRestEvent"), ("kTupletEvent",)):
        for v in voices:
            for e in evs:
                if e.stream == v and e.pos == pos and e.type in types and (e.source == "events" or e.block is not None):
                    return [select_step(flow, e)], [["selectnone"]], v
    for v in voices:
        mine = [e for e in evs if e.stream == v and e.type in ("kNoteEvent", "kRestEvent", "kGraceNoteEvent", "kTupletEvent")]
        if any(e.pos <= pos < e.end or e.pos == pos for e in mine):
            continue
        nxt = min((e.pos for e in mine if e.pos > pos), default=pos + 1)
        length = min(Fraction(1, 4), nxt - pos)
        # select the temp rest by its id: created ids are only known inside the script, so use "select_created"
        return ([["rest", v, fstr(pos), fstr(length)], ["select_created", v, -1]],
                [["selectnone"], ["delete", v, fstr(pos), fstr(pos + length)]], v)
    raise OpError(f"nothing to anchor a selection at {fstr(pos)}: every voice has a note sounding through it "
                  "without starting there - target a position where a note or rest starts")


def select_step(flow: int, e: Event) -> list:
    """Select one event. Lua finds the block itself for events it can enumerate; for dump-only events (a voice
    holding a trill, ornament, technique...) the block comes from the dump, as delete_events uses it.
    (EventEdit.Select ignores AddToSelection and BlockSelection: it always selects one event.)"""
    if e.source == "events":
        return ["select", e.stream, e.id]
    return ["cmd", f"EventEdit.Select?FlowID={flow}&EventID={e.id}&EventBlockID={e.block}"]


GRIDS = {Fraction(1): "kCrotchet", Fraction(1, 2): "kQuaver", Fraction(1, 4): "kSemiquaver", Fraction(1, 8): "kDemisemiquaver"}


def grid_for(*spans: Fraction) -> Fraction:
    """The coarsest note-input grid that every span is a whole number of."""
    for g in GRIDS:
        if all((x / g).denominator == 1 for x in spans):
            return g
    raise OpError(f"positions {', '.join(fstr(x) for x in spans)} are not on a demisemiquaver grid (inside a tuplet?): "
                  "start at a note or rest instead")


def advance_steps(g: Fraction, span: Fraction) -> list:
    """Move the note-input caret right by span (MoveRight steps by the grid; MoveAdvance jumps to the next item)."""
    return [["cmd", "NoteInput.MoveRight"]] * int(span / g)


async def caret_steps(s: Session, flow: int, pos: Fraction, voices: list[int], extra: tuple = ()) -> tuple[list, list, Fraction]:
    """Note input with the caret at pos, for a position where no note or rest starts (a dynamic in the middle of a
    held note): select the last note/rest starting before pos, enter note input (the caret goes to it) and advance
    the caret by the rhythmic grid (one that also divides the `extra` spans). Returns (steps, exit steps, grid)."""
    evs = await s.events(flow, voices, pos - 16, pos + Fraction(1, 64))
    for v in voices:
        prior = [e for e in evs if e.stream == v and e.type in ("kNoteEvent", "kRestEvent") and e.pos <= pos
                 and (e.source == "events" or e.block is not None)]
        if prior:
            e = max(prior, key=lambda x: x.pos)
            g = grid_for(pos - e.pos, *extra)
            steps = [select_step(flow, e), ["cmd", "NoteInput.Enter?Set=true"],
                     ["cmd", f"NoteInput.SetGridResolution?RhythmicGridResolutionValue={GRIDS[g]}"]] + advance_steps(g, pos - e.pos)
            return steps, [["cmd", "NoteInput.Exit"], ["selectnone"]], g
    raise OpError(f"nothing to start from at {fstr(pos)}: no note or rest in the last 4 bars of voices {voices}")


async def staff_voices(s: Session, flow: int, voice: int) -> list[int]:
    """The voices on voice's staff (voice first). A voice whose staff is unknown counts as on it when it belongs to
    the same instrument."""
    vs = await s.voices(flow)
    me = vs.get(voice, {})
    return [voice] + sorted(v for v, info in vs.items() if v != voice and info.get("instrument") == me.get("instrument")
                            and (info.get("staff_stream") is None or me.get("staff_stream") is None
                                 or info.get("staff_stream") == me.get("staff_stream")))


async def instrument_voices(s: Session, flow: int, voice: int) -> list[int]:
    """voice first, then the other voices of its instrument: a dynamic belongs to the instrument, so a note
    starting in any of its voices can anchor it."""
    vs = await s.voices(flow)
    inst = vs[voice].get("instrument") if voice in vs else None
    return [voice] + sorted(v for v, info in vs.items() if v != voice and inst is not None and info.get("instrument") == inst)


def brief(e: Event, regions) -> dict:
    """An event in a write result: id, bar, beat, pitch or kind, duration."""
    bar, beat = bar_at(regions, e.pos)
    d = {"id": e.id, "bar": bar, "beat": fstr(beat)}
    if e.type in ("kNoteEvent", "kGraceNoteEvent"):
        d["pitch"] = e.spelling
    elif e.type == "kRestEvent":
        d["rest"] = True
    else:
        d["type"] = e.type
    if e.dur:
        d["dur"] = fstr(e.dur)
    return d


CLEARABLE = {"kNoteEvent", "kRestEvent", "kGraceNoteEvent", "kTupletEvent", "kBarRestEvent"}


def clear_steps(flow: int, evs: list[Event], voice: int, lo: Fraction, hi: Fraction) -> list:
    """Steps deleting the notes, rests, grace notes and tuplets of `voice` that start in [lo, hi), and the ties
    reaching into it. Slurs, text and other markings in the voice stay (deleteEventsInRange takes them too). A note
    sounding into the range from before is shortened to end at lo."""
    steps, ids = [], []
    for e in evs:
        if e.stream != voice:
            continue
        doomed = (e.type in CLEARABLE and lo <= e.pos < hi) or (e.type == "kTieEvent" and e.pos < hi and e.end > lo)
        if doomed and e.source == "events":
            ids.append(e.id)
        elif doomed:
            if e.block is None:
                raise OpError(f"event {e.id} ({e.type}) has no known block; use include_markings=True")
            steps.append(["cmd", f"EventEdit.Delete?FlowID={flow}&EventID={e.id}&EventBlockID={e.block}"])
        elif e.type == "kNoteEvent" and e.pos < lo < e.end and e.source == "events":
            steps.append(["duration", e.id, fstr(lo - e.pos)])
    return ([["delete_ids", voice, ids]] if ids else []) + steps


def new_events(before: list[Event], after: list[Event], types: set[str] | str, pos: Fraction | None = None) -> list[Event]:
    types = {types} if isinstance(types, str) else types
    added, _ = diff(before, after)
    return [e for e in added if e.type in types and (pos is None or e.pos == pos)]



# ------------------------------------------------------------------ select + command, positional anchors

async def _events_by_id(s: Session, flow: int, ids: list[int]) -> dict[int, Event]:
    evs = {e.id: e for e in await s.events(flow)}
    missing = [i for i in ids if i not in evs]
    if missing:
        raise OpError(f"no events with ids {missing} in flow {flow}")
    return {i: evs[i] for i in ids}


async def select_apply(s: Session, flow: int, event_ids: list[int], commands: list[str], expect_change: bool = True,
                       extends: int = 0) -> dict:
    """Select each event in turn and run `commands` on it, all in one transaction; verify each event changed."""
    for c in commands:
        validate(c)
    evs = await _events_by_id(s, flow, event_ids)
    steps = []
    for i in event_ids:
        steps += [["select", evs[i].stream, i]] + [["cmd", "EventEdit.NavigateRightExtend"]] * extends + [["cmd", c] for c in commands]
    steps.append(["selectnone"])
    lo = min(e.pos for e in evs.values()) - 4
    hi = max(e.end for e in evs.values()) + 8

    def verify(before, after, created):
        if not expect_change:
            return None
        b, a = {e.id: e for e in before}, {e.id: e for e in after}
        unchanged = [i for i in event_ids if i in a and a[i].desc == b[i].desc and a[i].props == b[i].props]
        added, removed = diff(before, after)
        if unchanged and not added and not removed:
            return f"no visible change on events {unchanged} after {commands}"
        return None

    r = await s.transact(flow, steps, verify, None, lo, hi)
    added, removed = diff(r["before"], r["after"])
    b = {e.id: e for e in r["before"]}
    changed = [e.json() for e in r["after"] if e.id in b and (e.desc != b[e.id].desc or e.props != b[e.id].props)]
    return {"added": [e.json() for e in added], "removed": [e.json() for e in removed], "changed": changed}



async def _positional(s: Session, flow: int, pos: Fraction, command: str, types: set[str], voices: list[int]) -> dict:
    validate(command)
    sel, cleanup, _ = await anchor_steps(s, flow, pos, voices)
    steps = sel + [["cmd", command]] + cleanup

    def verify(before, after, created):
        return None if new_events(before, after, types, pos) or new_events(before, after, types) else \
            f"no {'/'.join(sorted(types))} created at {fstr(pos)}"

    r = await s.transact(flow, steps, verify, None, pos - 1, pos + 8)
    regions, _ = await s.regions(flow)
    return {"created": [{**e.json(), "bar": bar_at(regions, e.pos)[0]} for e in new_events(r["before"], r["after"], types)]}


async def all_voices(s: Session, flow: int) -> list[int]:
    return sorted(await s.voices(flow))


# ------------------------------------------------------------------ shared tables

SPAN_COMMANDS = {
    "slur": ("NoteInput.SlurStart", {"kSlurEvent"}),
    "cresc": ("NoteInput.HairpinStart?Type=kGradualDynamicUp&GradualDynamicType=kCrescOrDim", {"kDynamicGroupEvent"}),
    "dim": ("NoteInput.HairpinStart?Type=kGradualDynamicDown&GradualDynamicType=kCrescOrDim", {"kDynamicGroupEvent"}),
    "messa_di_voce": ("NoteInput.HairpinStart?Type=kGradualDynamicUp&GradualDynamicType=kMessaDiVoce", {"kDynamicGroupEvent"}),
    "8va": ("NoteInput.OttavaLineStart?Octave=1", {"kOttavaLineEvent"}),
    "8vb": ("NoteInput.OttavaLineStart?Octave=-1", {"kOttavaLineEvent"}),
    "15ma": ("NoteInput.OttavaLineStart?Octave=2", {"kOttavaLineEvent"}),
    "15mb": ("NoteInput.OttavaLineStart?Octave=-2", {"kOttavaLineEvent"}),
    "glissando": ("NoteInput.CreateGlissando", {"kGlissandoLineEvent"}),
}


def bar_beat(regions, pos: Fraction) -> dict:
    bar, beat = bar_at(regions, pos)
    return {"bar": bar, "beat": fstr(beat)}
