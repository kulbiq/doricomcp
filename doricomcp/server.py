"""Dorico MCP server: read and write a live Dorico 6 score by conversation.

Positions: every tool takes either `bar` (1-based) + `beat` (offset in crotchets from the bar start, e.g. "0",
"1", "3/2") or an absolute `pos` in crotchets from the flow start. Voices are voice-stream ids from
get_score_overview (e.g. piano: 2 = right hand, 4 = left hand). Event ids come from read_music/read_markings.
Every write is one undo step, verified by reading the score back; a failed check is undone automatically.
"""
# (the docstring above is the MCP instructions) Depends on: analysis, bridge, catalog, model, ops, rc, reads, session, windows.
import asyncio
import functools
import json
import subprocess
from fractions import Fraction

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.utilities.types import Image

from . import analysis, catalog, ops, reads, windows
from .bridge import LuaError
from .model import frac, fstr
from .rc import RCError
from .session import Session

INSTRUCTIONS = __doc__ + """
Start with get_score_overview, then get_bar_map and read_music. Write with add_notes and the add_*/set_* tools.
Use screenshot to look at the result. list_capabilities shows what is confirmed live and what is experimental.
Dorico's API cannot read: lyrics, fp and sffz (sffz reads as sfz), tonic/mode of keys (only the signature),
title/composer; and per-note properties in voices that contain trills, ornaments, arpeggios, techniques or glissandi.
Tempo values are read by selecting the tempo marking; undo skips those selection steps.
Undo works any time; redo only directly after undo (any read clears Dorico's redo stack).
"""

mcp = MCPServer("dorico", instructions=INSTRUCTIONS)
_session: Session | None = None


def S() -> Session:
    global _session
    if _session is None:
        _session = Session()
    return _session


_orphan: tuple[str, asyncio.Task] | None = None  # a call the client cancelled while Dorico was still working on it
_notices: list[str] = []


def _orphan_done(name: str, task: asyncio.Task):
    global _orphan
    _orphan = None
    if task.cancelled():
        return
    e = task.exception()
    _notices.append(f"an earlier {name} call was cancelled by the client while Dorico was working on it; it "
                    + (f"then failed: {str(e).splitlines()[0]}" if e else "then completed, so its change is in the score "
                       "(use undo to revert it)"))


def capability(name: str, image: bool = False, lock: bool = True):
    """Tag a tool with its confirmation status; failures caused by a blocking dialog are reported as such.

    The call runs in its own task, shielded from client cancellation: a cancelled Dorico edit cannot be stopped
    midway, and abandoning it would release the session lock while the edit is still running. It finishes
    (verified, or undone on failure) and the next tool result says how it ended.
    lock=False is for the dialog tools: they never touch Remote Control or Lua, and must work while another call
    is blocked by the very dialog they answer."""
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(*a, **kw):
            global _orphan
            if not lock:
                try:
                    return await fn(*a, **kw)
                except Exception as e:
                    raise ToolError(f"{type(e).__name__}: {e}") from e
            if S().lock._owner is asyncio.current_task():  # a tool calling another tool: already inside the lock
                return await fn(*a, **kw)
            if _orphan:
                raise ToolError(f"Dorico is still finishing an earlier {_orphan[0]} call that the client cancelled; "
                                "retry in a few seconds")

            async def locked():
                async with S().lock:
                    return await fn(*a, **kw)

            task = asyncio.ensure_future(locked())
            try:
                r = await asyncio.shield(task)
            except asyncio.CancelledError:
                if not task.done():
                    _orphan = (name, task)
                    task.add_done_callback(functools.partial(_orphan_done, name))
                raise
            except LuaError as e:
                raise ToolError(str(e).splitlines()[0]) from e
            except Exception as e:  # input errors, failed verifications, refused commands: tell the model why
                raise ToolError(f"{type(e).__name__}: {e}") from e
            st = catalog.status(name)
            if isinstance(r, dict):
                if st not in ("confirmed", "read-only"):
                    r = {**r, "capability_status": st}
                if _notices:
                    r = {**r, "notice": " | ".join(_notices)}
                    _notices.clear()
            return r
        wrapper.__doc__ = (fn.__doc__ or "") + ("" if catalog.status(name) == "confirmed" else
                                                f"\n[{catalog.status(name).upper()}: not yet confirmed by the live harness]")
        return wrapper
    return deco


async def _pos(flow, bar, beat, pos) -> Fraction:
    return await ops.resolve_pos(S(), flow, bar, beat, pos)


# ====================================================================== session & introspection

@mcp.tool()
@capability("dorico_status")
async def dorico_status() -> dict:
    """Live Dorico status (mode, selection, note input, undo availability) from Remote Control."""
    st = await S().rc.status()
    keep = ("hasScore", "activeOpenScoreID", "windowMode", "hasSelection", "selectedEventType", "noteInputActive",
            "insertActive", "canUndo", "canRedo", "inPlayback", "zoomPercent")
    try:
        dialogs = windows.dialogs()
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as e:  # no swiftc / no permission
        dialogs = f"unavailable ({type(e).__name__})"
    return {k: st.get(k) for k in keep if k in st} | {"dialogs_open": dialogs}


@mcp.tool()
@capability("list_capabilities")
async def list_capabilities() -> list[dict]:
    """The confirmation matrix: every capability, its mechanism and whether the live harness confirmed it."""
    return list(catalog.confirmed().values())


@mcp.tool()
@capability("describe_commands")
async def describe_commands(filter: str = "", limit: int = 40) -> list[dict]:
    """Search Dorico's 1,200 commands (regex on name/display name) with their parameters and enum values."""
    return catalog.describe_commands(filter, limit)


@mcp.tool()
@capability("describe_enums")
async def describe_enums(name: str) -> dict:
    """Exact accepted values of a Dorico enum type (or regex over enum type names)."""
    return catalog.describe_enums(name)


