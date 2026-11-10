"""Typed score snapshot built from the Lua `overview`/`read`/`elements` ops.

Positions and durations are exact Fractions in crotchets (quarter notes), as Dorico stores them.
Events come from two sources per stream: `.events` (rich: props, text...) and `dump()` (complete: also
slurs and other events `.events` leaves out). Dump-only events carry `"source": "dump"`.

Depends on: nothing else in the package.
"""
import math
import re
from dataclasses import dataclass, field
from fractions import Fraction

DUMP_EVENT = re.compile(r"^.*?: (k\w+) \(id:(\d+)\) at ([\d/-]+)(?: \([\d.-]+\))?(?:, duration ([\d/]+))?(.*)$")
DUMP_BLOCK = re.compile(r"^Start block id: (\d+) position: (\S+)")
# accidental: a western one, or (in other tonality systems) the alteration as a fraction of an octave: A1/244 is A4 a
# quarter-tone sharp in 24-EDO (1/24 octave), D-1/85 is D5 three quarter-tones flat (3/24 = 1/8)
ACCIDENTAL = r"bbb|bb|b|###|##|#|x|-?\d+/\d+"
SPELLING = re.compile(rf"\s([A-G](?:{ACCIDENTAL})?-?\d+)(?: \(ends|\s*$)")
ELEMENT = re.compile(r"element ID = (\d+)")
CLEF = re.compile(r"Clef entity ID in all layouts: (\S+)")
TEXT = re.compile(r"\) at [\d/-]+(?: \([\d.-]+\))? : (.*?)\s*\((paragraph\.[\w.]+)\)\s*$", re.DOTALL)


STEPS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
PITCH = re.compile(rf"^([A-G])({ACCIDENTAL})?(-?\d+)$")


def spelling_to_midi(sp: str) -> int | float | None:
    """"Eb4" -> 63 (middle C = C4 = 60), as Dorico spells pitches; "A1/244" -> 69.5."""
    m = PITCH.match(sp or "")
    if not m:
        return None
    western = {None: 0, "b": -1, "bb": -2, "bbb": -3, "#": 1, "##": 2, "x": 2, "###": 3}
    acc = western[m.group(2)] if m.group(2) in western else Fraction(m.group(2)) * 12
    midi = 12 * (int(m.group(3)) + 1) + STEPS[m.group(1)] + acc
    return int(midi) if midi == int(midi) else float(midi)


def frac(x) -> Fraction:
    if isinstance(x, Fraction):
        return x
    if isinstance(x, int):
        return Fraction(x)
    s = str(x).strip()
    if " " in s:  # "1 1/2"
        whole, rest = s.split(None, 1)
        return Fraction(whole) + Fraction(rest) * (-1 if whole.startswith("-") else 1)
    return Fraction(s)


def rational(v) -> Fraction | None:
    """A rhythmic property value ("3/2", "1.5", 2) as a Fraction, or None if unset or unreadable."""
    if v in (None, "", {"sealed": True}):
        return None
    try:
        return frac(v).limit_denominator(256)
    except (ValueError, ZeroDivisionError, TypeError):
        return None


def fstr(f: Fraction) -> str:
    return str(f.numerator) if f.denominator == 1 else f"{f.numerator}/{f.denominator}"


def parse_dump(text: str) -> list[dict]:
    """dump() text -> [{id, type, pos, dur, desc, instance}] (multi-line descriptions are joined)."""
    out, instance = [], None
    for line in (text or "").splitlines():
        if m := DUMP_BLOCK.match(line):
            instance = int(m.group(1))
            continue
        if line.startswith("----"):
            continue
        if m := DUMP_EVENT.match(line):
            out.append({"id": int(m.group(2)), "type": m.group(1), "pos": frac(m.group(3)),
                        "dur": frac(m.group(4) or 0), "desc": line[line.index(m.group(1) + " (id:"):].strip(), "instance": instance})
        elif out and line.strip():
            out[-1]["desc"] += " " + line.strip()
    return out


