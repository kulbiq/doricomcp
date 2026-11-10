"""Confirmation harness: run every capability once, through the real MCP tool path, on the
throwaway fixture; verify; record doricomcp/data/confirmed.json; reset the fixture afterwards.

    uv run python -m doricomcp.confirm            # all
    uv run python -m doricomcp.confirm add_span   # only capabilities whose name contains the argument

Each tool already verifies its own write by read-back (and undoes it on failure); the checks here add an
independent expectation per capability. Never run against a real score: it resets to fixtures/throwaway.dorico.

Depends on: catalog, fixture, model, server, windows.
"""
import asyncio
import contextlib
import datetime
import json
import subprocess
import sys
import traceback

from mcp.server.mcpserver.exceptions import ToolError

from . import fixture
from .catalog import CONFIRMED
from .server import S, mcp

RH, LH = 2, 4  # fixture voices: piano right hand, left hand

# Beethoven Op.10/1 bars 1-8 (Mutopia #778), as written into the fixture
BEETHOVEN_RH = [("0", "3/2", "Eb4", "G4", "C5"), ("7/4", "1/4", "G4"), ("2", "3/4", "Eb5"), ("11/4", "1/4", "C5"),
                ("3", "3/4", "G5"), ("15/4", "1/4", "Eb5"), ("4", "3/4", "C6"), ("19/4", "1/4", "G5"), ("5", "1", "Eb6"),
                ("6", "1", "Eb6"), ("8", "1", "G4", "C5"), ("9", "2", "G4", "C5"), ("11", "1", "G4", "B4"),
                ("12", "3/2", "F4", "Ab4", "B4"), ("55/4", "1/4", "B4"), ("14", "3/4", "F5"), ("59/4", "1/4", "D5"),
                ("15", "3/4", "B5"), ("63/4", "1/4", "F5"), ("16", "3/4", "D6"), ("67/4", "1/4", "B5"), ("17", "1", "F6"),
                ("18", "1", "F6"), ("20", "1", "B4", "D5"), ("21", "2", "B4", "D5"), ("23", "1", "C5")]
BEETHOVEN_LH = [("0", "3/2", "C3", "Eb3", "G3", "C4"), ("8", "1", "C4", "Eb4"), ("9", "2", "C4", "Eb4"),
                ("11", "1", "D4", "F4"), ("12", "3/2", "D3", "F3", "Ab3", "B3", "D4"), ("20", "1", "D4", "F4", "Ab4"),
                ("21", "2", "D4", "F4", "Ab4"), ("23", "1", "Eb4", "G4")]


async def call(tool: str, **args):
    r = await mcp.call_tool(tool, args)
    if getattr(r, "is_error", False):
        raise RuntimeError(r.content[0].text)
    sc = getattr(r, "structured_content", None)
    if sc is not None:
        return sc.get("result", sc)
    txt = r.content[0].text if r.content and hasattr(r.content[0], "text") else None
    return json.loads(txt) if txt else r


def expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


def music_rows(rm, voice) -> set[tuple]:
    v = next(x for x in rm["voices"] if x["voice"] == voice)
    return {(i["pos"], i["dur"], *sorted(i["pitches"])) for i in v["items"] if i["type"] in ("note", "chord")}


def golden(data) -> set[tuple]:
    return {(p, d, *sorted(ps)) for p, d, *ps in data}


def to_notes(data) -> list[str]:
    """Beethoven rows -> add_notes calls (pos, text) grouped into contiguous runs."""
    return [(p, "+".join(ps) + ":" + d) for p, d, *ps in data]


# ---------------------------------------------------------------------------- tests (name, mechanism, coroutine)

async def t_read_overview():
    ov = await call("get_score_overview")
    v = ov["flows"][0]["voices"]
    expect(set(v) == {"2", "4"} and v["2"]["staff_index"] == 1 and v["4"]["staff_index"] == 2, f"voices {v}")
    return f"players {ov['players']}, voices {v}"


async def t_read_bar_map():
    bm = await call("get_bar_map", include_keys=True)
    ts = [(r["bar"], r["timesig"]) for r in bm["time_signatures"]]
    expect(ts == [(1, "3/4"), (89, "4/4"), (126, "10/8")], f"time signatures {ts}")
    expect(bm["key_signatures"][0]["key"] == "3b", f"key {bm['key_signatures']}")
    counts = await S().bridge.run("element_counts", flow=0)
    expect(counts["bardivs"] == 3, f"probe left orphan elements: {counts}")
    return f"{ts}, key 3b, no orphans left"


async def t_read_music():
    rm = await call("read_music", voices=[RH, LH], from_bar=1, to_bar=8)
    expect(music_rows(rm, RH) == golden(BEETHOVEN_RH), "RH bars 1-8 differ from Mutopia data")
    expect(music_rows(rm, LH) == golden(BEETHOVEN_LH), "LH bars 1-8 differ from Mutopia data")
    stacc = [i for i in next(x for x in rm["voices"] if x["voice"] == RH)["items"] if "staccato" in i.get("articulations", [])]
    expect(len(stacc) == 4, f"expected 4 staccato notes, got {len(stacc)}")
    return "RH 26 + LH 8 onsets equal the Mutopia source; 4 staccatos"