@mcp.tool()
@capability("describe_property")
async def describe_property(name: str) -> dict | None:
    """Type, display name and enum values of an event property (e.g. kNoteVelocity, kEventColour)."""
    return catalog.property_info(name)


@mcp.tool()
@capability("list_library")
async def list_library(collection: str, filter: str = "") -> list[dict]:
    """Library entities (ids + names), live from Dorico: kInstrumentCollection, kClefCollection,
    kPlayingTechniqueAppearanceCollection, kOrnamentCollection, kTempoPresetCollection, kParagraphStyleCollection..."""
    try:
        r = await S().rc.request({"message": "getlibraryentities", "collection": collection})
        items = r.get("libraryentities", [])
    except (RCError, OSError, TimeoutError):  # Dorico not reachable: the catalogued dump
        items = catalog.library_dump(collection)
    f = filter.lower()
    return [i for i in items if not f or f in i["entityID"].lower() or f in i.get("name", "").lower()][:200]


@mcp.tool()
@capability("run_command")
async def run_command(command: str, select_event_id: int | None = None, flow: int = 0) -> dict:
    """Escape hatch: run any catalogued Dorico command ("Namespace.Command?Param=value&..."), validated
    against the catalogue. With select_event_id the event is selected first in the same undo step."""
    catalog.validate(command)
    if select_event_id is None:
        r = await S().rc.command(command)
        S().mark_written()
        return {"response": r}
    if command == "Edit.Delete":  # selecting a marking and deleting it does nothing; delete by id instead
        return await ops.delete_events(S(), flow, [select_event_id])
    r = await ops.select_apply(S(), flow, [select_event_id], [command], expect_change=False)
    if not (r["added"] or r["removed"] or r["changed"]):
        r["note"] = ("no visible change on the score's events (changes to dynamics inside a group or to options are "
                     "not visible here; otherwise the command did not apply to this event)")
    return r


@mcp.tool()
@capability("screenshot", image=True)
async def screenshot(bar: int | None = None, zoom: int | None = None, flow: int = 0) -> Image:
    """A picture of Dorico's score window, to check engraving by eye. bar: scroll there first; zoom: view zoom in
    percent for the picture (e.g. 200 to read dynamics and small markings), restored afterwards."""
    rc = S().rc
    before = (await rc.status()).get("zoomPercent")
    if zoom is not None:
        if not 25 <= zoom <= 800:
            raise ops.OpError("zoom: 25 to 800 percent")
        await rc.command(f"View.Zoom?ZoomPercent={zoom}")
    try:
        if bar is not None:
            await rc.command(f"Edit.GoTo?FlowID={flow}&Index={bar}")
        await asyncio.sleep(0.5 if bar is not None or zoom is not None else 0)  # let Dorico redraw
        return Image(data=windows.screenshot(), format="png")
    finally:
        if zoom is not None and before:
            await rc.command(f"View.Zoom?ZoomPercent={before}")


@mcp.tool()
@capability("dialogs", lock=False)
async def list_dialogs() -> dict:
    """Dorico's open dialogs (every window other than a project window): title, modal, the texts shown and the
    controls (role, title or label, value, enabled, path). A modal dialog blocks all commands until it is answered
    with dialog_click / dialog_set. Needs Accessibility permission for the app running this server."""
    return {"dialogs": windows.ax_dialogs()}


@mcp.tool()
@capability("dialogs", lock=False)
async def dialog_click(control: str, dialog: str | None = None) -> dict:
    """Press a control in a Dorico dialog: a button ("OK", "Cancel", "Apply", "Close"), checkbox, radio button or
    tab, by its title, the label before it, or its path from list_dialogs. dialog: its title, if several are open."""
    r = windows.dialog_press(control, dialog)
    await asyncio.sleep(0.4)
    left = windows.ax_dialogs()
    return {**r, "dialog_closed": all(d["title"] != r["dialog"] for d in left), "dialogs": left}


@mcp.tool()
@capability("dialogs", lock=False)
async def dialog_set(control: str, value: str, dialog: str | None = None) -> dict:
    """Set a control in a Dorico dialog: a checkbox or radio button to true/false, a text field to text, a pop-up
    or combo box to one of its items (by name). control: its title, the label before it, or its path."""
    r = windows.dialog_set_value(control, value, dialog)
    await asyncio.sleep(0.3)
    _, c = windows.find_control(windows.ax_dialogs(), r["set"]["path"], r["dialog"])
    return {**r, "now": c}


@mcp.tool()
@capability("refresh")
async def refresh() -> dict:
    """Forget cached reads (time signatures, dynamics, keys, structure); use after editing in Dorico by hand."""
    S().mark_written()
    return {"ok": True}


# ====================================================================== read

@mcp.tool()
@capability("read_overview")
async def get_score_overview() -> dict:
    """Players, instruments, layouts and flows; per flow its streams and voices (voice-stream id -> instrument,
    staff index, voice index). Use the voice ids for read_music/add_notes."""
    return await S().overview()


@mcp.tool()
@capability("read_bar_map")
async def get_bar_map(flow: int = 0, include_keys: bool = False) -> dict:
    """Bar numbers <-> positions, time signatures (read by Dorico's own equality API, cached) and optionally key
    signatures (include_keys: a letter-entry probe into an empty span; it plays 7 audition notes)."""
    return await S().bar_map(flow, keys=include_keys)


async def _range(flow, from_bar, to_bar, from_pos, to_pos) -> tuple[Fraction, Fraction]:
    lo = frac(from_pos) if from_pos is not None else await S().to_pos(flow, from_bar or 1)
    if to_pos is not None:
        return lo, frac(to_pos)
    try:
        return lo, await S().to_pos(flow, (to_bar or from_bar or 1) + 1)
    except ValueError:  # the last bar of an open-meter flow runs on: read to the end of the music
        evs = await S().events(flow)
        end = max((e.end for e in evs if e.type not in ("kBarDivisionEvent", "kTonalityDivisionEvent")), default=lo)
        return lo, max(end, lo + 1)


