"""Voice-leading check over read_music data: parallel and hidden fifths/octaves, crossings, spacing, leaps and,
with a chord plan, doublings and missing chord tones. Pure Python on what read_music returns; no Dorico access.

Depends on: model.
"""
import re
from fractions import Fraction
from itertools import pairwise

from .model import frac, spelling_to_midi

PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
# chord quality -> semitones above the root of (third, fifth, seventh); None = not in the chord
QUALITIES = {"": (4, 7, None), "m": (3, 7, None), "dim": (3, 6, None), "aug": (4, 8, None), "sus4": (5, 7, None),
             "sus2": (2, 7, None), "7": (4, 7, 10), "maj7": (4, 7, 11), "m7": (3, 7, 10), "m7b5": (3, 6, 10),
             "dim7": (3, 6, 9), "mmaj7": (3, 7, 11)}
CHORD_RX = re.compile(r"^([A-G])(#|b)?(maj7|mmaj7|m7b5|dim7|dim|aug|sus4|sus2|m7|m|7|ø7|o7|ø|o|)(?:/([A-G](?:#|b)?))?$")
ALIASES = {"ø7": "m7b5", "ø": "m7b5", "o7": "dim7", "o": "dim"}
NAMES = {0: "unison/octave", 7: "fifth"}


def _pc(name: str) -> int:
    return (PC[name[0]] + {"#": 1, "b": -1}.get(name[1:2], 0)) % 12


def parse_chord(sym: str) -> dict:
    m = CHORD_RX.match(sym.strip())
    if not m:
        raise ValueError(f"chord {sym!r}: like D, Bm, A7, F#dim, Gmaj7, Bm7b5, D/F#")
    root = _pc(m.group(1) + (m.group(2) or ""))
    third, fifth, seventh = QUALITIES[ALIASES.get(m.group(3), m.group(3))]
    roles = {root: "root", (root + third) % 12: "third", (root + fifth) % 12: "fifth"}
    if seventh is not None:
        roles[(root + seventh) % 12] = "seventh"
    return {"symbol": sym.strip(), "roles": roles, "bass": _pc(m.group(4)) if m.group(4) else None,
            "major": third == 4}


def parse_plan(plan: str) -> list[tuple[int, Fraction, dict]]:
    """"28 D, 28:2 A7, 29 Bm/F#" -> [(bar, beat, chord)], sorted."""
    out = []
    for item in filter(None, (x.strip() for x in re.split(r"[,;\n]", plan))):
        where, _, sym = item.partition(" ")
        bar, _, beat = where.partition(":")
        out.append((int(bar), frac(beat or 0), parse_chord(sym)))
    return sorted(out, key=lambda x: (x[0], x[1]))


def _lines(read: dict) -> dict[int, list[tuple]]:
    """voice -> [(start, end, midi, pitch, bar, beat)]; a chord in one voice counts by its top note."""
    out = {}
    for v in read["voices"]:
        notes = []
        for i in v["items"]:
            if i["type"] not in ("note", "chord"):
                continue
            k = max(range(len(i["midi"])), key=lambda j: i["midi"][j] or spelling_to_midi(i["pitches"][j]) or 0)
            dur = max(frac(d) for d in (i["dur"] if isinstance(i["dur"], list) else [i["dur"]]))
            notes.append((frac(i["pos"]), frac(i["pos"]) + dur, i["midi"][k] or spelling_to_midi(i["pitches"][k]),
                          i["pitches"][k], i["bar"], i["beat"]))
        out[v["voice"]] = notes
    return out