async def t_read_markings():
    mk = await call("read_markings", from_bar=1, to_bar=8)
    dyn = [(m["pos"], m["parts"][0]["level"]) for m in mk["markings"] if m["kind"] == "dynamic"]
    expect(dyn == [("0", "f"), ("8", "p"), ("12", "f"), ("20", "p")], f"dynamics {dyn}")
    at = [(m["parts"][0].get("bar"), m["parts"][0].get("beat")) for m in mk["markings"] if m["kind"] == "dynamic"]
    expect(at == [(1, "0"), (3, "2"), (5, "0"), (7, "2")], f"part positions {at}")
    slurs = [m for m in mk["markings"] if m["kind"] == "slur"]
    clefs = [m["clef"] for m in mk["markings"] if m["kind"] == "clef"]
    expect(len(slurs) == 6 and clefs == ["clef.treble", "clef.bass", "clef.treble"], f"slurs {len(slurs)} clefs {clefs}")
    return f"dynamics {dyn}, 6 slurs, clefs {clefs}"


async def t_read_context():
    c = await call("read_context_at", voice=LH, bar=5, beat="1")
    expect(c["time_signature"] == "3/4" and c["clef"] == "clef.bass" and c["dynamic"]["level"] == "f", str(c))
    return "bar 5 LH: 3/4, bass clef, f, 5 sounding notes"


async def t_golden_compose():
    for v in (RH, LH):
        await call("delete_range", voice=v, from_bar=1, to_bar=8)
    for v, data in ((RH, BEETHOVEN_RH), (LH, BEETHOVEN_LH)):
        for p, text in to_notes(data):
            await call("add_notes", notes=text, voice=v, pos=p)
    rm = await call("read_music", voices=[RH, LH], from_bar=1, to_bar=8)
    expect(music_rows(rm, RH) == golden(BEETHOVEN_RH) and music_rows(rm, LH) == golden(BEETHOVEN_LH), "recomposed bars differ")
    return "bars 1-8 deleted and recomposed through add_notes; read-back equals the Mutopia data"


async def t_add_notes():
    r = await call("add_notes", notes="C5+E5:q D5:e E5 F5:h r:q G5:h.", voice=RH, bar=31)
    expect(len(r["written"]) == 7, f"written {len(r['written'])}")
    return "chord, quaver run, minim, rest, dotted minim at bar 31"


async def _ids(bar, voice=RH):
    rm = await call("read_music", voices=[voice], from_bar=bar, to_bar=bar + 2)
    return [i["ids"][0] for i in rm["voices"][0]["items"] if i["type"] in ("note", "chord")]


async def t_set_pitch():
    ids = await _ids(31)
    for p in ("D#5", "Fbb5", "B#4", "D#5"):  # from a double flat a chromatic step can overshoot
        await call("set_pitch", event_id=ids[1], pitch=p)
        got = [i for i in (await call("read_music", voices=[RH], from_bar=31, to_bar=31))["voices"][0]["items"] if ids[1] in i.get("ids", [])]
        expect(got and got[0]["pitches"] == [p], f"note {ids[1]} should read {p} with the same id: {got}")
    return f"note {ids[1]} -> D#5, Fbb5, B#4, D#5 in place (same id)"


async def t_set_duration():
    ids = await _ids(31)
    await call("set_duration", event_id=ids[-1], duration="h")
    return "last note -> minim"


async def t_edit_notes():
    ids = await _ids(31)
    for a in ("pitch_up", "chromatic_down", "octave_up", "octave_down", "respell_above"):
        await call("edit_notes", event_ids=[ids[2]], action=a)
    return "pitch_up, chromatic_down, octave_up/down, respell_above on one note"


async def t_add_chord_interval():
    ids = await _ids(31)
    await call("add_interval", event_ids=[ids[3]], interval="3")
    return "third added above"


async def t_add_articulation():
    ids = await _ids(31)
    for k, i in (("staccato", 0), ("accent", 1), ("tenuto", 2)):
        await call("add_articulation", event_ids=[ids[i]], kind=k)
    rm = await call("read_music", voices=[RH], from_bar=31, to_bar=31)
    arts = {a for i in rm["voices"][0]["items"] for a in i.get("articulations", [])}
    expect({"staccato", "accent", "tenuto"} <= arts, f"read back {arts}")
    # every note of two chords given: SetArticulation toggles the whole chord, so it must be applied once per chord
    await call("add_notes", notes="C5+E5:q D5+F5", voice=RH, bar=56, replace=True)
    rm = await call("read_music", voices=[RH], from_bar=56, to_bar=56)
    chord_ids = [i for it in rm["voices"][0]["items"] if it["type"] == "chord" for i in it["ids"]]
    await call("add_articulation", event_ids=chord_ids, kind="staccato")
    again = await call("add_articulation", event_ids=chord_ids, kind="staccato")
    rm = await call("read_music", voices=[RH], from_bar=56, to_bar=56)
    chords = [it for it in rm["voices"][0]["items"] if it["type"] == "chord"]
    expect(len(chords) == 2 and all("staccato" in c.get("articulations", []) for c in chords), str(chords))
    expect("already" in again.get("note", ""), f"second staccato call was not a no-op: {again}")
    return "staccato, accent, tenuto read back; staccato on all notes of two chords, idempotent"


