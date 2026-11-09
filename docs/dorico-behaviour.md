# Measured Dorico behaviour

The server depends on these; each was measured on Dorico 6.2.30 and should be re-measured after a Dorico update.

- Time signatures and dynamic levels are sealed values; they are read with Dorico's own `Variant.__eq` against candidates built by Dorico, then the candidates are removed with one `Edit.Undo` and the element counts are checked.
- Key signatures are read by entering the letters A-G into an empty span and reading Dorico's spelling back (then deleting them); the tonic and mode are not recoverable, only the signature.
- Tempo events cannot be wrapped by Lua at all, but selecting one and sending Remote Control `getproperties` returns its text, microseconds per beat and percentages (not the beat unit).
- The stream dump names a playing technique's library entry (`pta.pizzText`), so techniques are readable by name.
- A dynamic sub-element's `kDynamicForceType` (0 fz, 1 rf(z), 2 sf(z), 3 mfz) and `kDynamicRinforzandoAndSforzandoHaveZ` are plain properties.
- Dorico has no div./unis. playing technique (divisi is a staff change through a dialog), so those stay staff text; arco, pizz. and the other techniques are `add_note_marking playing_technique` (which makes the voice dump-only, see below).
- A voice that contains a trill, ornament, arpeggio, playing technique, glissando or tempo event cannot be enumerated from Lua; its notes and rhythms still come from the stream dump, but per-note properties (articulations, ties) are not readable there.
- Any script, even a read, clears Dorico's redo stack, so `redo` only works directly after `undo`.
- Barlines are bar divisions that carry the current time signature; the bar map lists them separately from real signature changes.
- Lua `pitchWithSpelling` assignment and `copyRange`/`moveRange` are silent no-ops.
  `set_pitch` moves the note one semitone at a time with `NoteEdit.PitchUpChromatic`/`PitchDownChromatic` and then respells it, reading the spelling back after each command, so the note keeps its id.
  `NoteEdit.PitchDownChromatic?count=2` moved C5 up to D5, so the `count` parameter is not used.
  `copy_range` re-creates notes and rests (markings are not copied, and a range with tuplets is refused).
- Note input is slow (each typed pitch is auditioned, up to 0.3 s) and its chord mode is a hidden toggle, so `add_voice` types only the first item and writes the rest like `add_notes` (two undo steps), and stacked or split chords are detected and retried once with the toggle flipped.
- A hairpin that starts where a dynamic already is joins it in one dynamic group (e.g. `p<`): no new event, a new sub-element in the group's element.
  So does a dynamic placed where a hairpin ends, and a dynamic placed where one already is replaces it.
  Sub-element ids are indexes in the group (a dynamic put before a hairpin renumbers it), so new parts are found by position and kind, not by id.
  Each sub-element's `kDynamicPosition` is its offset from the group's start, which is how `read_markings` gives every part its own bar and beat.
  Dorico draws a hairpin's length (`kDynamicGradualChangeDuration`) from the gradual sub-element of its group, also for a hairpin on its own; the event's property of the same name is not drawn, so lengths are set on the sub-element through Lua and read back from the element table.
- `EventEdit.Select` always selects exactly one event: `AddToSelection=1` and `BlockSelection=1` are accepted but ignored.
  Extending the selection (`NavigateRightExtend`) steps through the onsets of every voice on the staff and selects all of them, and `SlurStart` then gives each voice its own slur.
  So `add_span` counts the staff's onsets and deletes the slurs the other voices got, in the same script; slurs cannot be entered from note input.
- In note input the caret starts at the selected note; `NoteInput.MoveRight` moves it by the rhythmic grid (`SetGridResolution`), `MoveAdvance` jumps to the next item.
  `add_dynamic` and `add_hairpin` use that where every voice holds a note through the position (positions must lie on a demisemiquaver grid).
- Deleting a note deletes the slur on it, and `deleteEventsInRange` takes text and other markings too; `add_notes(replace=True)` deletes notes and rests one by one, keeps the rest, and puts the span's slurs back on the new notes.
- Typing a rest first after `NoteInput.CreateVoice` creates no voice, so `add_voice` types its first note and writes leading rests afterwards.
- Selecting a marking and running `Edit.Delete` deletes nothing; `delete_events` uses `EventEdit.Delete` with the event's own block, and `run_command Edit.Delete` with `select_event_id` is routed to it.
- `NoteInput.SetArticulation` toggles the articulation on the whole chord, so `add_articulation` applies it once per chord and skips chords that already have it.
- Remote Control refuses `Project.Flow.Rename` and `Project.Flows.Delete` (`kCommandNotAllowed`, even in Setup mode: they need a flow selected in the Flows panel), but the same commands sent from a script's `doCommand` work; `delete_flow` answers Dorico's "all music ... will also be deleted" confirmation with OK through Accessibility, and both read the flows back.
- A flow without a time signature is in open meter: it is bar 1 up to its first time signature (or barline), so reads work and `set_time_signature` can address bar 1.
