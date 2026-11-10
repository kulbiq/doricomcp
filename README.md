<p align="center">
  <img src="https://raw.githubusercontent.com/mka142/doricomcp/main/icon.png" width="128" height="128" alt="doricomcp icon: a bold letter D with a connector in its counter">
</p>

# doricomcp

[![PyPI](https://img.shields.io/pypi/v/doricomcp)](https://pypi.org/project/doricomcp/)
[![Release](https://img.shields.io/github/v/release/mka142/doricomcp)](https://github.com/mka142/doricomcp/releases/latest)
[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-io.github.mka142%2Fdoricomcp-blue)](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.mka142/doricomcp)
[![CI](https://github.com/mka142/doricomcp/actions/workflows/ci.yml/badge.svg)](https://github.com/mka142/doricomcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](https://github.com/mka142/doricomcp/blob/main/LICENSE)

Talk to your Dorico score.
doricomcp connects Claude to a live Dorico 6 project, so you can ask about the music and have it edited for you:

- "What is in bars 12-20 of the violas?"
- "Add a crescendo from bar 40 beat 2 to the downbeat of 42 in all strings."
- "Put pizz. on the cellos in bar 33 and arco in bar 37."
- "Double the violin line an octave lower in the violas."
- "Check the voice leading in bars 20-28 against this chord plan."

Every edit appears in Dorico as one ordinary undo step, and it is read back and checked; if the check fails, the edit is undone at once.
doricomcp uses only Dorico's own interfaces (Remote Control and its built-in Lua scripting): it does not modify Dorico or your files.

> Not affiliated with or endorsed by Steinberg.
> Dorico is a trademark of Steinberg Media Technologies GmbH.
> Status: alpha, tested on Dorico 6.2.30 on macOS.
> Save your work before a session.

<!-- mcp-name: io.github.mka142/doricomcp -->

## Install

You need a Mac with Dorico 6.2 or later and [Claude Desktop](https://claude.ai/download) or Claude Code.

1. **Turn on Remote Control in Dorico.**
   In Dorico's Preferences, enable Remote Control and keep the port at 4560.
2. **Add doricomcp to Claude**, one of:
   - **Claude Desktop:** download `doricomcp.mcpb` from the [latest release](https://github.com/mka142/doricomcp/releases/latest) and double-click it, then click Install.
     Claude sets up Python by itself.
   - **Claude Code:** install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run `claude mcp add doricomcp -- uvx doricomcp`.
   - **Any other MCP client:** install [uv](https://docs.astral.sh/uv/getting-started/installation/) and add this server to the client's configuration:

     ```json
     {
       "mcpServers": {
         "doricomcp": { "command": "uvx", "args": ["doricomcp"] }
       }
     }
     ```

     If the client cannot find `uvx`, use its full path (`which uvx` in Terminal; usually `/opt/homebrew/bin/uvx` or `~/.local/bin/uvx`).
3. **Open a score in Dorico and ask Claude something about it.**
   The first time, Dorico asks whether to allow the client `doricomcp`: click Allow.
   You will not be asked again.
4. Optional: to let Claude look at the score (`screenshot`) and answer Dorico's dialogs, allow Screen Recording and Accessibility for Claude in System Settings > Privacy & Security.
   Both need the Xcode Command Line Tools (`xcode-select --install`).

### Troubleshooting

- **"Dorico is not reachable":** Dorico is not running, or Remote Control is off or on another port.
- **Dorico never shows the approval prompt:** delete `~/.doricomcp/session_token` and ask again.
- **Some tools are switched off in Claude Desktop:** Claude Desktop remembers switched-off tools per server name; switch them on in the server's settings.
- Anything else: [open an issue](https://github.com/mka142/doricomcp/issues) with what you asked and what happened.

## How to talk about the music

Claude handles these details for you; they matter when you read the tool results.

- Positions are a bar (1-based) and a beat, counted in crotchets from the start of the bar (`0`, `1`, `3/2`), or a position in crotchets from the start of the flow.
- Voices are numbered per score (piano: 2 = right hand, 4 = left hand); `get_score_overview` lists them with their instrument, staff and voice.
- Notes are written like `"Eb4+G4+C5:h. G4:e Eb5:q. C5:s r:q"`: C4 is middle C, durations are note values `w h q e s t` with dots, or crotchets (`3/2`).
- Quarter-tones (in a score whose tonality system is 24-EDO, set in Dorico's Key Signatures panel) are spelled as Dorico spells them: the alteration as a fraction of an octave between the letter and the octave.
  `A1/244` is A4 a quarter-tone sharp, `C-1/245` is C5 a quarter-tone flat, `D1/85` is D5 three quarter-tones sharp (3/24 = 1/8).
- Dynamics, tempo, time signatures, clefs, ornaments and holds take the same text as Dorico's popovers (`p<f`, `pp<ff>pp`, `rit.`, `[2+2+3]/8`).
  The [popover guide](https://github.com/mka142/doricomcp/blob/main/docs/popovers.md) lists every entry and what Dorico 6.2 actually creates for the undocumented ones.
- Playing techniques are given by name (`pizz.`, `con sord.`), including ones you added to the score yourself.

## What it can do

"Confirmed live" means the test harness ran the tool on a real Dorico and read the result back.

<!-- tools:start -->
**Session & introspection**

| Tool | What it does | Status |
|---|---|---|
| `dorico_status` | Live Dorico status (mode, selection, note input, undo availability) from Remote Control. | read-only |
| `list_capabilities` | The confirmation matrix: every capability, its mechanism and whether the live harness confirmed it. | read-only |
| `describe_commands` | Search Dorico's 1,200 commands (regex on name/display name) with their parameters and enum values. | read-only |
| `describe_enums` | Exact accepted values of a Dorico enum type (or regex over enum type names). | read-only |
| `describe_property` | Type, display name and enum values of an event property (e.g. kNoteVelocity, kEventColour). | read-only |
| `list_library` | Library entities (ids + names), live from Dorico: kInstrumentCollection, kClefCollection, kPlayingTechniqueAppearanceCollection ... | read-only |
| `run_command` | Escape hatch: run any catalogued Dorico command ("Namespace.Command?Param=value&..."), validated against the catalogue. | confirmed live |
| `screenshot` | A picture of Dorico's score window, to check engraving by eye. | confirmed live |
| `list_dialogs` | Dorico's open dialogs (every window other than a project window): title, modal, the texts shown and the controls (role, title or label ... | confirmed live |
| `dialog_click` | Press a control in a Dorico dialog: a button ("OK", "Cancel", "Apply", "Close"), checkbox, radio button or tab, by its title, the label ... | confirmed live |
| `dialog_set` | Set a control in a Dorico dialog: a checkbox or radio button to true/false, a text field to text, a pop-up or combo box to one of its items ... | confirmed live |
| `refresh` | Forget cached reads (time signatures, dynamics, keys, structure); use after editing in Dorico by hand. | read-only |

**Read**

| Tool | What it does | Status |
|---|---|---|
| `get_score_overview` | Players, instruments, layouts and flows; per flow its streams and voices (voice-stream id -> instrument, staff index, voice index). | confirmed live |
| `get_bar_map` | Bar numbers <-> positions, time signatures (read by Dorico's own equality API, cached) and optionally key signatures (include_keys: a ... | confirmed live |
| `read_music` | Notes, chords, rests (explicit and implicit), grace notes, tuplets, slurs and articulations per voice, with exact positions, durations ... | confirmed live |
| `read_markings` | Dynamics (levels incl. sfz/rfz/fz, hairpins), slurs, clefs, ottavas, text, tempo (text, bpm), holds, rehearsal marks, repeats, breaks ... | confirmed live |
| `read_context_at` | What is in force at a point: time signature, key signature, clef, dynamic level (and a hairpin running through the point), ottava, the last ... | confirmed live |
| `check_voice_leading` | Voice-leading check of the score: parallel and contrary fifths/octaves/unisons, hidden fifths/octaves in the outer voices, crossings ... | confirmed live |
| `score_changes` | What changed in a flow: without since, take a snapshot and return its token; with since=<token>, list the events added, removed and changed ... | confirmed live |
| `get_selection` | The current selection in Dorico (event type and, if available, its properties). | read-only |
| `get_options` | House-style options: kind kEngraving (per score), kNotation (per flow: flow_id), kLayout (per layout: layout_id). | read-only |

**Write: notes**

| Tool | What it does | Status |
|---|---|---|
| `add_notes` | Write notes, chords and rests one after another from a position. | confirmed live |
| `delete_range` | Delete the notes, rests, grace notes and tuplets of a voice in a range (bars inclusive, or positions [from_pos, to_pos)); slurs, text and ... | confirmed live |
| `delete_events` | Delete events by id: notes, rests or markings (dynamics, hairpins, slurs, text, clefs, octave lines...). | confirmed live |
| `set_pitch` | Change one note's pitch and spelling (e.g. "F#4", "Ebb5") in place: it keeps its id, rhythm, slurs and articulations. | confirmed live |
| `set_duration` | Change a note's or rest's duration (crotchets or w h q e s t with dots). | confirmed live |
| `edit_notes` | Apply an edit to notes: pitch_up/pitch_down (diatonic steps x count), chromatic_up/down, octave_up/down, respell_above/below ... | confirmed live |
| `add_interval` | Add a note at an interval to each given note, making a chord: "3" (third above), "-3", "maj3", "min6 below", "p5", "octave". | confirmed live |
| `add_grace_note` | Add a grace note before the note at the given position (value: notated length, default quaver). | confirmed live |
| `copy_range` | Copy (or move) notes and rests of a range to another place or voice/staff (markings are not copied). | confirmed live |
| `add_tuplet` | A tuplet typed with Dorico's note input, overwriting what is there: ratio "3:2", "5:4"; unit = the tuplet's note value (e, q, s, h); notes ... | confirmed live |
| `swap_voices` | Exchange the notes and rests of two voices in a range (e.g. divisi lines trading places), one undo step. | confirmed live |
| `add_voice` | Start a new voice on the same staff as `voice` (e.g. a second, stems-down voice), typing `notes` (add_notes syntax, plain or single-dotted ... | confirmed live |

**Write: markings**

| Tool | What it does | Status |
|---|---|---|
| `add_articulation` | staccato, staccatissimo, tenuto, accent, marcato, stress, unstress, staccato_tenuto on notes. | confirmed live |
| `add_span` | A line from one note to another in the same voice: slur, cresc, dim, messa_di_voce (hairpins), 8va, 8vb, 15ma, 15mb (octave lines) ... | confirmed live |
| `add_hairpin` | A hairpin (cresc, dim, messa_di_voce) from one position to another, e.g. bar 33 beat 0 to bar 33 beat 3/2, wherever notes start (also ... | confirmed live |
| `add_dynamic` | An immediate dynamic (p, pp, mp, mf, f, ff, sfz, fp, ...) on the voice's instrument at a position, also where no note starts (inside a held ... | confirmed live |
| `add_note_marking` | kind=ornament (value tr, mordent, inv, turn), hold (fermata, breath, caesura...), playing_technique (value: a name like pizz., arco, con ... | confirmed live |
| `add_text` | Staff text (e.g. "dolce", "espress.") attached to a voice at a position. | confirmed live |
| `add_clef` | A clef change on the voice's staff: clef.treble, clef.bass, clef.alto, clef.tenor, clef.treble8ba . | confirmed live |
| `set_tempo` | A tempo marking: "q=120", "Allegro q=132", "h.=60", "rit.", "a tempo". | confirmed live |
| `set_time_signature` | Time signature from a bar on: 3/4, 6/8, 2+3/8, c, cut. | confirmed live |
| `set_key_signature` | Key signature from a bar on: "2#", "3b", "0", or names like "Eb", "F#m", "c minor". | confirmed live |
| `add_barline` | Barline at the start of a bar: "\|\|" double, "\|:" start repeat, ":\|" end repeat, ":\|:", "\|\|\|" final, ":" dashed. | confirmed live |
| `add_repeat_marker` | segno, coda, fine, "to coda", "D.C.", "D.C. | confirmed live |
| `add_rehearsal_mark` | A rehearsal mark (next letter in sequence) at the start of a bar. | confirmed live |
| `add_break` | Force a system or frame (page) break before a bar. | confirmed live |
| `set_property` | Set any event property (all layouts), e.g. kNoteVelocity=100, kEventColour=#ffff0000, kEventScale=kCue, kNoteForcedVoiceDirection. | confirmed live |

**Write: options & structure**

| Tool | What it does | Status |
|---|---|---|
| `set_option` | Set a house-style option (paths and values from get_options). | confirmed live |
| `add_player` | Add a solo (or section) player holding an instrument from the library, e.g. instrument.strings.violin, instrument.wind.flute (list_library ... | confirmed live |
| `add_instrument` | Give an existing player (index in get_score_overview players) an extra instrument (doubling). | confirmed live |
| `rename_player` | Rename a player (index in get_score_overview players). | confirmed live |
| `add_flow` | Add a new flow (movement) at the end of the project, with all players. | confirmed live |
| `rename_flow` | Rename a flow (ids from get_score_overview flows). | confirmed live |
| `delete_flow` | Delete a flow and all its music (one undo step; undo restores it). | confirmed live |
| `remove_instrument` | Remove an instrument and all its music (one undo step; undo restores it). | confirmed live |
| `add_layout` | Add a custom score layout (optionally named). | confirmed live |
| `rename_layout` | Rename a layout (ids from get_score_overview layouts). | confirmed live |
| `layout_flows` | Include or exclude flows in a layout (Dorico does not expose a layout's flows for read-back). | confirmed live |
| `set_score_order` | Instrument order template, e.g. instrumentscoreorder.orchestral, instrumentscoreorder.windband, instrumentscoreorder.choral (list_library ... | confirmed live |

**Navigation, playback, history**

| Tool | What it does | Status |
|---|---|---|
| `go_to` | Scroll Dorico's view to a bar. | confirmed live |
| `select_events` | Select an event in Dorico (e.g. to show the user). | confirmed live |
| `play` | Start playback (from a bar, or from the playhead). | confirmed live |
| `stop` | Stop playback. | confirmed live |
| `undo` | Undo the last `count` edits in Dorico (every tool write is one step). | confirmed live |
| `redo` | Redo `count` steps. | confirmed live |
<!-- tools:end -->

## Known gaps and how they could be closed

What follows is what Dorico's interfaces do not give yet, measured on 6.2.30, with the most promising way in.
Each one is a good first contribution.

- **Lyrics** (`read_markings`, no write tool).
  Lyric text is not readable and `NoteInput.StartLyricInput` plus `AcceptCurrentLyricInput?LyricText=` from a script created no lyric.
  Next: send the same two commands from Remote Control (not Lua) with the note selected, and try the `EventCreationLocation` parameter; then read the lyric back with the selection read used for tempo.
- **Tempo beat unit** (`read_markings`, `read_context_at`).
  Text, bpm, relative and final percentages are read by selecting the tempo marking, but the beat unit is never exposed, so `h.=60` and `q=60` both read 60.
  Next: record the definition when `set_tempo` writes it (as `add_voice` records staves), and compare against Dorico's playback tempo for markings made by hand.
- **fp and sffz** (`read_markings`).
  sfz, sf, rfz, rf, fz and mfz are read from the dynamic's force type; fp leaves no readable property and sffz reads as sfz.
  Next: extend the sealed-value equality probe that reads p/f levels to Dorico-built fp and sffz candidates.
- **Note details in voices with techniques, trills, ornaments, arpeggios or glissandi** (`read_music`).
  Lua cannot list events in such a voice, so pitches and rhythms come from the stream dump, but articulations and ties do not.
  Measured route: in one script, delete the voice's technique, trill or ornament events, read the notes with all their properties, then undo at once; the voice dump came back identical.
  For a single note, Remote Control's `status` message carries the selected note's articulation flags (`articulationStaccato`, ...).
- **div. and unis.** (`add_text`).
  They are written as staff text; Dorico's real divisi is `Edit.AddDivisi` / `Edit.RestoreUnison`, which open the Change Divisi dialog.
  Next: drive that dialog with the existing dialog tools, as `delete_flow` does with its confirmation.
- **Tonality system** (24-EDO and others).
  Quarter-tones are read and written, but switching a score to 24-EDO is only in Dorico's Key Signatures panel: the keys popover rejects a tonality system in its text, and `CreateKeySignature` ignores a `tonalitySystemID` parameter.
  Next: look for the panel's command in Remote Control's command list after choosing a system there by hand.
- **Deleting players** (`remove_instrument` removes instruments).
  `Project.Players.Delete` needs a player selected in Setup mode, and `Project.Players.DeleteEmpty` opens a dialog listing every player without music, not just one.
  Next: select the one player in that dialog with `dialog_set` before pressing Delete Selected Players.
- **Copy and move with markings** (`copy_range`).
  Lua's `copyRange` is a no-op, so notes and rests are re-created and markings are not copied.
  Next: re-create slurs, dynamics and articulations from the twin, as `add_notes(replace=True)` already does for slurs.
- **Key tonic and mode** (`get_bar_map`).
  Only the signature (e.g. 2 sharps) is recoverable.
  Next: infer major/minor from the music with `check_voice_leading`'s chord logic and present it as a guess.
- **Title and composer** (`get_score_overview`).
  Not in Lua or Remote Control.
  No route known through Dorico's own interfaces.
- **Staff of a voice** (`get_score_overview`).
  Dorico does not say which staff a voice is on; the server knows the first voice per staff and the voices it created, and says "unknown" otherwise.
- **Redo after a read** (`redo`).
  Any script, even a read, clears Dorico's redo stack, so redo works only directly after undo.

## How writes stay safe

- Every write is one Lua transaction, which Dorico records as one undo step.
- The tool reads the affected range back and checks the expected result; on a mismatch it undoes the step immediately and confirms the range is restored.
- A script is never abandoned: Dorico runs Remote Control commands in between a script's own commands, so a read or undo sent while a script still runs would land in the middle of it.
  The bridge waits for the script's done marker however long it takes; it stops early only for a modal dialog, and then nothing is undone.
- A tool call the client cancels still runs to the end under the session lock (verified, or undone on failure), and the next tool result reports how it ended.
- Commands that act on "the selection" always get a real selection first (an event at the position, or a temporary rest deleted in the same step), because a selection-less popover command can open a modal dialog that blocks Dorico.
- Reading a tempo selects it, and Dorico records every selection as an undo step; the server counts the selection steps its reads leave on top and `undo` skips them.

## Contributing

Bug reports, measurements on other Dorico versions and pull requests are welcome.
[CONTRIBUTING.md](https://github.com/mka142/doricomcp/blob/main/CONTRIBUTING.md) explains the layout, the checks and how to run the live test harness.
What Dorico does and does not allow through its interfaces is recorded in [docs/dorico-behaviour.md](https://github.com/mka142/doricomcp/blob/main/docs/dorico-behaviour.md).

## Roadmap

- Close the gaps listed above, starting with lyrics and note details in technique voices.
- Windows support: the Remote Control and Lua parts are portable; screenshots and dialogs need a Windows counterpart of `windows.py`.
- Milestone: a project website on GitHub Pages with setup, a demo video and the tool reference.

## License

MIT, see [LICENSE](https://github.com/mka142/doricomcp/blob/main/LICENSE).