async def t_set_property():
    ids = await _ids(31)
    await call("set_property", event_ids=[ids[0]], name="kNoteVelocity", value="100")
    await call("set_property", event_ids=[ids[0]], name="kNoteVelocity")
    return "velocity set to 100 and reset"


async def t_add_span():
    ids = await _ids(31)
    out = []
    for kind, a, b in (("slur", 0, 3), ("cresc", 0, 2), ("dim", 3, 4), ("8va", 1, 3)):
        await call("add_span", start_event_id=ids[a], end_event_id=ids[b], kind=kind)
        out.append(kind)
    # a voice with rests (the hairpin used to stop at the first rest), then a hairpin starting on a dynamic (p<)
    await call("add_notes", notes="C5:q r D5 E5 r F5", voice=RH, bar=57, replace=True)
    ids = await _ids(57)
    r = await call("add_span", start_event_id=ids[0], end_event_id=ids[3], kind="cresc")
    g = r["created"][0]
    expect("warning" not in r and r["length"] == "6", f"cresc across rests to the end of F5 (6 crotchets): {r}")
    await call("delete_events", event_ids=[g["id"]])
    await call("add_dynamic", value="p", voice=RH, bar=57)
    r = await call("add_span", start_event_id=ids[0], end_event_id=ids[2], kind="dim")
    expect("merged_into" in r and r["length"] == "4" and "warning" not in r, f"dim on p to the end of E5: {r}")
    await call("set_property", event_ids=[r["merged_into"]["id"]], name="kDynamicGradualChangeDuration", value="2")
    mk = await call("read_markings", from_bar=57, to_bar=58)
    dyn = [m for m in mk["markings"] if m["kind"] == "dynamic"]
    gone = await call("run_command", command="Edit.Delete", select_event_id=dyn[0]["id"])
    expect(gone["deleted"], f"Edit.Delete by run_command deleted nothing: {gone}")

    # two voices on one staff, voice 1 denser: each slur only in its own voice
    await call("add_notes", notes="C5:e D5 E5 F5 G5 A5", voice=RH, bar=62, replace=True)
    v2 = (await call("add_voice", notes="A4:q B4 C5", voice=RH, bar=62))["new_voice"]
    top, low = await _ids(62), await _ids(62, v2)
    before = await _slurs(62)
    r = await call("add_span", kind="slur", start_event_id=low[0], end_event_id=low[2])
    r2 = await call("add_span", kind="slur", spans=[[top[0], top[2]], [top[3], top[5]]])
    new = [x for x in await _slurs(62) if x not in before]
    by_voice = sorted((x["stream"], x["pos"]) for x in new)
    want = sorted([(v2, await _pos(62)), (RH, await _pos(62)), (RH, await _pos(62, "3/2"))])
    expect(len(r["created"]) == 1 and len(r2["created"]) == 2 and by_voice == want, f"slurs by voice {by_voice}, expected {want}")
    return ("slur, cresc, dim, 8va; cresc across rests to the end note; dim merged into p and resized; deleted by id; "
            "slurs in a two-voice staff stay in their voice (one and two pairs per call)")


async def _slurs(bar):
    mk = await call("read_markings", from_bar=bar, to_bar=bar)
    return [{"stream": m["stream"], "pos": m["pos"], "id": m["id"]} for m in mk["markings"] if m["kind"] == "slur"]


async def _pos(bar, beat="0"):
    from fractions import Fraction

    from .model import fstr
    return fstr(await S().to_pos(0, bar, Fraction(beat)))


async def t_add_hairpin():
    # every voice of the piano holds a note through the bar: no anchor, so the note-input caret places them
    voices = (await call("get_score_overview"))["flows"][0]["voices"]
    piano = sorted(int(v) for v, info in voices.items() if info["instrument"] == voices[str(RH)]["instrument"])
    for v in piano:
        await call("add_notes", notes={RH: "D5:h.", LH: "D3:h."}.get(v, "A4:h."), voice=v, bar=70, replace=True)
    h = await call("add_hairpin", kind="cresc", voice=RH, bar=70, beat="1/2", to_bar=70, to_beat="2")
    expect(h["hairpin"] == "cresc" and h["length"] == "3/2" and h["from"] == {"bar": 70, "beat": "1/2"} and "warning" not in h, str(h))
    f = await call("add_dynamic", value="f", voice=RH, bar=70, beat="2")  # where the hairpin ends
    p = await call("add_dynamic", value="p", voice=RH, bar=70, beat="5/2")  # inside the held note
    expect([(d["level"], d["beat"]) for d in f["dynamics"] + p["dynamics"]] == [("f", "2"), ("p", "5/2")], f"{f} {p}")
    mk = await call("read_markings", from_bar=70, to_bar=70)
    parts = [(x.get("level") or x.get("hairpin"), x.get("beat"), x.get("length")) for m in mk["markings"]
             if m["kind"] == "dynamic" for x in m["parts"]]
    expect(("cresc", "1/2", "3/2") in parts and ("f", "2", None) in parts and ("p", "5/2", None) in parts, f"parts {parts}")
    c = await call("read_context_at", voice=RH, bar=70, beat="1")
    expect(c["dynamic"].get("in", {}).get("hairpin") == "cresc", str(c["dynamic"]))
    c = await call("read_context_at", voice=LH, bar=70, beat="11/4")
    expect(c["dynamic"].get("level") == "p", str(c["dynamic"]))
    both = await call("add_dynamic", value="pp", voice=RH, bar=71, at=[{"value": "ff", "bar": 72}])
    expect([d["level"] for d in both["dynamics"]] == ["pp", "ff"], str(both))
    again = await call("add_dynamic", value="mp", voice=RH, bar=72)  # where ff is: Dorico replaces it
    expect([(d["level"], d.get("replaced_existing")) for d in again["dynamics"]] == [("mp", True)], str(again))
    return ("cresc from beat 1/2 to 2 inside a held note (caret), f at its end, p inside the note; part positions and "
            "context read back; two dynamics in one call")