@dataclass
class Event:
    id: int
    type: str
    stream: int
    block: int | None
    pos: Fraction
    dur: Fraction
    desc: str
    props: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)
    source: str = "events"

    @property
    def end(self) -> Fraction:
        return self.pos + self.dur

    @property
    def element(self) -> int | None:
        m = ELEMENT.search(self.desc)
        return int(m.group(1)) if m else None

    @property
    def spelling(self) -> str | None:
        m = SPELLING.search(self.desc)
        return m.group(1) if m else None

    @property
    def midi(self) -> int | float | None:
        v = rational(self.props.get("kNotePitch"))
        if v is not None:  # a quarter-tone in 24-EDO reads "139/2"
            return int(v) if v.denominator == 1 else float(v)
        return spelling_to_midi(self.spelling) if self.spelling else None

    def json(self) -> dict:
        d = {"id": self.id, "type": self.type, "stream": self.stream, "pos": fstr(self.pos)}
        if self.dur:
            d["dur"] = fstr(self.dur)
        if self.type in ("kNoteEvent", "kGraceNoteEvent"):
            d["pitch"], d["midi"] = self.spelling, self.midi
        if self.type == "kClefEvent" and (m := CLEF.search(self.desc)):
            d["clef"] = m.group(1)
        if self.type == "kTextEvent" and (m := TEXT.search(self.desc)):
            d["text"], d["style"] = m.group(1), m.group(2)
        if self.element is not None:
            d["element"] = self.element
        d.update(self.extra)
        props = {k: v for k, v in self.props.items() if k not in IMPLICIT_PROPS and v != {"sealed": True}}
        if props:
            d["props"] = props
        if self.source != "events":
            d["source"] = self.source
        return d


IMPLICIT_PROPS = {"kEventPosition", "kEventDuration", "kEventSecondaryPosition", "kEventSecondaryEndPositionOffset", "kNotePitch"}


def build_events(streams: list[dict]) -> list[Event]:
    """Merge `.events` rows with dump-only rows for each stream from the Lua `read` op."""
    out = []
    for st in streams:
        inst_block = {b["instance"]: b["block"] for b in st.get("blocks") or []}
        seen = set()
        for r in st.get("events") or []:
            extra = {k: r[k] for k in ("text", "secondary", "tuplet", "ottava", "layout", "frame") if k in r}
            out.append(Event(r["id"], r["type"], st["id"], r.get("block"), frac(r["pos"]), frac(r["dur"]),
                             r["desc"], r.get("props") or {}, extra))
            seen.add(r["id"])
        for r in parse_dump(st.get("dump")):
            if r["id"] not in seen:
                out.append(Event(r["id"], r["type"], st["id"], inst_block.get(r["instance"]), r["pos"], r["dur"],
                                 r["desc"], source="dump"))
    out.sort(key=lambda e: (e.pos, e.stream, e.id))
    return out


def in_range(e: Event, lo: Fraction | None, hi: Fraction | None) -> bool:
    if lo is not None and (e.end <= lo if e.dur else e.pos < lo):
        return False
    return hi is None or e.pos < hi


# ------------------------------------------------------------------ bar map

def ts_length(ts: str) -> Fraction | None:
    """Bar length in crotchets for "n/d", "C" (4/4) or "cut" (2/2)."""
    if ts == "C":
        return Fraction(4)
    if ts == "cut":
        return Fraction(4)
    if m := re.fullmatch(r"(\d+)/(\d+)", ts or ""):
        return Fraction(int(m.group(1)) * 4, int(m.group(2)))
    return None


@dataclass
class Region:
    start: Fraction
    timesig: str | None  # None: no time signature in force (open meter)
    length: Fraction | None
    first_bar: int
    pickup: Fraction | None = None  # irregular first bar length, if any