@mcp.tool()
@capability("read_music")
async def read_music(flow: int = 0, voices: list[int] | None = None, from_bar: int | None = 1, to_bar: int | None = None,
                     from_pos: str | None = None, to_pos: str | None = None, detail: str = "full",
                     grid_step: str | None = None) -> dict:
    """Notes, chords, rests (explicit and implicit), grace notes, tuplets, slurs and articulations per voice,
    with exact positions, durations, spelled pitches, MIDI numbers and event ids. Range: bars (inclusive)
    or positions [from_pos, to_pos).
    detail="compact": per voice and bar the notes in add_notes syntax plus their ids (about a tenth of the size; use it
    for long ranges or many voices). detail="grid": one row per onset of any voice (or every grid_step crotchets,
    e.g. "1/2") with what each voice sounds, for checking verticals."""
    lo, hi = await _range(flow, from_bar, to_bar, from_pos, to_pos)
    return await reads.read_music(S(), flow, voices, lo, hi, detail, frac(grid_step) if grid_step else None)


@mcp.tool()
@capability("read_markings")
async def read_markings(flow: int = 0, from_bar: int | None = 1, to_bar: int | None = None,
                        from_pos: str | None = None, to_pos: str | None = None) -> dict:
    """Dynamics (levels incl. sfz/rfz/fz, hairpins), slurs, clefs, ottavas, text, tempo (text, bpm), holds, rehearsal
    marks, repeats, breaks, playing techniques (name), ornaments, time/key signatures in a range. Each row says whether its content is readable.
    A dynamic group lists its parts in order, each with its own position (bar, beat): a level (p, f...) or a hairpin
    (cresc/dim, length, end); "sub" identifies a hairpin part for set_property."""
    lo, hi = await _range(flow, from_bar, to_bar, from_pos, to_pos)
    return await reads.read_markings(S(), flow, lo, hi)


@mcp.tool()
@capability("read_context")
async def read_context_at(flow: int = 0, voice: int | None = None, bar: int | None = None, beat: str = "0",
                          pos: str | None = None, include_key: bool = False) -> dict:
    """What is in force at a point: time signature, key signature, clef, dynamic level (and a hairpin running
    through the point), ottava, the last tempo marking (text, bpm), and the notes sounding in the voice."""
    return await reads.read_context_at(S(), flow, await _pos(flow, bar, beat, pos), voice, include_key)


@mcp.tool()
@capability("check_voice_leading")
async def check_voice_leading(voices: list[int] | None = None, flow: int = 0, from_bar: int | None = 1,
                              to_bar: int | None = None, chords: str | None = None, key: str | None = None,
                              max_leap: int = 12) -> dict:
    """Voice-leading check of the score: parallel and contrary fifths/octaves/unisons, hidden fifths/octaves in the
    outer voices, crossings, spacing over an octave between upper voices, leaps over max_leap semitones and tritone
    leaps. voices: from highest to lowest (default: ordered by average pitch). chords (optional harmonic plan,
    "bar[:beat] symbol, ...", e.g. "28 D, 28:2 A7, 29 Bm/F#") adds doubled thirds (major chords), doubled sevenths,
    doubled leading tone (needs key, e.g. "D" or "Bm"), missing thirds, non-chord tones and wrong bass notes.
    A voice holding a chord counts by its top note."""
    lo, hi = await _range(flow, from_bar, to_bar, None, None)
    rd = await reads.read_music(S(), flow, voices, lo, hi)
    return analysis.check(rd, voices, chords, key, max_leap)


_snapshots: dict[str, tuple[dict, set]] = {}


@mcp.tool()
@capability("score_changes")
async def score_changes(flow: int = 0, since: str | None = None) -> dict:
    """What changed in a flow: without since, take a snapshot and return its token; with since=<token>, list the
    events added, removed and changed since then, each marked by "server" (written through these tools) or "Dorico"
    (edited in Dorico by hand), and a new token. Changes inside dynamic groups (levels) are not seen."""
    s = S()
    regions, _ = await s.regions(flow)
    now = {e.id: e for e in await s.events(flow)}
    token = f"{flow}:{len(_snapshots) + 1}"
    _snapshots[token] = (now, set(s.written))
    if since is None:
        return {"token": token, "events": len(now)}
    if since not in _snapshots or not since.startswith(f"{flow}:"):
        raise ops.OpError(f"unknown token {since!r} for flow {flow} (tokens live until the server restarts)")
    old, written = _snapshots[since]
    mine = s.written - written

    def row(e):
        return {**ops.brief(e, regions), "by": "server" if (flow, e.id) in mine else "Dorico"}
    changed = [e for i, e in now.items() if i in old and (e.desc != old[i].desc or e.props != old[i].props)]
    return {"token": token, "added": [row(e) for i, e in now.items() if i not in old],
            "removed": [row(e) for i, e in old.items() if i not in now], "changed": [row(e) for e in changed]}


@mcp.tool()
@capability("get_selection")
async def get_selection() -> dict:
    """The current selection in Dorico (event type and, if available, its properties)."""
    st = await S().rc.status()
    pl = S().rc.latest.get("propertieslist")
    return {"hasSelection": st.get("hasSelection"), "selectedEventType": st.get("selectedEventType"),
            "properties": pl.get("properties") if pl and st.get("hasSelection") else None}


@mcp.tool()
@capability("get_options")
async def get_options(kind: str = "kLayout", layout_id: int | None = 0, flow_id: int | None = None, filter: str = "") -> list[dict]:
    """House-style options: kind kEngraving (per score), kNotation (per flow: flow_id), kLayout (per layout: layout_id)."""
    msg = {"message": "getoptions", "optionsType": kind}
    if kind == "kLayout":
        msg["layoutID"] = layout_id or 0
    if kind == "kNotation":
        msg["flowID"] = flow_id or 0
    r = await S().rc.request(msg)
    f = filter.lower()
    return [o for o in r.get("options", []) if not f or f in o["path"].lower()][:300]