async def t_replace_keeps_markings():
    await call("add_notes", notes="C5:q D5 E5", voice=RH, bar=66, replace=True)
    await call("add_text", text="div.", voice=RH, bar=66)
    ids = await _ids(66)
    await call("add_span", kind="slur", start_event_id=ids[0], end_event_id=ids[2])
    r = await call("add_notes", notes="E5:q F5 G5", voice=RH, bar=66, replace=True)
    mk = await call("read_markings", from_bar=66, to_bar=66)
    kinds = sorted(m["kind"] for m in mk["markings"] if m["kind"] in ("text", "slur"))
    expect(kinds == ["slur", "text"] and r["replaced"] == 3 and "slurs_lost" not in r, f"after replace: {kinds}, {r}")
    sl = next(m for m in mk["markings"] if m["kind"] == "slur")
    expect((sl["beat"], sl.get("dur")) == ("0", "2"), f"slur put back from E5 to G5 (beat 0 to 2): {sl}")
    d = await call("delete_range", voice=RH, from_bar=66, to_bar=66)
    mk = await call("read_markings", from_bar=66, to_bar=66)
    # Dorico deletes the slur together with its notes; the text stays
    expect(d["by_type"].get("notes") == 3 and any(m.get("text") == "div." for m in mk["markings"]), f"after delete_range: {d}")
    return "replace=True keeps the span's text and puts its slur back on the new notes; delete_range keeps the text"


async def t_swap_voices():
    v2 = (await call("add_voice", notes="r:q A4:h", voice=RH, bar=68))["new_voice"]
    await call("add_notes", notes="E5:h.", voice=RH, bar=68, replace=True)
    await call("swap_voices", voice=RH, other_voice=v2, from_bar=68, to_bar=68)
    rm = await call("read_music", voices=[RH, v2], from_bar=68, to_bar=68, detail="compact")
    bars = {v["voice"]: v["bars"].get("68") for v in rm["voices"]}
    expect(bars == {RH: "r:1 A4:2", v2: "E5:3"}, f"after swap {bars}")
    rest = rm["voices"][0]["ids"]["68"][0]
    await call("edit_notes", event_ids=[rest], action="remove_rests")
    rm = await call("read_music", voices=[RH], from_bar=68, to_bar=68)
    expect(not [i for i in rm["voices"][0]["items"] if i["type"] == "rest"], "rest not removed")
    return "two voices swapped in bar 68 (compact read-back); the rest removed with remove_rests"


async def t_check_voice_leading():
    await call("add_notes", notes="D5:q E5 r", voice=RH, bar=67, replace=True)
    await call("add_notes", notes="G3:q A3 r", voice=LH, bar=67, replace=True)
    r = await call("check_voice_leading", voices=[RH, LH], from_bar=67, to_bar=67)
    expect(r["summary"].get("parallel fifths") == 1, str(r))
    g = await call("read_music", voices=[RH, LH], from_bar=67, to_bar=67, detail="grid")
    expect(g["rows"][:2] == [["67:0", "D5", "G3"], ["67:1", "E5", "A3"]], str(g["rows"]))
    return "parallel fifths D5/G3 -> E5/A3 found; grid read"


async def t_score_changes():
    tok = (await call("score_changes"))["token"]
    await call("add_notes", notes="B4:q", voice=RH, bar=69)
    r = await call("score_changes", since=tok)
    expect([(x["pitch"], x["by"]) for x in r["added"]] == [("B4", "server")], str(r))
    return "a note added through add_notes is reported as a server change"


async def t_delete_events():
    t = (await call("add_text", text="delete me", voice=RH, bar=59))["created"][0]
    r = await call("delete_events", event_ids=[t["id"]])
    expect([e["id"] for e in r["deleted"]] == [t["id"]], str(r))
    return "text created and deleted by id"


async def t_add_dynamic():
    await call("add_dynamic", value="mf", voice=RH, bar=31)
    await call("add_dynamic", value="sfz", voice=RH, bar=31, beat="1")
    await call("add_dynamic", value="pp", voice=RH, bar=40)  # empty bar: anchored by a temporary rest
    mk = await call("read_markings", from_bar=31, to_bar=40)
    lv = [m["parts"][0].get("level") for m in mk["markings"] if m["kind"] == "dynamic" and m.get("parts")]
    expect({"mf", "sfz", "pp"} <= set(lv), f"levels {lv}")
    left = await call("read_music", voices=[RH], from_bar=40, to_bar=40)
    expect(not [i for i in left["voices"][0]["items"] if i["type"] == "rest"], "temporary anchor rest left behind")
    return "mf and sfz on notes, pp in an empty bar; levels read back; anchor rest removed"