def check(read: dict, order: list[int] | None = None, plan: str | None = None, key: str | None = None,
          max_leap: int = 12, limit: int = 300) -> dict:
    """order: voices from highest to lowest (default: by average pitch). key: tonic for leading-tone doubling
    ("D", "Bm"; minor keys use the raised seventh). plan: chords in force, "bar[:beat] symbol, ..."."""
    lines = _lines(read)
    lines = {v: ns for v, ns in lines.items() if ns}
    order = [v for v in (order or sorted(lines, key=lambda v: -sum(n[2] for n in lines[v]) / len(lines[v]))) if v in lines]
    chords = parse_plan(plan) if plan else []
    leading = (_pc(key.rstrip("m")) - 1) % 12 if key else None
    problems = []

    def add(kind, at, voices, detail):
        problems.append({"bar": at[0], "beat": at[1], "kind": kind, "voices": voices, "detail": detail})

    for v in order:  # melodic leaps
        for a, b in pairwise(lines[v]):
            d = abs(b[2] - a[2])
            if d > max_leap or d == 6:
                add("leap" if d != 6 else "tritone leap", (b[4], b[5]), [v], f"{a[3]} -> {b[3]} ({d} semitones)")

    times = sorted({n[0] for ns in lines.values() for n in ns})
    prev = None
    for t in times:
        cur = {v: next((n for n in lines[v] if n[0] <= t < n[1]), None) for v in order}
        at = next((n[4], n[5]) for n in cur.values() if n and n[0] == t)
        here = [v for v in order if cur[v]]
        for hi, lo in pairwise(here):
            if cur[hi][2] < cur[lo][2]:
                add("crossing", at, [hi, lo], f"{cur[hi][3]} below {cur[lo][3]}")
        for hi, lo in pairwise(here[:-1]):  # upper voices; the bass may be further away
            if cur[hi][2] - cur[lo][2] > 12:
                add("spacing", at, [hi, lo], f"{cur[hi][3]} - {cur[lo][3]} wider than an octave")
        if prev:
            for i, a in enumerate(order):
                for b in order[i + 1:]:
                    pa, pb, ca, cb = prev.get(a), prev.get(b), cur[a], cur[b]
                    if not (pa and pb and ca and cb) or (pa is ca and pb is cb):
                        continue
                    da, db = ca[2] - pa[2], cb[2] - pb[2]
                    if not (da and db):
                        continue
                    i1, i2 = (pa[2] - pb[2]) % 12, (ca[2] - cb[2]) % 12
                    if i1 == i2 and i1 in NAMES:
                        name = "unisons" if pa[2] == pb[2] and ca[2] == cb[2] else NAMES[i1] + "s"
                        motion = "parallel" if da * db > 0 else "contrary"
                        add(f"{motion} {name}", at, [a, b], f"{pa[3]}/{pb[3]} -> {ca[3]}/{cb[3]}")
                    elif (a, b) == (order[0], order[-1]) and da * db > 0 and i2 in NAMES and abs(da) > 2:
                        add(f"hidden {NAMES[i2]}", at, [a, b], f"{pa[3]}/{pb[3]} -> {ca[3]}/{cb[3]}, upper voice leaps")
        if chords and len(here) >= 3:
            ch = next((c for bar, beat, c in reversed(chords) if (bar, beat) <= (at[0], frac(at[1]))), None)
            if ch:
                pcs = [cur[v][2] % 12 for v in here]
                count = {p: pcs.count(p) for p in set(pcs)}
                roles = {ch["roles"].get(p): n for p, n in count.items()}
                if roles.get("third", 0) > 1 and ch["major"]:
                    add("doubled third", at, here, f"{ch['symbol']}: major third doubled")
                if roles.get("seventh", 0) > 1:
                    add("doubled seventh", at, here, ch["symbol"])
                if leading is not None and count.get(leading, 0) > 1:
                    add("doubled leading tone", at, here, ch["symbol"])
                if "third" not in roles:
                    add("missing third", at, here, ch["symbol"])
                if foreign := sorted({cur[v][3] for v in here if cur[v][2] % 12 not in ch["roles"]}):
                    add("non-chord tone", at, here, f"{ch['symbol']}: {' '.join(foreign)}")
                if ch["bass"] is not None and cur[here[-1]][2] % 12 != ch["bass"]:
                    add("bass", at, [here[-1]], f"{ch['symbol']}: bass is {cur[here[-1]][3]}")
        prev = cur
    summary = {}
    for p in problems:
        summary[p["kind"]] = summary.get(p["kind"], 0) + 1
    problems.sort(key=lambda p: (p["bar"], frac(p["beat"])))
    return {"voices_high_to_low": order, "verticals": len(times), "summary": summary, "problems": problems[:limit],
            **({"truncated": len(problems) - limit} if len(problems) > limit else {})}


if __name__ == "__main__":
    def voice(vid, notes):
        items, t = [], Fraction(0)
        for p, d in notes:
            items.append({"type": "note", "pos": str(t), "dur": d, "bar": 1 + int(t // 3), "beat": str(t % 3),
                          "pitches": [p], "midi": [spelling_to_midi(p)]})
            t += frac(d)
        return {"voice": vid, "items": items}

    # outer voices in parallel fifths D5/G4 -> E5/A4; the middle voice drops below the bass, then leaps a ninth
    rd = {"voices": [voice(1, [("D5", "1"), ("E5", "1"), ("F#5", "1")]), voice(2, [("B4", "1"), ("C#4", "1"), ("D5", "1")]),
                     voice(3, [("G4", "1"), ("A4", "1"), ("A4", "1")])]}
    r = check(rd, order=[1, 2, 3])
    kinds = r["summary"]
    assert kinds == {"parallel fifths": 1, "crossing": 1, "spacing": 1, "leap": 1}, r
    # a chord plan: D major with a doubled F#, then A7 with no third
    rd = {"voices": [voice(1, [("F#5", "1"), ("G5", "1")]), voice(2, [("F#4", "1"), ("E4", "1")]),
                     voice(3, [("D3", "1"), ("A2", "1")])]}
    r = check(rd, order=[1, 2, 3], plan="1 D, 1:1 A7", key="D")
    assert r["summary"].get("doubled third") == 1 and r["summary"].get("missing third") == 1, r
    assert parse_chord("Bm7b5")["roles"] == {11: "root", 2: "third", 5: "fifth", 9: "seventh"}
    print("analysis self-check ok")