# ====================================================================== write: notes

@mcp.tool()
@capability("add_notes")
async def add_notes(notes: str, voice: int, flow: int = 0, bar: int | None = None, beat: str = "0",
                    pos: str | None = None, replace: bool = False) -> dict:
    """Write notes, chords and rests one after another from a position.
    notes: space-separated items "PITCHES:DURATION"; chords join pitches with "+"; "r" is a rest; a missing
    duration repeats the previous one. Durations: crotchets (1, 3/2, 1/2) or w h q e s t (+ dots, e.g. "q.").
    Pitches: C4 = middle C, F#5, Bb3. Example: "Eb4+G4+C5:h. G4:e Eb5:q. C5:s r:q".
    replace=True first clears the notes and rests of the span (slurs, text and other markings there stay);
    otherwise notes are added (chords merge with existing notes)."""
    return await ops.add_notes(S(), flow, voice, notes, bar, beat, pos, replace)


@mcp.tool()
@capability("delete_range")
async def delete_range(voice: int, flow: int = 0, from_bar: int | None = None, to_bar: int | None = None,
                       from_pos: str | None = None, to_pos: str | None = None, include_markings: bool = False) -> dict:
    """Delete the notes, rests, grace notes and tuplets of a voice in a range (bars inclusive, or positions
    [from_pos, to_pos)); slurs, text and other markings in the voice stay unless include_markings=True."""
    lo, hi = await _range(flow, from_bar, to_bar, from_pos, to_pos)
    return await ops.delete_range(S(), flow, voice, lo, hi, include_markings)


@mcp.tool()
@capability("delete_events")
async def delete_events(event_ids: list[int], flow: int = 0) -> dict:
    """Delete events by id: notes, rests or markings (dynamics, hairpins, slurs, text, clefs, octave lines...).
    Ids come from read_music / read_markings."""
    return await ops.delete_events(S(), flow, event_ids)


@mcp.tool()
@capability("set_pitch")
async def set_pitch(event_id: int, pitch: str, flow: int = 0) -> dict:
    """Change one note's pitch and spelling (e.g. "F#4", "Ebb5") in place: it keeps its id, rhythm, slurs and
    articulations."""
    return await ops.set_pitch(S(), flow, event_id, pitch)


@mcp.tool()
@capability("set_duration")
async def set_duration(event_id: int, duration: str, flow: int = 0) -> dict:
    """Change a note's or rest's duration (crotchets or w h q e s t with dots)."""
    return await ops.set_duration(S(), flow, event_id, duration)


@mcp.tool()
@capability("edit_notes")
async def edit_notes(event_ids: list[int], action: str, count: int = 1, flow: int = 0) -> dict:
    """Apply an edit to notes: pitch_up/pitch_down (diatonic steps x count), chromatic_up/down, octave_up/down,
    respell_above/below, double_duration, halve_duration, tie (to the next note of the same pitch), delete;
    remove_rests on rest ids (Dorico's Remove Rests: the voice shows a gap there, e.g. a divisi line that pauses)."""
    return await ops.edit_notes(S(), flow, event_ids, action, count)


@mcp.tool()
@capability("add_chord_interval")
async def add_interval(event_ids: list[int], interval: str, flow: int = 0) -> dict:
    """Add a note at an interval to each given note, making a chord: "3" (third above), "-3", "maj3", "min6 below", "p5", "octave"."""
    return await ops.transpose_notes(S(), flow, event_ids, interval, add=True)


@mcp.tool()
@capability("add_grace_note")
async def add_grace_note(pitch: str, voice: int, flow: int = 0, bar: int | None = None, beat: str = "0",
                         pos: str | None = None, value: str = "e") -> dict:
    """Add a grace note before the note at the given position (value: notated length, default quaver)."""
    return await ops.add_grace_note(S(), flow, voice, pitch, await _pos(flow, bar, beat, pos), value)


@mcp.tool()
@capability("copy_range")
async def copy_range(voice: int, dest_voice: int, flow: int = 0, from_bar: int | None = None, to_bar: int | None = None,
                     from_pos: str | None = None, to_pos: str | None = None, dest_bar: int | None = None,
                     dest_beat: str = "0", dest_pos: str | None = None, move: bool = False) -> dict:
    """Copy (or move) notes and rests of a range to another place or voice/staff (markings are not copied)."""
    lo, hi = await _range(flow, from_bar, to_bar, from_pos, to_pos)
    return await ops.copy_range(S(), flow, voice, lo, hi, dest_voice, await _pos(flow, dest_bar, dest_beat, dest_pos), move)


@mcp.tool()
@capability("add_tuplet")
async def add_tuplet(ratio: str, unit: str, notes: str, voice: int, flow: int = 0, bar: int | None = None,
                     beat: str = "0", pos: str | None = None) -> dict:
    """A tuplet typed with Dorico's note input, overwriting what is there: ratio "3:2", "5:4"; unit = the
    tuplet's note value (e, q, s, h); notes in add_notes syntax with notated values, e.g. "C5:e D5 E5" or
    "Eb4+G4:q B4 D5". Accidentals are always explicit (C#5, Ab4); plain letters mean naturals."""
    return await ops.add_tuplet(S(), flow, voice, await _pos(flow, bar, beat, pos), ratio, unit, notes)


@mcp.tool()
@capability("swap_voices")
async def swap_voices(voice: int, other_voice: int, flow: int = 0, from_bar: int | None = None, to_bar: int | None = None,
                      from_pos: str | None = None, to_pos: str | None = None) -> dict:
    """Exchange the notes and rests of two voices in a range (e.g. divisi lines trading places), one undo step.
    Notes are re-created with their pitch and rhythm (new ids); slurs, text and markings stay in their voice."""
    lo, hi = await _range(flow, from_bar, to_bar, from_pos, to_pos)
    return await ops.swap_voices(S(), flow, voice, other_voice, lo, hi)