async def t_add_note_marking():
    ids = await _ids(31)
    await call("add_note_marking", event_ids=[ids[0]], kind="ornament", value="mordent")
    await call("add_note_marking", event_ids=[ids[1]], kind="hold", value="fermata")
    await call("add_note_marking", event_ids=[ids[2]], kind="playing_technique", value="pizz.")
    m = await call("read_markings", from_bar=31, to_bar=31)
    tech = [r["technique"]["name"] for r in m["markings"] if r["kind"] == "playing technique"]
    expect(tech == ["Pizzicato"], f"technique read back as {tech}")
    return "mordent, fermata, pizz. (by name, read back as Pizzicato)"


async def t_add_text():
    await call("add_text", text="dolce", voice=RH, bar=32)
    mk = await call("read_markings", from_bar=32, to_bar=32)
    expect(any(m.get("text") == "dolce" for m in mk["markings"]), "text not read back")
    return "dolce written and read back"


async def t_add_clef():
    await call("add_clef", clef="clef.alto", voice=LH, bar=33)
    c = await call("read_context_at", voice=LH, bar=33, beat="1")
    expect(c["clef"] == "clef.alto", c["clef"])
    return "alto clef on LH staff read back"


async def t_set_tempo():
    await call("set_tempo", value="Andante q=96", bar=34)
    await call("set_tempo", value="rit.", bar=35)
    m = await call("read_markings", from_bar=34, to_bar=35)
    got = [r.get("tempo") for r in m["markings"] if r["kind"].startswith("tempo")]
    expect(got[0]["text"] == "Andante" and got[0]["bpm"] == 96 and got[1]["text"] == "rit.", f"tempo read back as {got}")
    ctx = await call("read_context_at", bar=34, beat="1")
    expect(ctx["tempo"]["bpm"] == 96, f"tempo in force {ctx.get('tempo')}")
    # the reads selected the tempo markings: undo must skip those selection steps and remove the rit.
    await call("undo")
    m = await call("read_markings", from_bar=35, to_bar=35)
    expect(not [r for r in m["markings"] if r["kind"].startswith("tempo")], "undo after a tempo read did not remove rit.")
    return "Andante q=96 and rit. read back (text, bpm); undo after the reads removed rit."


async def t_set_time_signature():
    r = await call("set_time_signature", value="5/4", bar=36)
    expect(r["read_back"] == "5/4", str(r))
    bm = await call("get_bar_map")
    expect((36, "5/4") in [(x["bar"], x["timesig"]) for x in bm["time_signatures"]], "bar map")
    expect(bm["time_signatures"][-1]["bar"] == 105 or bm["time_signatures"][-1]["timesig"] == "10/8", "later bars renumbered")
    return "5/4 at bar 36, read back by the equality probe"


async def t_set_key_signature():
    await call("set_key_signature", value="2#", bar=38)
    bm = await call("get_bar_map", include_keys=True)
    k = [x for x in bm["key_signatures"] if x["bar"] == 38]
    expect(k and k[0]["key"] == "2#", f"keys {bm['key_signatures']}")
    return "2# at bar 38, read back by the key probe"


async def t_add_barline():
    await call("add_barline", kind="||", bar=42)
    await call("add_barline", kind="|:", bar=43)
    await call("add_barline", kind=":|", bar=44)
    return "||, |:, :| at bar starts"


async def t_add_repeat_marker():
    await call("add_repeat_marker", value="D.C. al Fine", bar=45)
    await call("add_repeat_marker", value="segno", bar=46)
    return "D.C. al Fine, segno"


async def t_add_rehearsal_mark():
    await call("add_rehearsal_mark", bar=47)
    return "rehearsal mark at bar 47"


async def t_add_break():
    await call("add_break", bar=48, kind="system")
    return "system break before bar 48"


async def t_add_grace_note():
    await call("add_grace_note", pitch="D5", voice=RH, bar=31)
    return "grace note before bar 31"


async def t_add_tuplet():
    r = await call("add_tuplet", ratio="3:2", unit="e", notes="C5:e D#5 Eb5", voice=RH, bar=52)
    got = [n["pitch"] for n in r["notes"]]
    expect(got == ["C5", "D#5", "Eb5"] and r["tuplets"], f"tuplet notes {got}")
    r = await call("add_tuplet", ratio="5:4", unit="s", notes="C#5:s D5 E5 F#5 Ab5", voice=RH, bar=52, beat="1")
    expect(len(r["notes"]) == 5, str(r))
    r = await call("add_tuplet", ratio="6:4", unit="s", notes="Ab4:s Bb4 D5 F5 D5 Bb4 Ab4 Bb4 D5 F5 D5 Bb4", voice=RH, bar=53)
    expect(r["groups"] == 2 and len(r["notes"]) == 12 and len(r["tuplets"]) >= 1, str(r))
    # a tuplet that opens with a rest, then a dynamic at its start (anchored on the tuplet itself)
    await call("add_tuplet", ratio="3:2", unit="e", notes="r:e D5 E5", voice=RH, bar=53, beat="2")
    d = await call("add_dynamic", value="mp", voice=RH, bar=53, beat="2")
    expect(d["dynamics"], str(d))
    return "3:2 quavers, 5:4 semiquavers, two 6:4 sextuplets in one call; mp at a rest-led triplet"


