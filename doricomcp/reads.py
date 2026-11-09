"""Composer-facing views of the digital twin: music per voice, markings, and what is in force at a point.

Depends on: catalog, model, session.
"""
import re
from fractions import Fraction

from .model import Event, bar_at, frac, fstr
from .session import Session

NOTE_TYPES = {"kNoteEvent", "kRestEvent", "kGraceNoteEvent", "kTupletEvent", "kBarRestEvent"}
MARKING_KIND = {
    "kDynamicGroupEvent": "dynamic", "kSlurEvent": "slur", "kTieEvent": "tie", "kClefEvent": "clef",
    "kOttavaLineEvent": "ottava", "kTextEvent": "text", "kImmediateTempoChangeEvent": "tempo",
    "kGradualTempoChangeEvent": "tempo (gradual)", "kTempoEvent": "tempo", "kPauseEvent": "hold/pause",
    "kRehearsalMarkEvent": "rehearsal mark", "kRepeatMarkerEvent": "repeat marker", "kBreakEvent": "break",
    "kPlayingTechniqueEvent": "playing technique", "kOrnamentEvent": "ornament", "kTrillEvent": "trill",
    "kGlissandoLineEvent": "glissando", "kPedalLineEvent": "pedal", "kArpeggioEvent": "arpeggio",
    "kLyricEvent": "lyric", "kChordSymbolEvent": "chord symbol", "kFiguredBassEvent": "figured bass",
    "kBarDivisionEvent": "time signature / barline", "kTonalityDivisionEvent": "key signature",
    "kFingeringEvent": "fingering", "kCommentEvent": "comment", "kRepeatEndingEvent": "repeat ending",
}
# read confidence per marking kind: "value" = content readable; "position" = only where it is
VALUE_READABLE = {"dynamic", "slur", "clef", "ottava", "text", "time signature / barline", "key signature", "break",
                  "tempo", "tempo (gradual)", "playing technique"}
TECHNIQUE = re.compile(r"\s(pta\.\S+)")  # the technique's appearance id in the stream dump
TEMPO_TYPES = {"kImmediateTempoChangeEvent", "kGradualTempoChangeEvent", "kTempoEvent"}
ARTIC_NAMES = {"kArticulationDuration": {0: "staccato", 1: "staccato", 2: "staccatissimo", 3: "tenuto", 4: "staccato-tenuto"},
               "kArticulationForce": {0: "accent", 1: "marcato"}, "kArticulationStress": {0: "stress", 1: "unstress"}}


def tempo_value(panel: dict) -> dict:
    """A tempo event's Properties-panel values -> text, bpm, beat unit, relative/final percent."""
    out = {}
    if panel.get("kTempoText"):
        out["text"] = panel["kTempoText"]
    if us := panel.get("kTempoImmediateAbsoluteTempoMicrosecs"):  # microseconds per beat
        bpm = round(60e6 / int(us), 1)
        out["bpm"] = int(bpm) if bpm == int(bpm) else bpm
        out["beat_unit"] = panel.get("kTempoImmediateAbsoluteBeatUnit") or "not readable (h.=60 and q=60 both read 60)"
    for k, name in (("kTempoImmediateRelativePercent", "percent"),
                    ("kTempoGradualFinalTempoPercent", "final_percent")):
        if panel.get(k):
            out[name] = panel[k]
    if panel.get("kTempoImmediateAbsoluteShowMetronomeMarkFlag") == "false":
        out["metronome_mark_hidden"] = True
    return out


def _articulations(props: dict) -> list[str]:
    out = []
    for k, names in ARTIC_NAMES.items():
        if k in props and props[k] is not None:
            out.append(names.get(props[k], f"{k}={props[k]}"))
    return out


def compact(items: list[dict]) -> tuple[dict, dict]:
    """read_music items -> ({bar: "add_notes text"}, {bar: [ids per token]}). Each bar's text starts at its first
    item; "@beat " marks a bar whose first item does not start on beat 0 (a note held over the barline)."""
    text, ids, last = {}, {}, {}
    for it in items:
        bar = str(it["bar"])
        if it["type"] == "implicit rest" and it.get("to_range_end"):
            continue
        dur = it["dur"] if isinstance(it["dur"], str) else max(it["dur"], key=frac)
        head = "+".join(it["pitches"]) if "pitches" in it else "r"
        tok = head + (":" + dur if last.get(bar) != dur else "")
        if bar not in text:
            beat = it["beat"]
            text[bar], ids[bar] = ("" if beat == "0" else f"@{beat} "), []
        text[bar] += tok + " "
        ids[bar].append(it["ids"] if len(it.get("ids", [])) > 1 else (it["ids"][0] if it.get("ids") else None))
        last[bar] = dur
    return {b: t.strip() for b, t in text.items()}, ids