@mcp.tool()
@capability("add_voice")
async def add_voice(notes: str, voice: int, flow: int = 0, bar: int | None = None, beat: str = "0",
                    pos: str | None = None) -> dict:
    """Start a new voice on the same staff as `voice` (e.g. a second, stems-down voice), typing `notes`
    (add_notes syntax, plain or single-dotted values). Returns the new voice id for later add_notes calls."""
    return await ops.add_voice(S(), flow, voice, await _pos(flow, bar, beat, pos), notes)


# ====================================================================== write: markings

@mcp.tool()
@capability("add_articulation")
async def add_articulation(event_ids: list[int], kind: str, flow: int = 0) -> dict:
    """staccato, staccatissimo, tenuto, accent, marcato, stress, unstress, staccato_tenuto on notes."""
    return await ops.add_articulation(S(), flow, event_ids, kind)


@mcp.tool()
@capability("add_span")
async def add_span(kind: str, start_event_id: int | None = None, end_event_id: int | None = None,
                   spans: list[list[int]] | None = None, flow: int = 0) -> dict:
    """A line from one note to another in the same voice: slur, cresc, dim, messa_di_voce (hairpins),
    8va, 8vb, 15ma, 15mb (octave lines), glissando. Only that voice gets it, even with other voices on the staff.
    spans: several [start_event_id, end_event_id] pairs in one call (slurs: one undo step), e.g. a slur over every
    pair of quavers. Hairpins end at the end of the end note; for exact positions use add_hairpin."""
    return await ops.add_span(S(), flow, kind, start_event_id, end_event_id, spans)


@mcp.tool()
@capability("add_hairpin")
async def add_hairpin(kind: str, voice: int, to_bar: int | None = None, to_beat: str = "0", to_pos: str | None = None,
                      flow: int = 0, bar: int | None = None, beat: str = "0", pos: str | None = None,
                      voices: list[int] | None = None) -> dict:
    """A hairpin (cresc, dim, messa_di_voce) from one position to another, e.g. bar 33 beat 0 to bar 33 beat 3/2,
    wherever notes start (also inside a held note). voices: put the same hairpin on several instruments (one voice
    each), e.g. the whole string section. A hairpin starting at a dynamic joins its group (p<), reported as
    merged_into. Returns the direction, positions and drawn length."""
    start = await _pos(flow, bar, beat, pos)
    end = await _pos(flow, to_bar, to_beat, to_pos)
    return await ops.add_hairpin(S(), flow, voice, start, end, kind, voices)


@mcp.tool()
@capability("add_dynamic")
async def add_dynamic(value: str, voice: int, flow: int = 0, bar: int | None = None, beat: str = "0",
                      pos: str | None = None, voices: list[int] | None = None, at: list[dict] | None = None) -> dict:
    """An immediate dynamic (p, pp, mp, mf, f, ff, sfz, fp, ...) on the voice's instrument at a position, also
    where no note starts (inside a held note) or where a hairpin ends. voices: the same on several instruments.
    at: more dynamics in the same call, e.g. [{"value": "f", "bar": 34}, {"value": "p", "bar": 36, "beat": "2"}]
    (each takes bar + beat or pos). One undo step; returns only the dynamics created."""
    targets = [(await _pos(flow, bar, beat, pos), value)]
    for d in at or []:
        if not isinstance(d, dict) or "value" not in d:
            raise ops.OpError('each at item needs a value and a position: {"value": "f", "bar": 34, "beat": "0"}')
        targets.append((await _pos(flow, d.get("bar"), str(d.get("beat", "0")), d.get("pos")), d["value"]))
    return await ops.add_dynamic(S(), flow, voices or [voice], targets)


@mcp.tool()
@capability("add_note_marking")
async def add_note_marking(event_ids: list[int], kind: str, value: str = "", flow: int = 0) -> dict:
    """kind=ornament (value tr, mordent, inv, turn), hold (fermata, breath, caesura...),
    playing_technique (value: a name like pizz., arco, con sord., sul pont., ord., or a library id like pta.pizzText),
    tie, articulation (value staccato...)."""
    return await ops.add_note_marking(S(), flow, event_ids, kind, value)


@mcp.tool()
@capability("add_text")
async def add_text(text: str, voice: int, flow: int = 0, bar: int | None = None, beat: str = "0", pos: str | None = None) -> dict:
    """Staff text (e.g. "dolce", "espress.") attached to a voice at a position."""
    return await ops.add_text(S(), flow, voice, await _pos(flow, bar, beat, pos), text)


@mcp.tool()
@capability("add_clef")
async def add_clef(clef: str, voice: int, flow: int = 0, bar: int | None = None, beat: str = "0", pos: str | None = None) -> dict:
    """A clef change on the voice's staff: clef.treble, clef.bass, clef.alto, clef.tenor, clef.treble8ba ..."""
    return await ops.add_clef(S(), flow, voice, await _pos(flow, bar, beat, pos), clef)


@mcp.tool()
@capability("set_tempo")
async def set_tempo(value: str, flow: int = 0, bar: int | None = None, beat: str = "0", pos: str | None = None) -> dict:
    """A tempo marking: "q=120", "Allegro q=132", "h.=60", "rit.", "a tempo"."""
    return await ops.set_tempo(S(), flow, await _pos(flow, bar, beat, pos), value)


@mcp.tool()
@capability("set_time_signature")
async def set_time_signature(value: str, bar: int, flow: int = 0) -> dict:
    """Time signature from a bar on: 3/4, 6/8, 2+3/8, c, cut. Single n/d values are read back to confirm."""
    return await ops.set_time_signature(S(), flow, await S().to_pos(flow, bar), value)