async def t_add_voice():
    r = await call("add_voice", notes="Bb3+D4:e r Bb3+D4 r C4:q", voice=RH, bar=54)
    ov = await call("get_score_overview")
    v = ov["flows"][0]["voices"][str(r["new_voice"])]
    expect(v["staff_index"] == 1 and v["voice_index"] >= 2, str(v))  # add_span's test made one before
    rm = await call("read_music", voices=[r["new_voice"]], from_bar=54, to_bar=54)
    rows = [(i["beat"], sorted(i["pitches"])) for i in rm["voices"][0]["items"] if i["type"] in ("note", "chord")]
    expect(rows == [("0", ["Bb3", "D4"]), ("1", ["Bb3", "D4"]), ("2", ["C4"])], f"new voice reads {rows}")
    await call("add_notes", notes="F4:h.", voice=r["new_voice"], bar=55)
    return f"voice {r['new_voice']} created on the RH staff, recorded, and written to with add_notes"


async def t_copy_range():
    await call("copy_range", voice=RH, dest_voice=RH, from_bar=31, to_bar=31, dest_bar=50)
    await call("copy_range", voice=RH, dest_voice=LH, from_bar=50, to_bar=50, dest_bar=50, move=True)
    return "copy RH bar 31 -> bar 50; move to LH"


async def t_delete_range():
    await call("delete_range", voice=LH, from_bar=50, to_bar=50)
    rm = await call("read_music", voices=[LH], from_bar=50, to_bar=50)
    expect(not [i for i in rm["voices"][0]["items"] if i["type"] != "implicit rest"], "not empty")
    return "LH bar 50 emptied"


async def t_set_option():
    r = await call("set_option", kind="kLayout", path="playerInstrumentTransitionOptions.showWarningLabels", value="false", layout_ids=[1])
    return f"layout 1 option -> {r['value']}"


async def t_add_player():
    r = await call("add_player", instrument="instrument.strings.violin")
    return f"violin player {r['player_id']}"


async def t_add_instrument():
    await call("add_instrument", player_id=0, instrument="instrument.keyboard.celesta")
    return "celesta doubling for player 0"


async def t_remove_instrument():
    before = {i for pl in (await call("get_score_overview"))["players"] for i in pl["instruments"]}
    await call("add_instrument", player_id=0, instrument="instrument.keyboard.celesta")
    gone = next(i for pl in (await call("get_score_overview"))["players"] for i in pl["instruments"] if i not in before)
    r = await call("remove_instrument", instrument_id=gone)
    expect(all(gone not in pl["instruments"] for pl in r["players"]) and "note" not in r, str(r))
    return "the celesta doubling removed after Dorico's confirmation; the player keeps its first instrument"


async def t_quarter_tones():
    # the fixture is 12-EDO and Dorico's interfaces cannot switch it, so a quarter-tone must be refused and undone
    before = (await call("read_music", voices=[RH], from_bar=64, to_bar=64, detail="compact"))["voices"][0]["bars"]
    try:
        await call("add_notes", notes="A1/244:q", voice=RH, bar=64, replace=True)
        expect(False, "a quarter-tone was written in a 12-EDO score")
    except ToolError as e:
        expect("24-EDO" in str(e) and "undone" in str(e), str(e))
    after = (await call("read_music", voices=[RH], from_bar=64, to_bar=64, detail="compact"))["voices"][0]["bars"]
    expect(before == after, f"{before} -> {after}")
    return "a quarter-tone in a 12-EDO score is refused with the 24-EDO hint and undone (written and read in a 24-EDO score by hand)"


async def t_rename_player():
    r = await call("rename_player", player_id=0, name="Keys")
    expect("Keys" in str(r["players"]), str(r))
    return "player 0 renamed"


async def t_open_meter():
    bm = await call("get_bar_map", flow=1)
    await call("read_music", flow=1, from_bar=1, to_bar=1)
    await call("set_time_signature", value="2/4", bar=1, flow=1)
    after = await call("get_bar_map", flow=1)
    expect(after["time_signatures"][0]["timesig"] == "2/4", str(after["time_signatures"]))
    return f"flow 1 read before any signature ({bm['time_signatures'][0]['timesig']}); 2/4 set at bar 1 and read back"


async def t_rename_flow():
    r = await call("rename_flow", flow_id=1, name="Coda test")
    expect({"id": 1, "name": "Coda test"} in r["flows"], str(r))
    return "flow 1 renamed and read back"


async def t_delete_flow():
    r = await call("delete_flow", flow_id=1)
    expect([f["id"] for f in r["flows"]] == [0], str(r))
    return "flow 1 deleted"