def grid(voices: list[dict], step: Fraction | None, regions) -> dict:
    """One row per onset of any voice (or every `step` crotchets): bar, beat and each voice's sounding pitches.
    "~" marks a note held from earlier, "." silence."""
    sounding = {}
    for v in voices:
        sounding[v["voice"]] = [(frac(i["pos"]), frac(i["pos"]) + max(frac(d) for d in (i["dur"] if isinstance(i["dur"], list) else [i["dur"]])),
                                 "+".join(i["pitches"])) for i in v["items"] if i["type"] in ("note", "chord")]
    times = sorted({t for ns in sounding.values() for t, _, _ in ns} | {frac(i["pos"]) for v in voices for i in v["items"]
                                                                        if i["type"] in ("rest",)})
    if step:
        lo = min(times, default=Fraction(0))
        hi = max((e for ns in sounding.values() for _, e, _ in ns), default=lo)
        times = sorted(set(times) | {lo + k * step for k in range(int((hi - lo) / step) + 1)})
    rows = []
    for t in times:
        cells = []
        for v in voices:
            here = [(a, p) for a, e, p in sounding[v["voice"]] if a <= t < e]
            cells.append(" ".join(p if a == t else "~" + p for a, p in here) or ".")
        bar, beat = bar_at(regions, t)
        rows.append([f"{bar}:{fstr(beat)}"] + cells)
    return {"columns": ["bar:beat"] + [str(v["voice"]) for v in voices], "rows": rows}


async def read_music(s: Session, flow: int, voices: list[int] | None, lo: Fraction, hi: Fraction, detail: str = "full",
                     step: Fraction | None = None) -> dict:
    """detail: full (every item with ids, MIDI, properties), compact (per bar add_notes text + ids), grid (verticals)."""
    if detail not in ("full", "compact", "grid"):
        raise ValueError("detail: full, compact or grid")
    vmap = await s.voices(flow)
    voices = voices or sorted(vmap)
    regions, _ = await s.regions(flow)
    evs = await s.events(flow, voices, lo, hi)
    out = []
    for v in voices:
        mine = [e for e in evs if e.stream == v]
        props_ok = all(e.source == "events" for e in mine if e.type == "kNoteEvent")
        items, slurs = [], []
        by_pos: dict[Fraction, list[Event]] = {}
        for e in mine:
            if e.type in ("kNoteEvent", "kRestEvent"):
                by_pos.setdefault(e.pos, []).append(e)
            elif e.type == "kSlurEvent":
                slurs.append({"id": e.id, "from": fstr(e.pos), "to": fstr(e.end)})
        t = lo
        for p in sorted(by_pos):
            group = by_pos[p]
            if p > t and p >= lo:
                b, o = bar_at(regions, t)
                items.append({"type": "implicit rest", "pos": fstr(t), "dur": fstr(p - t), "bar": b, "beat": fstr(o)})
            notes = [e for e in group if e.type == "kNoteEvent"]
            bar, off = bar_at(regions, p)
            base = {"pos": fstr(p), "bar": bar, "beat": fstr(off)}
            if notes:
                notes.sort(key=lambda e: e.midi or 0)
                durs = {e.dur for e in notes}
                item = {"type": "chord" if len(notes) > 1 else "note", **base,
                        "dur": fstr(max(durs)) if len(durs) == 1 else [fstr(d) for d in durs],
                        "pitches": [e.spelling for e in notes], "midi": [e.midi for e in notes],
                        "ids": [e.id for e in notes]}
                arts = sorted({a for e in notes for a in _articulations(e.props)})
                if arts:
                    item["articulations"] = arts
                extra = {k: v for e in notes for k, v in e.props.items()
                         if k not in ARTIC_NAMES and k not in ("kNotePitch", "kEventPosition", "kEventDuration",
                                                              "kEventSecondaryPosition", "kEventSecondaryEndPositionOffset")}
                if extra:
                    item["props"] = {k: ("present (value sealed)" if v == {"sealed": True} else v) for k, v in extra.items()}
                items.append(item)
                t = max(t, p + max(durs))
            for r in (e for e in group if e.type == "kRestEvent"):
                items.append({"type": "rest", **base, "dur": fstr(r.dur), "ids": [r.id]})
                t = max(t, p + r.dur)
        if t < hi and items:
            items.append({"type": "implicit rest", "pos": fstr(t), "dur": fstr(hi - t), "bar": bar_at(regions, t)[0], "to_range_end": True})
        graces = [{"id": e.id, "pos": fstr(e.pos), "pitch": e.spelling} for e in mine if e.type == "kGraceNoteEvent"]
        tuplets = [e.json() for e in mine if e.type == "kTupletEvent"]
        out.append({"voice": v, **vmap.get(v, {}), "items": items, "slurs": slurs, "grace_notes": graces,
                    "tuplets": tuplets, "note_properties_readable": props_ok,
                    **({} if props_ok else {"why_not": "this voice contains an event type Dorico's Lua API cannot wrap "
                                                       "(trill, ornament, arpeggio, playing technique, glissando, tempo...); notes "
                                                       "and rhythms come from the stream dump, articulations/ties are not readable"})})
    head = {"flow": flow, "from": fstr(lo), "to": fstr(hi)}
    if detail == "grid":
        g = grid(out, step, regions)
        if missing := [x["voice"] for x in out if not x["items"]]:
            g["silent_voices"] = missing
        return {**head, **g, "legend": "pitches sounding at each onset; ~ = held from earlier, . = silence"}
    if detail == "compact":
        rows = []
        for x in out:
            text, ids = compact(x["items"])
            rows.append({"voice": x["voice"], "instrument": x.get("instrument"), "bars": text, "ids": ids,
                         **({"slurs": [f"{sl['from']}-{sl['to']}" for sl in x["slurs"]]} if x["slurs"] else {}),
                         **({"tuplets": len(x["tuplets"])} if x["tuplets"] else {})})
        return {**head, "voices": rows, "legend": "add_notes syntax per bar (a duration repeats until it changes; @beat = "
                                                  "first item's offset); ids align with the items (null = rest)"}
    return {**head, "voices": out,
            "units": "positions and durations in crotchets (quarter notes); beat = offset in crotchets within the bar"}