@mcp.tool()
@capability("set_key_signature")
async def set_key_signature(value: str, bar: int, flow: int = 0, beat: str = "0") -> dict:
    """Key signature from a bar on: "2#", "3b", "0", or names like "Eb", "F#m", "c minor"."""
    return await ops.set_key_signature(S(), flow, await S().to_pos(flow, bar, frac(beat)), value)


@mcp.tool()
@capability("add_barline")
async def add_barline(kind: str, bar: int, flow: int = 0) -> dict:
    """Barline at the start of a bar: "||" double, "|:" start repeat, ":|" end repeat, ":|:", "|||" final, ":" dashed."""
    return await ops.add_barline(S(), flow, bar, kind)


@mcp.tool()
@capability("add_repeat_marker")
async def add_repeat_marker(value: str, bar: int, flow: int = 0, beat: str = "0") -> dict:
    """segno, coda, fine, "to coda", "D.C.", "D.C. al Fine", "D.C. al Coda", "D.S. al Fine", "D.S. al Coda"."""
    return await ops.add_repeat_marker(S(), flow, await S().to_pos(flow, bar, frac(beat)), value)


@mcp.tool()
@capability("add_rehearsal_mark")
async def add_rehearsal_mark(bar: int, flow: int = 0) -> dict:
    """A rehearsal mark (next letter in sequence) at the start of a bar."""
    return await ops.add_rehearsal_mark(S(), flow, await S().to_pos(flow, bar))


@mcp.tool()
@capability("add_break")
async def add_break(bar: int, kind: str = "system", flow: int = 0) -> dict:
    """Force a system or frame (page) break before a bar."""
    return await ops.add_break(S(), flow, bar, kind)


@mcp.tool()
@capability("set_property")
async def set_property(event_ids: list[int], name: str, value: str | None = None, flow: int = 0, part: int | None = None) -> dict:
    """Set any event property (all layouts), e.g. kNoteVelocity=100, kEventColour=#ffff0000, kEventScale=kCue,
    kNoteForcedVoiceDirection... Omit value to reset to default. See describe_property.
    kDynamicGradualChangeDuration (hairpin length in crotchets) also works on a hairpin joined to a dynamic (p<);
    part: the hairpin's "sub" from read_markings when its group holds several hairpins (> <)."""
    return await ops.set_property(S(), flow, event_ids, name, value, part)


# ====================================================================== write: options & structure

@mcp.tool()
@capability("set_option")
async def set_option(kind: str, path: str, value: str, layout_ids: list[int] | None = None, flow_ids: list[int] | None = None) -> dict:
    """Set a house-style option (paths and values from get_options). kind: kEngraving, kNotation (flow_ids),
    kLayout (layout_ids). Written via Dorico's own commands (the setoptions message ignores layout ids)."""
    if any(c in path + value for c in '&?"\\'):
        raise ops.OpError("path/value cannot contain & ? \" or \\")
    d = f'Dictionary=list: {{string: "{path}"}}\\, {{string: "{value}"}}'
    if kind == "kLayout":
        cmd = f"Project.Layout.SetOptions?{d}&LayoutIDArray={','.join(map(str, layout_ids or [0]))}"
    elif kind == "kNotation":
        cmd = f"Project.Flow.SetNotationOptions?{d}&FlowIDArray={','.join(map(str, flow_ids or [0]))}"
    elif kind == "kEngraving":
        cmd = f"Engrave.SetEngravingOptions?{d}"
    else:
        raise ops.OpError("kind: kEngraving, kNotation or kLayout")
    await S().rc.command(cmd)
    S().mark_written()
    msg = {"message": "getoptions", "optionsType": kind}
    if kind == "kLayout":
        msg["layoutID"] = (layout_ids or [0])[0]
    if kind == "kNotation":
        msg["flowID"] = (flow_ids or [0])[0]
    now = [o for o in (await S().rc.request(msg)).get("options", []) if o["path"] == path]
    got = now[0].get("currentValue") if now else None
    if got != value:
        raise ops.OpError(f"option {path} reads {got!r} after writing {value!r}")
    return {"path": path, "value": got}


async def _setup_mode_command(cmd: str):
    rc = S().rc
    mode = (await rc.status()).get("windowMode")
    await rc.command("Window.SwitchMode?WindowMode=kSetupMode")
    try:
        await rc.command(cmd)
    finally:
        if mode and mode != "kSetupMode":
            await rc.command(f"Window.SwitchMode?WindowMode={mode}")
    S().mark_written()


@mcp.tool()
@capability("add_player")
async def add_player(instrument: str, section: bool = False) -> dict:
    """Add a solo (or section) player holding an instrument from the library, e.g. instrument.strings.violin,
    instrument.wind.flute (list_library kInstrumentCollection)."""
    if not instrument.startswith("instrument."):
        raise ops.OpError("instrument must be a library id like instrument.strings.violin")
    before = await S().overview()
    pid = len(before["players"])
    await S().rc.command("Project.SectionPlayer.New" if section else "Project.SoloPlayer.New")
    await S().rc.command(f"Project.Instrument.New?PlayerID={pid}&InstrumentEntityID={instrument}")
    S().mark_written()
    after = await S().overview()
    # player ids are assumed dense (creation order); check that exactly the new player got the instrument
    unchanged = after["players"][:pid] == before["players"]
    if len(after["players"]) != pid + 1 or not unchanged or len(after["players"][pid]["instruments"]) != 1:
        raise ops.OpError(f"players changed unexpectedly (check Setup mode and undo if needed): {after['players']}")
    return {"player_id": pid, "players": after["players"], "voices": after["flows"][0]["voices"]}