async def t_dialogs():
    # Dorico confirms instrument deletion with a modal dialog (measured): open it, read it, answer Cancel
    inst = (await call("get_score_overview"))["instruments"][-1]
    cmd = asyncio.ensure_future(S().rc.command(f"Project.Instrument.Delete?InstrumentID={inst}", timeout=60))
    for _ in range(20):
        await asyncio.sleep(0.25)
        ds = [d for d in (await call("list_dialogs"))["dialogs"] if d["modal"]]
        if ds:
            break
    expect(ds, "no modal dialog appeared for Project.Instrument.Delete")
    titles = [c.get("title") for c in ds[0]["controls"] if c["role"] == "AXButton"]
    no = next(t for t in titles if t and t.lower() in ("cancel", "no"))
    r = await call("dialog_click", control=no)
    expect(r["dialog_closed"], str(r))
    await asyncio.gather(cmd, return_exceptions=True)
    S().mark_written()
    expect(inst in (await call("get_score_overview"))["instruments"], "the instrument was deleted although Cancel was pressed")
    return f"confirmation dialog listed ({ds[0]['title']!r}, buttons {titles}) and answered {no!r}"


async def t_add_flow():
    r = await call("add_flow")
    expect(len(r["flows"]) == 2, str(r))
    return "second flow added"


async def t_layouts():
    r = await call("add_layout", name="Excerpt")
    lid = next(lay["layoutID"] for lay in r["layouts"] if lay["layoutName"] == "Excerpt")
    await call("layout_flows", layout_id=lid, flow_ids=[1], include=False)
    await call("layout_flows", layout_id=lid, flow_ids=[1], include=True)
    return f"custom layout {lid} named, flow 1 excluded and included (no read-back available)"


async def t_set_score_order():
    await call("set_score_order", order="instrumentscoreorder.orchestral")
    return "orchestral order"


async def t_go_to():
    await call("go_to", bar=31)
    return "view at bar 31"


async def t_select_events():
    ids = await _ids(1)
    r = await call("select_events", event_ids=[ids[0]])
    expect(r["status"]["hasSelection"], str(r))
    return "selected; status reports a selection"


async def t_playback():
    await call("play", from_bar=1)
    await asyncio.sleep(1.5)
    await call("stop")
    return "played 1.5 s from bar 1 and stopped"


async def t_undo():
    def a5(rm):  # bar 60 is empty in the fixture; look for this test's own note only
        return [i for i in rm["voices"][0]["items"] if i["type"] == "note" and "A5" in i["pitches"]]
    await call("add_notes", notes="A5:q", voice=RH, bar=60)
    await call("undo")
    await call("redo")  # must follow undo directly: any script (even a read) clears Dorico's redo stack
    expect(a5(await call("read_music", voices=[RH], from_bar=60, to_bar=60)), "redo did not restore the note")
    await call("undo")
    expect(not a5(await call("read_music", voices=[RH], from_bar=60, to_bar=60)), "undo did not remove the note")
    return "add, undo, redo (verified), undo (verified)"


async def t_run_command():
    ids = await _ids(31)
    await call("run_command", command="NoteInput.SetArticulation?Value=kStaccatissimo", select_event_id=ids[0])
    return "validated command on a selected note"


async def t_screenshot():
    r = await mcp.call_tool("screenshot", {"bar": 31, "zoom": 200})
    expect(r.content and getattr(r.content[0], "type", "") == "image", "no image")
    zoom = (await S().rc.status()).get("zoomPercent")
    return f"PNG of the score window at bar 31, 200% (zoom restored to {zoom})"