async def read_markings(s: Session, flow: int, lo: Fraction, hi: Fraction) -> dict:
    regions, _ = await s.regions(flow)
    evs = await s.events(flow, None, lo, hi)
    dyn = await s.dynamics(flow, evs)
    rows = []
    for e in evs:
        if e.type in NOTE_TYPES:
            continue
        kind = MARKING_KIND.get(e.type, e.type)
        row = {"kind": kind, **e.json(), "bar": bar_at(regions, e.pos)[0], "beat": fstr(bar_at(regions, e.pos)[1]),
               "read": "value" if kind in VALUE_READABLE else "position only (content not exposed by Dorico's API)"}
        if e.type == "kDynamicGroupEvent":
            row["parts"] = [locate(part, regions) for part in dyn.get(e.id, {}).get("parts", [])]
            # Dorico draws a hairpin's length from its part in the group; the event's own Gradual values are not drawn
            props = {k: v for k, v in row.pop("props", {}).items() if "Gradual" not in k}
            if props:
                row["props"] = props
        if e.type == "kBarDivisionEvent":
            ts, _ = await s.prober.sealed(flow, [e.element], [])
            row["timesig"] = ts[e.element]
        if e.type == "kPlayingTechniqueEvent" and (tech := TECHNIQUE.search(e.desc)):
            row["technique"] = {"id": tech.group(1)}
        rows.append(row)
    techs = {x["entityID"]: x["name"] for x in await s.library("kPlayingTechniqueAppearanceCollection")} \
        if any(e.type == "kPlayingTechniqueEvent" for e in evs) else {}
    for row in rows:
        if "technique" in row:
            row["technique"]["name"] = techs.get(row["technique"]["id"])
    tempos = [e for e in evs if e.type in TEMPO_TYPES]
    if tempos:
        panel = await s.selected_props(flow, tempos)
        for row in rows:
            if row["id"] in panel:
                row["tempo"] = tempo_value(panel[row["id"]])
    return {"flow": flow, "from": fstr(lo), "to": fstr(hi), "markings": rows}