@mcp.tool()
@capability("add_instrument")
async def add_instrument(player_id: int, instrument: str) -> dict:
    """Give an existing player (index in get_score_overview players) an extra instrument (doubling)."""
    before = await S().overview()
    await S().rc.command(f"Project.Instrument.New?PlayerID={player_id}&InstrumentEntityID={instrument}")
    S().mark_written()
    after = await S().overview()
    if len(after["instruments"]) != len(before["instruments"]) + 1:
        raise ops.OpError("instrument was not added")
    return {"players": after["players"]}


@mcp.tool()
@capability("rename_player")
async def rename_player(player_id: int, name: str, short_name: str | None = None) -> dict:
    """Rename a player (index in get_score_overview players)."""
    if any(c in name + (short_name or "") for c in "&?"):
        raise ops.OpError("names cannot contain & or ?")
    await _setup_mode_command(f"Project.Player.Rename?PlayerID={player_id}&Name={name}" + (f"&ShortName={short_name}" if short_name else ""))
    return {"players": (await S().overview())["players"]}


@mcp.tool()
@capability("add_flow")
async def add_flow() -> dict:
    """Add a new flow (movement) at the end of the project, with all players."""
    before = await S().overview()
    await S().rc.command("Project.Flow.New")
    S().mark_written()
    after = await S().overview()
    if len(after["flows"]) != len(before["flows"]) + 1:
        raise ops.OpError("flow was not added")
    return {"flows": _flows(after)}


def _flows(ov: dict) -> list[dict]:
    return [{"id": f["id"], "name": f.get("name")} for f in ov["flows"]]


async def _answering(coro, text: str, button: str):
    """Await coro while pressing `button` in the modal dialog whose text contains `text` (Dorico's own
    confirmation of an action the caller asked for). Returns the dialog's texts, or None if none appeared."""
    task = asyncio.ensure_future(coro)
    seen = None
    while not task.done():
        await asyncio.sleep(0.25)
        for d in await asyncio.to_thread(windows.ax_dialogs):
            if d["modal"] and any(text in t for t in d["texts"]):
                await asyncio.to_thread(windows.dialog_press, button, d["title"])
                seen = d["texts"]
    await task
    return seen


async def _flow_command(cmd: str, confirm: str | None = None):
    """A flow command in Setup mode. Remote Control refused Project.Flow.Rename and Project.Flows.Delete with
    kCommandNotAllowed (they need a flow selected in Setup's Flows panel, which no command can
    select), so on that refusal the same command is sent from a script's doCommand. Callers verify the effect.
    confirm: text of Dorico's confirmation dialog for this command, answered with OK (the caller asked for it)."""
    rc = S().rc
    mode = (await rc.status()).get("windowMode")
    await rc.command("Window.SwitchMode?WindowMode=kSetupMode")
    async def send():
        try:
            await rc.command(cmd)
        except RCError as e:
            if "kCommandNotAllowed" not in str(e):
                raise
            # a script's doCommand is not refused (Flows.Delete then asks for confirmation)
            await S().bridge.run("tx", flow=(await S().overview())["flows"][0]["id"], steps=[["cmd", cmd]])

    try:
        await (_answering(send(), confirm, "OK") if confirm else send())
    except Exception as e:
        if d := windows.dialogs():
            raise ops.OpError(f"{cmd} opened a dialog in Dorico ({d[0]['w']}x{d[0]['h']} '{d[0]['name']}'); "
                              "answer it with list_dialogs + dialog_click, then check get_score_overview") from e
        raise
    finally:
        if mode and mode != "kSetupMode":
            await rc.command(f"Window.SwitchMode?WindowMode={mode}")
        S().mark_written()


NOT_ALLOWED = ("Dorico only allows this with the flow selected in Setup mode's Flows panel, which its interfaces "
               "cannot select; do it in Dorico (Setup mode, select the flow card)")


@mcp.tool()
@capability("rename_flow")
async def rename_flow(flow_id: int, name: str) -> dict:
    """Rename a flow (ids from get_score_overview flows)."""
    if not name or any(c in name for c in "&?"):
        raise ops.OpError("flow names must be non-empty and cannot contain & or ?")
    await S().flow_info(flow_id)
    await _flow_command(f"Project.Flow.Rename?FlowID={flow_id}&Name={name}")
    flows = _flows(await S().overview())
    got = next(f["name"] for f in flows if f["id"] == flow_id)
    if got != name:
        raise ops.OpError(f"flow {flow_id} is still named {got!r}: {NOT_ALLOWED}, then rename it")
    return {"flows": flows}


@mcp.tool()
@capability("delete_flow")
async def delete_flow(flow_id: int) -> dict:
    """Delete a flow and all its music (one undo step; undo restores it). Dorico's "all music ... will also be
    deleted" confirmation is answered OK. The last flow cannot be deleted."""
    before = await S().overview()
    if flow_id not in {f["id"] for f in before["flows"]}:
        raise ops.OpError(f"no flow {flow_id}; flows: {_flows(before)}")
    if len(before["flows"]) == 1:
        raise ops.OpError("a project needs at least one flow")
    await _flow_command(f"Project.Flows.Delete?FlowIDArray={flow_id}", confirm="If you delete a flow")
    after = await S().overview()
    if flow_id in {f["id"] for f in after["flows"]} or len(after["flows"]) != len(before["flows"]) - 1:
        raise ops.OpError(f"flow {flow_id} was not deleted: {NOT_ALLOWED} and press Delete")
    return {"flows": _flows(after)}


async def _layouts() -> list[dict]:
    return (await S().rc.request({"message": "getlayouts"})).get("layouts", [])


@mcp.tool()
@capability("layouts")
async def add_layout(name: str | None = None) -> dict:
    """Add a custom score layout (optionally named). Part layouts are created automatically with players."""
    before = {lay["layoutID"] for lay in await _layouts()}
    await S().rc.command("Project.Layout.New?Type=kCustomScoreLayout")
    new = [lay for lay in await _layouts() if lay["layoutID"] not in before]
    if not new:
        raise ops.OpError("layout was not created")
    if name:
        await rename_layout(new[0]["layoutID"], name)
    S().mark_written()
    return {"layouts": await _layouts()}