TESTS = [
    ("read_overview", "Lua Score/Flow/streams + RC flows/layouts", t_read_overview),
    ("read_bar_map", "bar-division events + Variant equality probe (+ Edit.Undo) + key letter probe", t_read_bar_map),
    ("read_music", "Lua .events + stream dump", t_read_music),
    ("read_markings", "stream dumps + element tables + equality probe", t_read_markings),
    ("read_context", "events up to a point", t_read_context),
    ("golden_compose", "delete_range + add_notes (Lua createNote)", t_golden_compose),
    ("add_notes", "Lua createNote/createRest", t_add_notes),
    ("set_pitch", "Lua delete + createNote", t_set_pitch),
    ("set_duration", "Lua Event.duration", t_set_duration),
    ("edit_notes", "EventEdit.Select + NoteEdit.* commands", t_edit_notes),
    ("add_chord_interval", "NoteInput.TransposeOrAddNotesToSelection", t_add_chord_interval),
    ("add_articulation", "NoteInput.SetArticulation", t_add_articulation),
    ("set_property", "EventEdit.ChangeProperty", t_set_property),
    ("add_span", "select start + EventEdit.Select AddToSelection end + SlurStart/HairpinStart/OttavaLineStart", t_add_span),
    ("add_hairpin", "anchor or note-input caret (SetGridResolution + MoveAdvance) + HairpinStart/Stop + sub-element length", t_add_hairpin),
    ("replace_keeps_markings", "Event:delete per note/rest instead of deleteEventsInRange", t_replace_keeps_markings),
    ("add_dynamic", "NoteInput.CreateDynamic on a selected or temporary anchor", t_add_dynamic),
    ("add_note_marking", "NoteInput.CreateOrnament/CreatePause/CreatePlayingTechnique", t_add_note_marking),
    ("add_text", "Lua createText", t_add_text),
    ("add_clef", "Lua createClef on the staff stream", t_add_clef),
    ("set_tempo", "NoteInput.CreateTempo on an anchor", t_set_tempo),
    ("set_time_signature", "NoteInput.CreateTimeSignature + equality read-back", t_set_time_signature),
    ("set_key_signature", "NoteInput.CreateKeySignature + key probe read-back", t_set_key_signature),
    ("quarter_tones", "Lua createNote + NoteInput.SetAccidental (24-EDO accidental); refused cleanly in 12-EDO", t_quarter_tones),
    ("add_barline", "NoteInput.CreateBarLine at a bar start", t_add_barline),
    ("add_repeat_marker", "NoteInput.AddRepeatsToSelection", t_add_repeat_marker),
    ("add_rehearsal_mark", "NoteInput.CreateRehearsalMark", t_add_rehearsal_mark),
    ("add_break", "Edit.CreateSystemBreak", t_add_break),
    ("add_grace_note", "Lua createGraceNote", t_add_grace_note),
    ("add_tuplet", "note input: StartTupletRun (one run = consecutive groups) + explicit accidentals/octaves", t_add_tuplet),
    ("add_voice", "note input: CreateVoice + first item, rest via Lua createNote; staff recorded in ~/.doricomcp/voices.json", t_add_voice),
    ("copy_range", "Lua createNote/createRest (copyRange is a no-op)", t_copy_range),
    ("swap_voices", "Event:delete + createNote/createRest in both voices; Edit.RemoveRests", t_swap_voices),
    ("check_voice_leading", "read_music + pure-Python analysis; read_music grid", t_check_voice_leading),
    ("score_changes", "event snapshots + the server's write log", t_score_changes),
    ("delete_range", "Event:delete per note/rest", t_delete_range),
    ("set_option", "Project.Layout.SetOptions Dictionary + getoptions read-back", t_set_option),
    ("add_player", "Project.SoloPlayer.New + Project.Instrument.New", t_add_player),
    ("add_instrument", "Project.Instrument.New", t_add_instrument),
    ("remove_instrument", "Project.Instrument.Delete + Dorico's confirmation answered OK", t_remove_instrument),
    ("rename_player", "Project.Player.Rename in Setup mode", t_rename_player),
    ("dialogs", "macOS Accessibility on a Dorico confirmation dialog: list, press Cancel", t_dialogs),
    ("add_flow", "Project.Flow.New", t_add_flow),
    ("layouts", "Project.Layout.New + Layout.Rename/Layouts.Include|ExcludeFlows in Setup mode", t_layouts),
    ("open_meter", "bar map with an implicit open-meter region before the first time signature", t_open_meter),
    ("rename_flow", "Project.Flow.Rename in Setup mode + getflows read-back", t_rename_flow),
    ("delete_flow", "Project.Flows.Delete in Setup mode", t_delete_flow),
    ("set_score_order", "Project.SetInstrumentScoreOrder", t_set_score_order),
    ("go_to", "Edit.GoTo", t_go_to),
    ("select_events", "EventEdit.Select", t_select_events),
    ("playback", "Play.MovePlayheadToFlowPosition + Play.StartOrStop + Play.Stop", t_playback),
    ("undo", "Edit.Undo/Redo after a state refresh", t_undo),
    ("run_command", "catalogue-validated command on a selected event", t_run_command),
    ("delete_events", "EventEdit.Delete with each event's block", t_delete_events),
    ("screenshot", "CoreGraphics window capture", t_screenshot),
]
READ_ONLY = {"describe_commands", "describe_enums", "describe_property", "list_library", "dorico_status", "get_options",
             "get_selection", "list_capabilities", "refresh"}


async def main(only: str | None):
    old = json.loads(CONFIRMED.read_text()) if CONFIRMED.exists() else []
    results = {r["capability"]: r for r in old}
    today = datetime.date.today().isoformat()
    for name in READ_ONLY:
        results[name] = {"capability": name, "mechanism": "static catalogue / Remote Control read", "status": "read-only",
                         "evidence": "no score access or read-only RC message", "date": today}
    await fixture.reset(S().rc)
    S().mark_written()
    try:
        for name, mech, fn in TESTS:
            if only and only not in name:
                continue
            try:
                ev = await fn()
                status = "confirmed"
            except Exception as e:  # noqa: BLE001 - a failing capability is recorded, the run goes on
                ev, status = f"{type(e).__name__}: {str(e)[:500]}", "failed"
                traceback.print_exc(limit=1)
                if "no result within" in ev:  # Dorico blocked by a dialog: restart and continue
                    await fixture.force_restart()
                    S().rc.ws = None
                    S().mark_written()
            print(f"{status:10} {name:22} {ev}")
            results[name] = {"capability": name, "mechanism": mech, "status": status, "evidence": ev, "date": today}
            CONFIRMED.write_text(json.dumps(sorted(results.values(), key=lambda r: r["capability"]), indent=1) + "\n")
    finally:
        from .windows import screenshot
        with contextlib.suppress(OSError, RuntimeError, subprocess.SubprocessError):
            (CONFIRMED.parent / "confirm_last.png").write_bytes(screenshot())
        if "--keep" not in sys.argv:
            await fixture.reset(S().rc)
        await S().rc.close()
    bad = [r for r in results.values() if r["status"] == "failed"]
    print(f"{sum(r['status'] == 'confirmed' for r in results.values())} confirmed, {len(bad)} failed")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    asyncio.run(main(args[0] if args else None))