def locate(part: dict, regions) -> dict:
    """A dynamic group's part with its bar/beat (and a hairpin's end)."""
    if "pos" not in part:
        return part
    out = dict(part)
    out["bar"], beat = bar_at(regions, frac(part["pos"]))
    out["beat"] = fstr(beat)
    if "length" in part:
        end = frac(part["pos"]) + frac(part["length"])
        out["end"] = fstr(end)
        out["end_bar"], eb = bar_at(regions, end)
        out["end_beat"] = fstr(eb)
    return out


def in_force(groups: list[tuple[Event, dict]], pos: Fraction) -> dict | None:
    """The last dynamic level at or before pos from (group event, its dynamics() entry) pairs, and any hairpin
    running through pos."""
    level, hairpin = None, None
    for g, d in groups:
        for part in d.get("parts", []):
            at = frac(part["pos"]) if "pos" in part else g.pos
            if at > pos:
                continue
            if "level" in part and (level is None or at >= level[0]):
                level = (at, part["level"])
            if "length" in part and at <= pos < at + frac(part["length"]):
                hairpin = {"hairpin": part["hairpin"], "from": fstr(at), "to": fstr(at + frac(part["length"]))}
    if level is None and hairpin is None:
        return None
    return {**({"level": level[1], "since_pos": fstr(level[0])} if level else {}), **({"in": hairpin} if hairpin else {})}


async def read_context_at(s: Session, flow: int, pos: Fraction, voice: int | None, with_key: bool = False) -> dict:
    regions, _ = await s.regions(flow)
    bar, off = bar_at(regions, pos)
    region = max((r for r in regions if r.start <= pos), key=lambda r: r.start)
    vmap = await s.voices(flow)
    ctx = {"flow": flow, "pos": fstr(pos), "bar": bar, "beat": fstr(off), "time_signature": region.timesig,
           "time_signature_since_bar": region.first_bar}
    evs = await s.events(flow, None, None, pos + Fraction(1, 1024))
    before = [e for e in evs if e.pos <= pos]
    tempo = [e for e in before if e.type in ("kImmediateTempoChangeEvent", "kTempoEvent")]
    if tempo:
        panel = await s.selected_props(flow, tempo[-1:])
        ctx["tempo"] = {"since_pos": fstr(tempo[-1].pos), **tempo_value(panel[tempo[-1].id])}
    keys = [e for e in before if e.type == "kTonalityDivisionEvent"]
    if keys:
        ctx["key_signature_since"] = {"pos": fstr(keys[-1].pos), "bar": bar_at(regions, keys[-1].pos)[0]}
        if with_key:
            bm = await s.bar_map(flow, keys=True)
            row = [k for k in bm["key_signatures"] if k["event"] == keys[-1].id]
            if row:
                ctx["key_signature"] = row[0].get("key"), row[0].get("meaning") or row[0].get("reason")
    if voice is not None:
        v = vmap.get(voice, {})
        stave = v.get("staff_stream")
        clefs = [e for e in before if e.type == "kClefEvent" and e.stream == stave]
        ctx["clef"] = clefs[-1].json().get("clef") if clefs else "instrument default (no clef change before this point)"
        # dynamics sit on a stream of the instrument: a staff (stave stream) or, voice-specific, a voice
        inst = next((i for i in (await s.flow_info(flow))["instruments"] if voice in i["voices"]), {"voices": [voice]})
        inst_staves = set(inst["voices"]) | {vv.get("staff_stream") for k, vv in vmap.items() if k in inst["voices"]} - {None}
        dyns = [e for e in before if e.type == "kDynamicGroupEvent" and e.stream in inst_staves]
        if dyns:
            d = await s.dynamics(flow, dyns[-12:])
            ctx["dynamic"] = in_force([(g, d.get(g.id, {})) for g in dyns[-12:]], pos) or "none readable"
        ott = [e for e in before if e.type == "kOttavaLineEvent" and e.stream in inst_staves | {voice} and e.pos <= pos < e.end]
        if ott:
            ctx["ottava"] = ott[-1].json()
        sounding = [e for e in evs if e.stream == voice and e.type == "kNoteEvent" and e.pos <= pos < e.end]
        ctx["sounding"] = [{"id": e.id, "pitch": e.spelling, "from": fstr(e.pos), "to": fstr(e.end)} for e in sounding]
        ctx["voice"] = {"id": voice, **v}
    return ctx