@mcp.tool()
@capability("layouts")
async def rename_layout(layout_id: int, name: str) -> dict:
    """Rename a layout (ids from get_score_overview layouts)."""
    if any(c in name for c in "&?"):
        raise ops.OpError("names cannot contain & or ?")
    await _setup_mode_command(f"Project.Layout.Rename?LayoutID={layout_id}&Name={name}")
    got = {lay["layoutID"]: lay["layoutName"] for lay in await _layouts()}
    if got.get(layout_id) != name:
        raise ops.OpError(f"layout {layout_id} is named {got.get(layout_id)!r}")
    return {"layouts": await _layouts()}


@mcp.tool()
@capability("layouts")
async def layout_flows(layout_id: int, flow_ids: list[int], include: bool = True) -> dict:
    """Include or exclude flows in a layout (Dorico does not expose a layout's flows for read-back)."""
    verb = "IncludeFlows" if include else "ExcludeFlows"
    await _setup_mode_command(f"Project.Layouts.{verb}?LayoutIDArray={layout_id}&FlowIDArray={','.join(map(str, flow_ids))}")
    return {"ok": True, "verified": False}


@mcp.tool()
@capability("set_score_order")
async def set_score_order(order: str) -> dict:
    """Instrument order template, e.g. instrumentscoreorder.orchestral, instrumentscoreorder.windband,
    instrumentscoreorder.choral (list_library kInstrumentScoreOrderCollection)."""
    await S().rc.command(f"Project.SetInstrumentScoreOrder?InstrumentScoreOrderEntityID={order}")
    S().mark_written()
    return {"players": (await S().overview())["players"]}


# ====================================================================== navigation, playback, history

@mcp.tool()
@capability("go_to")
async def go_to(bar: int, flow: int = 0) -> dict:
    """Scroll Dorico's view to a bar."""
    await S().rc.command(f"Edit.GoTo?FlowID={flow}&Index={bar}")
    return {"ok": True}


@mcp.tool()
@capability("select_events")
async def select_events(event_ids: list[int], flow: int = 0) -> dict:
    """Select an event in Dorico (e.g. to show the user). Note: selection changes are undo steps in Dorico."""
    evs = await ops._events_by_id(S(), flow, event_ids[:1])
    e = evs[event_ids[0]]
    await S().bridge.run("tx", flow=flow, steps=[["select", e.stream, e.id]])
    return {"selected": event_ids[0], "status": {k: (await S().rc.status()).get(k) for k in ("hasSelection", "selectedEventType")}}


@mcp.tool()
@capability("playback")
async def play(from_bar: int | None = None, flow: int = 0) -> dict:
    """Start playback (from a bar, or from the playhead)."""
    if from_bar is not None:
        p = await S().to_pos(flow, from_bar)
        await S().rc.command(f"Play.MovePlayheadToFlowPosition?FlowID={flow}&RhythmicPosition={fstr(p)}\\,")
    await S().rc.command("Play.StartOrStop?PlayFromLocation=kPlayhead")
    return {"playing": (await S().rc.status()).get("inPlayback")}


@mcp.tool()
@capability("playback")
async def stop() -> dict:
    """Stop playback."""
    await S().rc.command("Play.Stop")
    return {"playing": (await S().rc.status()).get("inPlayback")}


@mcp.tool()
@capability("undo")
async def undo(count: int = 1) -> dict:
    """Undo the last `count` edits in Dorico (every tool write is one step). Selection steps left by this server's
    tempo reads are skipped; other selection changes (by hand, select_events) count as steps."""
    steps = await S().undo(count)
    return {"dorico_steps": steps, "canUndo": (await S().rc.status()).get("canUndo")}


@mcp.tool()
@capability("undo")
async def redo(count: int = 1) -> dict:
    """Redo `count` steps. Only possible right after undo: every MCP read runs a Dorico script, and any
    script clears Dorico's redo stack (verified)."""
    await S().rc.redo(count)
    S().mark_written()
    return {"ok": True}


# ====================================================================== resources

@mcp.resource("dorico://status")
async def status_resource() -> str:
    return json.dumps(await dorico_status())


@mcp.resource("dorico://score")
async def score_resource() -> str:
    s = S()
    ov = await s.overview()
    out = {"overview": ov, "flows": []}
    for f in ov["flows"]:
        bm = await s.bar_map(f["id"])
        hi = await s.to_pos(f["id"], bm["last_bar_with_music"] + 1)
        out["flows"].append({"bar_map": bm, "music": await reads.read_music(s, f["id"], None, Fraction(0), hi),
                             "markings": await reads.read_markings(s, f["id"], Fraction(0), hi)})
    return json.dumps(out)


def main():
    mcp.run("stdio")


def _self_check():
    async def main():
        @capability("selfcheck_slow")
        async def slow():
            await asyncio.sleep(0.3)
            return {"ok": True}

        @capability("selfcheck_fast")
        async def fast():
            return {"ok": True}

        t = asyncio.ensure_future(slow())
        await asyncio.sleep(0.05)
        t.cancel()  # what the MCP SDK does on notifications/cancelled
        await asyncio.gather(t, return_exceptions=True)
        try:
            await fast()
            raise AssertionError("a call while the cancelled edit runs must be refused")
        except ToolError as e:
            assert "still finishing" in str(e)
        await asyncio.sleep(0.4)
        r = await fast()
        assert "completed" in r["notice"] and "notice" not in await fast(), r

        @capability("selfcheck_outer")
        async def outer():
            return await fast()  # like add_layout calling rename_layout
        assert (await asyncio.wait_for(outer(), 2))["ok"]
    asyncio.run(main())
    print("server self-check ok: a cancelled call finishes under the lock and is reported")


if __name__ == "__main__":
    import sys
    _self_check() if sys.argv[1:] == ["selfcheck"] else main()