def bar_regions(divisions: list[tuple[Fraction, str | None, Fraction | None]]) -> list[Region]:
    """divisions: sorted [(pos, timesig, pickup_len)] -> regions with their first bar numbers.

    A flow starts in open meter until its first time signature; a region without a readable signature (open meter,
    or a barline there) is one bar that runs to the next division."""
    if not divisions or divisions[0][0] > 0:
        divisions = [(Fraction(0), None, None)] + list(divisions)
    regions, bar = [], 1
    for i, (pos, ts, pickup) in enumerate(divisions):
        length = ts_length(ts)
        regions.append(Region(pos, ts, length, bar, pickup))
        if i + 1 < len(divisions):
            span = divisions[i + 1][0] - pos
            if length is None:
                bar += 1
                continue
            if pickup:
                bar += 1
                span -= pickup
            bar += math.ceil(span / length)
    return regions


def bar_at(regions: list[Region], pos: Fraction) -> tuple[int, Fraction]:
    """position -> (bar number, offset within the bar)."""
    r = max((r for r in regions if r.start <= pos), key=lambda r: r.start, default=None)
    if r is None:
        raise ValueError(f"no bar at {pos}")
    off = pos - r.start
    if r.length is None:
        return r.first_bar, off
    if r.pickup:
        if off < r.pickup:
            return r.first_bar, off
        off -= r.pickup
        n = r.first_bar + 1 + off // r.length
        return int(n), off % r.length
    return int(r.first_bar + off // r.length), off % r.length


def bar_start(regions: list[Region], bar: int) -> Fraction:
    """bar number -> its start position."""
    r = max((r for r in regions if r.first_bar <= bar), key=lambda r: r.first_bar, default=None)
    if r is None:
        raise ValueError(f"no bar {bar}")
    k = bar - r.first_bar
    if r.length is None:
        if k:
            raise ValueError(f"bar {bar} does not exist: no time signature is in force from bar {r.first_bar} "
                             f"(open meter), so it runs on as one bar; address positions with pos")
        return r.start
    if r.pickup:
        return r.start if k == 0 else r.start + r.pickup + (k - 1) * r.length
    return r.start + k * r.length


# ------------------------------------------------------------------ keys

SHARP_ORDER, FLAT_ORDER = "FCGDAEB", "BEADGCF"


def key_from_spelling(spelled: list[str]) -> str | None:
    """Spelled letters A..G (as Dorico entered them by key) -> "3b", "2#" or "0"."""
    sharps = {s[0] for s in spelled if "#" in s}
    flats = {s[0] for s in spelled if "b" in s[1:]}
    if sharps and flats:
        return None
    if sharps:
        n = len(sharps)
        return f"{n}#" if set(SHARP_ORDER[:n]) == sharps else None
    if flats:
        n = len(flats)
        return f"{n}b" if set(FLAT_ORDER[:n]) == flats else None
    return "0"


KEY_NAMES = {"0": "C major / A minor (or open/atonal)", "1#": "G / Em", "2#": "D / Bm", "3#": "A / F#m", "4#": "E / C#m",
             "5#": "B / G#m", "6#": "F# / D#m", "7#": "C# / A#m", "1b": "F / Dm", "2b": "Bb / Gm", "3b": "Eb / Cm",
             "4b": "Ab / Fm", "5b": "Db / Bbm", "6b": "Gb / Ebm", "7b": "Cb / Abm"}


# ------------------------------------------------------------------ staves

def staff_map(overview_flow: dict, recorded: dict[int, int] | None = None) -> dict[int, dict]:
    """voice stream id -> {instrument, staff_stream, staff_index, voice_index, confidence}.

    Dorico's Lua API does not expose which staff a voice is on. Known facts used instead:
    - "creation order": Dorico creates each staff's first voice right after the staff, so a voice whose id is
      its instrument's stave id + 1 is that staff's first voice (holds for every instrument as created);
    - "recorded": voices this server created itself (add_voice) are recorded with their staff;
    - otherwise the staff is reported as unknown rather than guessed.
    """
    recorded = recorded or {}
    staves = sorted(s["id"] for s in overview_flow["streams"] if s["kind"] == "kInstrumentStaveStream")
    out = {}
    for inst in overview_flow["instruments"]:
        voices = sorted(inst["voices"])
        inst_staves = sorted({v - 1 for v in voices if v - 1 in staves} | {recorded[v] for v in voices if v in recorded})
        for v in voices:
            if v - 1 in staves:
                stave, conf = v - 1, "creation order"
            elif v in recorded:
                stave, conf = recorded[v], "recorded when created"
            else:
                stave, conf = None, "unknown (voice not created by this server)"
            out[v] = {"instrument": inst["id"], "staff_stream": stave, "confidence": conf,
                      "staff_index": inst_staves.index(stave) + 1 if stave in inst_staves else None}
        for st in inst_staves:
            for i, v in enumerate(sorted(x for x in voices if out[x]["staff_stream"] == st), 1):
                out[v]["voice_index"] = i
    return out


if __name__ == "__main__":
    # self-check against the fixture's known structure
    regs = bar_regions([(Fraction(0), "3/4", None), (Fraction(264), "4/4", None), (Fraction(412), "10/8", None)])
    assert [r.first_bar for r in regs] == [1, 89, 126], regs
    assert bar_at(regs, Fraction(207)) == (70, 0)
    assert bar_start(regs, 89) == 264 and bar_start(regs, 126) == 412 and bar_start(regs, 127) == 417
    assert key_from_spelling(["Ab4", "Bb4", "C5", "D5", "Eb5", "F5", "G5"]) == "3b"
    assert key_from_spelling(["A4", "B4", "C#5", "D5", "E5", "F#5", "G5"]) == "2#"
    assert key_from_spelling(list("ABCDEFG")) == "0"
    ev = parse_dump("Start block id: 1002 position: 0\n"
                    "1.75 (7/4 (1.75)) dur: 13/4 (3.25): kSlurEvent (id:94) at 7/4 (1.75), duration 13/4 (3.25)  element ID = 6\n"
                    "8 (8): kClefEvent (id:102) at 8 \nClef entity ID in all layouts: clef.treble\n")
    assert ev[0]["type"] == "kSlurEvent" and ev[0]["pos"] == Fraction(7, 4) and ev[0]["dur"] == Fraction(13, 4)
    assert ev[1]["id"] == 102 and "clef.treble" in ev[1]["desc"]
    e = Event(15, "kNoteEvent", 2, 2, Fraction(0), Fraction(3, 2), "kNoteEvent (id:15) at 0, duration 3/2 (1.5)  Eb4 (ends 3/2 (1.5))", {"kNotePitch": "63"})
    assert e.spelling == "Eb4" and e.midi == 63
    assert spelling_to_midi("A1/244") == 69.5 and spelling_to_midi("D-1/85") == 72.5 and spelling_to_midi("C-1/245") == 71.5
    assert Event(1, "kNoteEvent", 8, 8, Fraction(0), Fraction(1), "kNoteEvent (id:1) at 0, duration 1  A1/244 (ends 1)",
                 {"kNotePitch": "139/2"}).json()["midi"] == 69.5
    assert spelling_to_midi("Eb4") == 63 and spelling_to_midi("C4") == 60 and spelling_to_midi("Dbb5") == 72 and spelling_to_midi("B#3") == 60
    pk = bar_regions([(Fraction(0), "4/4", Fraction(1)), (Fraction(9), "3/4", None)])
    assert [r.first_bar for r in pk] == [1, 4] and bar_at(pk, Fraction(5)) == (3, 0)
    t = Event(1, "kTextEvent", 2, 2, Fraction(90), Fraction(0), "kTextEvent (id:145) at 90 : dolce (paragraph.defaulttext)")
    assert t.json()["text"] == "dolce" and t.json()["style"] == "paragraph.defaulttext"
    op = bar_regions([])  # a flow with no time signature at all
    assert bar_at(op, Fraction(37, 6)) == (1, Fraction(37, 6)) and bar_start(op, 1) == 0
    late = bar_regions([(Fraction(8), "3/4", None)])  # open meter, then 3/4 from pos 8
    assert [r.first_bar for r in late] == [1, 2] and bar_at(late, Fraction(11)) == (3, 0) and bar_start(late, 2) == 8
    try:
        bar_start(op, 2)
        raise AssertionError("bar 2 of an open-meter flow must not resolve")
    except ValueError as e:
        assert "open meter" in str(e)
    print("model self-check ok")
