# Dorico Pro 6 Write-mode popover entry reference

doricomcp sends popover text unchanged through Dorico's commands (`NoteInput.CreateDynamic?Definition=<text>`, `CreateTempo`, `CreateTimeSignature`, `CreateKeySignature`, `CreateClef`, `CreateOrnament`, `CreatePause`, `CreateBarLine`), so what works in a popover works in the tools.
Playing techniques are the exception: the command takes a library id, and the server matches the text against the score's live library (including techniques the user added).
The section "Measured live" at the end records what Dorico 6.2.30 actually created for entries the manual does not document.

Compiled 2026-10-19 from the official Steinberg online documentation.
The requested URL `https://www.steinberg.help/r/dorico-pro/6.0/en/` returns a 301 redirect, and the manual currently served is **Dorico Pro 6.2 (build 6.2.30)**.
All tables below come from that version.
Two Steinberg documents were used:

- **Dorico Popover Reference 6.2** (`/r/dorico/doricopopovers/6.2/en/...`), which holds the entry tables.
- **Dorico Pro Help 6.2** (`/r/dorico-pro/6.2/en/...`), which holds the "Inputting X with the popover" task pages that describe behaviour (where an item lands, how long it lasts, and so on).

Every section gives both URLs.
The manual text is paraphrased here.
Only the short syntax tokens are quoted exactly.
Items marked **(Pro only)** are flagged that way in the manual and are missing from Elements/SE.

Status legend used in the "Not documented" lists:
**unverified** means the manual does not mention the entry.
It does not mean the entry is wrong.
These entries need a live test in Dorico before a tool relies on them.

---

## 0. Shortcuts and shared conventions

### 0.1 Key commands that open each popover (Write mode, default English keyboard layout)

| Key | Popover / action | Notes |
|---|---|---|
| `Shift-B` | Bars and barlines | |
| `Shift-C` | Clefs and octave lines | |
| `Shift-D` | Dynamics | Pressing Return on a selected dynamic reopens it for editing. |
| `Shift-F` | Fingerings | |
| `Shift-G` | Figured bass | |
| `Shift-H` | Holds and pauses | |
| `Shift-I` | Note tools (intervals, transpose, invert, and so on) | |
| `Shift-K` | Key signatures | |
| `Shift-L` | Lyrics | |
| `Shift-M` | Time signatures (meter) | |
| `Shift-O` | Ornaments (also trills, arpeggios, glissandi, jazz articulations, guitar techniques) | |
| `Shift-P` | Playing techniques (also pedal lines, harp pedals, harmonics, string indicators) | |
| `Shift-Q` | Chord symbols | Opening this popover ends note input. |
| `Shift-R` | Repeats and tremolos | |
| `Shift-T` | Tempo | |
| `Shift-U` | Cues (Pro only) | |
| `Shift-0` (zero) | MIDI trigger regions | |
| `;` (semicolon) | Tuplets | |
| `Shift-A` | Rehearsal mark | **Not a popover.** It inserts the next rehearsal mark at once and has no text field. |
| `Shift-X` / `Shift-Alt/Opt-X` | Staff text / system text | **Not a popover.** It opens the rich text editor. |

The manual describes the pattern as Shift plus a letter opening a popover.
The defaults change with the keyboard language setting.
Every popover can also be opened from Notations toolbox > Popovers or from a menu item, for example **Write > Create Dynamic** or **Write > Create Tempo**.
Selecting an existing item and pressing Return reopens its popover.
Sources: [Key commands in Dorico](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/program_concepts/program_concepts_key_commands_in_dorico_r.html), [Popovers in Dorico](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/program_concepts/program_concepts_popovers_c.html), and the individual popover pages cited below.

### 0.2 Conventions shared by many popovers

| Syntax | Meaning | Where documented |
|---|---|---|
| `( ... )` | Parenthesized item, e.g. `(f)`, `(arco)`, `(q=72)`, `(Cmaj7)` | Dynamics, playing techniques, tempo, chord symbols |
| `[ ... ]` | Hidden item, e.g. `[pizz]`, `[q=96]` | Playing techniques and tempo only. In the time-signature popover, square brackets have a different meaning: a beat grouping that is not shown. |
| `->` suffix | Gives the item a duration that keeps going while you input notes, e.g. `vibrato->` | Playing techniques, string indicators |
| `?` | Ends the current open-ended item during note input | Gradual dynamics, playing techniques, string indicators |
| `\|` or `stop` | Ends an octave line during note input | Octave lines |
| `*`, `s*`, `u*` | End sustain, sostenuto, or una corda pedal lines | Pedal lines |
| Return | Commits the entry for all voices/staves (global scope) | All |
| Alt/Opt-Return | Commits locally: the caret voice for dynamics and octave lines, the selected staves for meters, keys, and barlines, or a single local chord symbol | Dynamics, keys, time signatures, bars/barlines, octave lines, chord symbols |
| Space (during note input) | Moves the caret on by the current duration, which also lengthens open-ended items such as `p<`, `8va`, `ped`, `vibrato->`, and trills | |

**How an item's span is set (applies to every popover):**

- Outside note input, items with duration span the current selection.
  Whether they snap to notes only or to any items depends on the *item input position* preference.
  Gradual dynamics end at the start or the end of the last selected note, depending on the *gradual dynamic input position* preference.
- During note input, the item starts at the caret.
  Open-ended items do not exist until the caret moves on, either by Space or by inputting notes, because that movement sets their length.

**Interactive-only features.**
Some features depend on the live UI and cannot be packed into one `Definition=` string.
These are the suggestion menus (tempo, playing techniques, pedal lines, cues), Space advancing, the `?` and `stop` terminators that act on an item still being input, lyric and chord-symbol navigation keys, the fretted-instrument fingering hand toggle, and the Local/Global toggle.
A command-driven tool has to supply the final text itself and has to set the duration through the selection.

### 0.3 Beat-unit codes (shared by tempo, tuplets, and adding/removing beats)

| Entry | Note value |
|---|---|
| `z` or `2` | 64th |
| `y` or `3` | 32nd |
| `x` or `4` | 16th |
| `e` or `5` | eighth |
| `q` or `6` | quarter |
| `h` or `7` | half |
| `w` or `8` | whole |
| `2w` or `9` | double whole (breve) |
| `.` | rhythm dot, appended once per dot, e.g. `q.`, `h..` |

The number codes match the note-input duration keys.
A numeric beat unit must be separated from a preceding number by a space or a hyphen, e.g. `+2 6`, `+2-6`, `5:4-6.`.
Source: [Beat units](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_beat_units_r.html).

---

## 1. Dynamics popover (`Shift-D`)

Sources:
[Popover Ref: Dynamics popover](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_dynamics_r.html) ·
[Immediate, force, and combined](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_dynamics_dynamics_r.html) ·
[Gradual](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_dynamics_gradual_r.html) ·
[Modifiers](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_dynamics_modifiers_r.html) ·
[Pro Help: Inputting dynamics with the popover](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_dynamics_inputting_popover_t.html) ·
[Pro Help: Dynamics popover](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_dynamics_popover_r.html) ·
[Types of dynamics](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/notation_reference/notation_reference_dynamics/notation_reference_dynamics_types_r.html) ·
[Groups of dynamics](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/notation_reference/notation_reference_dynamics/notation_reference_dynamics_groups_c.html) ·
[Linked dynamics](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/notation_reference/notation_reference_dynamics/notation_reference_dynamics_linked_c.html) ·
[Niente markings](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/notation_reference/notation_reference_dynamics/notation_reference_dynamics_niente_hairpins_c.html) ·
[Messa di voce](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/notation_reference/notation_reference_dynamics/notation_reference_dynamics_messa_di_voce_c.html) ·
[Truncation](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/notation_reference/notation_reference_dynamics/notation_reference_dynamics_placement_gradual_dynamics_trunctating_c.html) ·
[5.1 Dynamics popover page (older, longer list)](https://www.steinberg.help/r/dorico-pro/5.1/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_dynamics_popover_r.html)

### 1.1 Immediate, force, and combined dynamics

| Entry | Result | Notes |
|---|---|---|
| `pppppp` ... `ppp`, `pp`, `p` | Piano levels down to six p's | The table gives the range as "pppppp to p". |
| `mp` | mezzo piano | |
| `mf` | mezzo forte | |
| `f`, `ff`, `fff` ... `ffffff` | Forte levels up to six f's | The table gives the range as "f to ffffff". |
| `fp` | fortepiano drawn as one glyph, no separator | Combined dynamic |
| `f-p`, `f:p`, `f/p` | fortepiano drawn with a separator character | Combined dynamic. Other combined pairs (one p-type level plus one f-type level, e.g. `ff-pp`) are documented only through the panel's Combined Dynamics section, so the popover form is **unverified**. |
| `sfz` | sforzando | Force/intensity-of-attack dynamic |
| `rfz` | rinforzando | Force/intensity-of-attack dynamic |
| `(f)` | Parenthesized dynamic | Works with any entry |

### 1.2 Gradual dynamics (hairpins and text)

| Entry | Result | Notes |
|---|---|---|
| `<` | Crescendo, drawn as a hairpin by default | |
| `cresc` / `crescendo` | Crescendo drawn as "cresc." text only | Stored as a property override on the gradual dynamic |
| `cresc...` / `crescendo...` | "cresc." text plus a continuation line | Property override |
| `>` | Diminuendo, drawn as a hairpin by default | |
| `dim` / `diminuendo` | "dim." text only | Property override |
| `dim...` / `diminuendo...` | "dim." text plus a continuation line | Property override |
| `decresc` / `decrescendo` | "decresc." text | |
| `decresc...` / `decrescendo...` | "decresc." text plus a continuation line | Property override |
| `<>` | Messa di voce: crescendo then diminuendo | One item with start, centre, and end handles |
| `><` | Messa di voce: diminuendo then crescendo | One item |
| `< >` / `> <` (with a space) | Two separate grouped hairpins that look like a messa di voce | Each has its own start and end handles. The space is what makes them separate. |
| `o<` / `>o` | Niente hairpin with a small circle at the closed end | |
| `n<` / `>n` | Niente hairpin with a letter "n" at the closed end | |
| `?` | Stops an open-ended gradual dynamic during note input | Typing a new immediate dynamic such as `f` also stops it. |

Niente on text gradual dynamics: when a gradual dynamic with niente is drawn as text, Dorico shows "dal niente" for crescendos and "al niente" for diminuendos.
In the manual, niente is a *property* (Properties > Dynamics > Niente) or a panel button.
A typed text form such as `dim. al niente` is **not documented**.

Direct key commands that skip the popover: `<` inputs a crescendo hairpin, `>` a diminuendo, `Shift-Alt/Opt-,` a cresc/dim messa di voce, and `Shift-Alt/Opt-.` a dim/cresc messa di voce.

### 1.3 Modifiers

A modifier must come with an immediate dynamic, separated from it by a space, e.g. `f molto`, `p espressivo`, `mf dolce`.
Modifier text is free.
The 5.1 page says plainly that the list is not complete because any modifier text can be typed.
To show only the modifier, hide the immediate dynamic afterwards with a property.

| Entry | Result | Notes |
|---|---|---|
| `subito`, `sub`, `sub.` | *subito* | Its look and position are set in Engraving Options > Dynamics. Example: `p sub`. |
| `possibile`, `poss`, `poss.` | *possibile* | e.g. `ff poss` |
| `poco` | *poco* | Can also qualify a gradual dynamic |
| `molto` | *molto* | Always placed *before* the level, whatever order you type, e.g. `f molto` shows as *molto f*. |
| `piu`, `più` | *più* | e.g. `piu f` |
| `meno` | *meno* | e.g. `meno p` |
| `mosso` | *mosso* | |
| any other word | Free modifier text in italics (e.g. `espressivo`, `dolce`, `sempre`) | The manual guarantees prefix/suffix placement only through the Prefix/Suffix properties. Free-text order handling beyond `molto` is not described. |

*Poco a poco* is a property on gradual dynamics.
No typed form for it is documented.

### 1.4 Dynamic phrases (several dynamics in one entry)

The popover takes whole phrases that mix immediate and gradual dynamics.
The manual's examples are `p<f>p`, `p<f`, `f>`, and `p<`.

| Entry | Result | Notes |
|---|---|---|
| `p<f` | p, then a crescendo, then f, all in one dynamic group | |
| `p<f>p` | p, crescendo, f, diminuendo, p | |
| `f>` | f followed by an open-ended diminuendo | |
| `p<` | p followed by an open-ended crescendo | |

**How long the hairpins are and where they end:**

1. **Outside note input, with a range selected.**
   The phrase is spread over the selection.
   Gradual dynamics end at the start or the end of the last selected note, depending on Preferences > Note Input and Editing > *gradual dynamic input position*.
   Selecting a single item gives an immediate dynamic at that point.
2. **During note input, open-ended entry** (`p<`, `f>`, `<`).
   The hairpin is not created until the caret moves on.
   It keeps growing with every Space press or new note, and it ends when you type `?` or a new immediate dynamic in the popover.
3. **During note input, closed phrase** (`p<f>p`).
   Each gradual dynamic in the phrase gets a default length of one **quarter note**.
   You lengthen or shorten it afterwards.
4. **Truncation.**
   An immediate dynamic that falls inside a hairpin's range cuts the hairpin short on the page.
   The hairpin still keeps its stored end position, and it grows back if that dynamic is deleted.

### 1.5 Grouping and linking

- **Grouping (horizontal).**
  Dynamics typed together (`p<f>p`) or input one after another next to each other, with gradual dynamics between the immediate ones, are **grouped automatically**.
  A group lines up in a row and moves and edits as one unit.
  Moving an inner immediate dynamic resizes the hairpins on each side.
  A single dynamic counts as a group of one.
  Edit > Notations > Dynamics > Group Dynamics groups dynamics by hand.
- **Linking (vertical).**
  Identical dynamics at the same position on several staves are **linked** when they are input together (caret extended across staves, or a multi-staff selection) or pasted.
  Editing or moving one linked dynamic changes all of them.
  Edit > Notations > Dynamics > Link links dynamics by hand, but only when the groups are the same.
- **Scope.**
  Return applies the dynamic to every voice and staff of the instrument, including both staves of a grand staff.
  Alt/Opt-Return during note input applies it only to the caret voice, which makes a voice-specific dynamic.

### 1.6 Not documented in the 6.2 or 5.1 manual (unverified)

The user asked about the following entries, but the manual does not mention them:

- `n` or `niente` as an *immediate* level, and `o` as a stand-alone niente.
  Niente is documented only as an end marking on hairpins (`o<`, `>o`, `n<`, `>n`).
- `sf`, `sff`, `sffz`, `sfffz`, `fz`, `ffz`, `sfp`, `sfpp`, `sfzp`, `rf`, `rinf`, `pf`.
  The manual lists only `sfz` and `rfz`.
  The panel contains more force and combined dynamics, but their popover spellings are not given.
- A single-letter `s` shorthand for subito, e.g. `sp` or `s f`.
  Only `subito`, `sub`, and `sub.` are documented.
- `.` (period) to end or extend a dynamic.
  The documented terminator is `?`.
- Typed text forms `dim. al niente`, `cresc. dal niente`, and `poco a poco` (these are properties).
- `cresc.` or `dim.` *with* a trailing period, e.g. `cresc.` instead of `cresc`.
  It probably works, but only the forms without the period are listed.
- Modifiers on gradual dynamics typed in the popover, e.g. `poco <` or `molto cresc`.
  The panel offers poco and niente gradual modifiers, but no popover syntax is given.

---

## 2. Playing techniques popover (`Shift-P`)

Sources:
[Popover Ref: Playing techniques popover](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_playing_techniques_r.html) ·
[Playing technique entries](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_playing_techniques_playing_techniques_r.html) ·
[Pedal lines](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_pedal_lines_r.html) ·
[Harp pedaling](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_harp_pedaling_r.html) ·
[Harmonics](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_harmonics_r.html) ·
[Pro Help: Inputting playing techniques with the popover](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_playing_techniques_inputting_popover_t.html) ·
[Pro Help: Playing techniques popover](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_playing_techniques_popover_r.html) ·
[Pedal lines input](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_pedal_lines_piano_inputting_popover_t.html) ·
[Retakes/levels](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_pedal_lines_piano_inputting_popover_adding_retakes_changes_t.html) ·
[Harp pedal diagrams](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_harp_pedal_diagrams_inputting_popover_t.html) ·
[String indicators](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_string_indicators_inputting_outside_staff_popover_t.html) ·
[Creating custom playing techniques](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/library/library_playing_techniques_custom_creating_t.html)

### 2.1 How entries map to the library

- Each playing technique in Library > Playing Techniques has a **Popover text** field.
  The popover matches what you type against that field.
- While you type, a menu lists the valid techniques that match.
  Because each technique is tied to a playback technique, the manual says it must be entered *as described* or chosen from the menu.
  Free text is not accepted here, unlike tempo.
  **A command-driven tool should therefore send the exact Popover text string.**
- The manual's table is only a selection.
  Many more techniques are valid, namely every technique in the library, each with its own Popover text.
- **Custom techniques:** Library > Playing Techniques > New, then fill in **Popover text**, which becomes the entry string, and choose a playback technique.
  A custom technique exists only in its project unless it is saved as default.
- Playing techniques are **voice-specific** by default.
  They go above the staff for up-stem voices and below for down-stem voices.
- During note input the popover takes **one** technique.
  Outside note input it takes **two** joined by `->` (`a->b`), which groups them.
- Outside note input with a range selected, an *Attribute*-type technique is placed at each note, and a *Direction*-type technique becomes one item with a duration spanning the range.

### 2.2 Modifiers of the entry

| Entry | Result | Notes |
|---|---|---|
| `(arco)` | Parenthesized technique | |
| `[pizz]` | Hidden technique (it still plays back) | |
| `vibrato->` | Technique with an open-ended duration | Grows with Space or note input during note input |
| `?` | Ends the current open-ended technique, leaving a duration line | |
| `<technique>` typed while a `->` technique is still running | Ends the running one and joins it to the new one with a *continuation* line | e.g. type `vibrato` after `non vibrato->` |
| `a->b` (outside note input) | Two techniques grouped with a transition | e.g. `sul pont->sul tasto` |

### 2.3 Documented technique entries (selection)

| Entry | Result | Notes |
|---|---|---|
| `string 1` ... `string 9` | String indicator outside the staff | The reference table uses `string 1`, while the task page uses `string1` and `string3->`. Both spellings appear. |
| `nat` | naturale (nat.) | |
| `vibrato` | vibrato | |
| `senza vibrato` | senza vib. | The task page also shows `non vibrato->`. |
| `legato` | legato | |
| `o` | Harmonic circle (o) | Glyph technique |
| `con sord` | con sordino (muted) | |
| `senza sord` | senza sordino | |
| `stopped` | "stopped" text | |
| `+` | stopped/muted (+) glyph | |
| `downbow` / `upbow` | Down bow / up bow glyphs | |
| `strong air pressure` | | |
| `double-tongue` | | |
| `fluttertongue` | f.t. | |
| `flt` | flt. | |
| `flz` | Flz. (Flatterzunge) | |
| `sul pont` | sul ponticello | |
| `sul tasto` | sul tasto | |
| `pst` | poco sul tasto | |
| `pizz` | pizzicato | |
| `spicc` | spiccato | |
| `arco` | arco | |
| `tongue click`, `finger click` | Stockhausen symbols | |
| `motor on` / `motor off` | Vibraphone motor | |
| `open` | open | |
| `damp`, `damp large` | | |
| `full barre`, `half barre` | Guitar barré | |
| `strum up`, `strum down` | | |
| `lh`, `rh` | Left hand / right hand | |

Not in the table but almost certainly valid through the menu: `col legno`, `mute`, `trem.`, `ord.`, `sul G`, and so on.
They depend on the library, so check them against the live library.

### 2.4 Pedal lines (same popover)

| Entry | Result | Notes |
|---|---|---|
| `ped` | Sustain pedal line | Lengthens with Space or note input |
| `1/4`, `1/2`, `3/4`, `1` | Sustain pedal level change (Pro only) | Shown only when the pedal line uses the Line continuation type |
| `^`, `notch`, `retake` | Retake in a sustain pedal line | Sustain only |
| `nonotch` | Removes a retake | |
| `*` | Stops the sustain pedal line (note input) | |
| `sost` / `s*` | Sostenuto pedal line / stop it | |
| `unacorda` / `u*` | Una corda pedal line / stop it | |

### 2.5 Harp pedal diagrams (harp staff)

| Entry | Result | Notes |
|---|---|---|
| Note names with `b`/`^` (flat), `-`/nothing (natural), `#`/`v` (sharp) | Pedal setting for the named strings | Strings not named stay as they were, or natural at the start. |
| `BbEb` or `--^\|^---` or `DCBbEbFGA` | D C B♭ E♭ F G A | In the symbolic form the order is D C B \| E F G A, and `\|` divides the left and right foot. |
| `C#F#G#` or `-v-\|-vv-` or `DC#BEF#G#A` | D C♯ B E F♯ G♯ A | |

### 2.6 Harmonics (the entry must start with a harmonic keyword)

Separate the tokens with spaces, e.g. `harm nat n1 s1 p4 diamond`.

| Entry | Result |
|---|---|
| `harm`, `harmonic`, `harmonics` | Harmonic (natural by default) |
| `nat`/`natural`, `art`/`artificial` | Natural or artificial type |
| `nh`, `hh`, `harm nat`, `harmonic natural` | Natural harmonic |
| `ah`, `harm art`, `harmonic artificial` | Artificial harmonic |
| `ph` / `pinch` | Pinch harmonic / pinch artificial |
| `p4`, `p=4`, `partial=4` | Partial number |
| `n2`, `n=2`, `node=2` | Node |
| `s3`, `s=3`, `string=3` / `s=D4` | String by number (counted from the highest string) or by pitch |
| `circle`, `circleabove` | Circle above (natural harmonics) |
| `diamond`, `diamondnotehead`, `sounding` | Diamond notehead (natural harmonics) |
| `white`, `whitediamond`, `whitediamondnotehead`, `touched` | White diamond for the touched pitch (natural harmonics) |
| `normal` | White diamond for the touched pitch (artificial harmonics) |
| `sounding`/`singlesounding`, `stopped`/`singlestopped` | Artificial harmonic notehead styles |
| `open` / `noopen` | Show or hide the open-string pitch |
| `paren` / `noparen` | Show or hide the parenthesized sounding pitch |
| `noharm` | Delete the harmonic |

---

## 3. Tempo popover (`Shift-T`)

Sources:
[Popover Ref: Tempo popover](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_tempo_r.html) ·
[Absolute](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_tempo_absolute_r.html) ·
[Metronome marks](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_tempo_metronome_marks_r.html) ·
[Gradual](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_tempo_gradual_r.html) ·
[Relative](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_tempo_relative_r.html) ·
[Equations](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_tempo_equations_r.html) ·
[Rhythmic feels](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_tempo_rhythmic_feels_r.html) ·
[Pro Help: Inputting tempo marks with the popover](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_tempo_inputting_popover_t.html) ·
[Tempo panel](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_tempo_panel_r.html) ·
[Types of tempo marks](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/notation_reference/notation_reference_tempo/notation_reference_tempo_types_r.html)

General behaviour:

- The popover takes free text.
  A suggestion menu offers known tempo marks, and anything else becomes custom tempo text.
- Dorico has five tempo types: Absolute, Gradual, Relative, Reset (`a tempo`, `Tempo primo`), and Tempo equation.
  Words that Dorico recognizes are given the matching type and playback behaviour.
- Tempo marks are system-attached.
- During note input, a gradual tempo change starts at the caret with a default length of one quarter note.
  Unlike hairpins, it does **not** grow as you input more notes.
- Outside note input, a gradual tempo change spans the selection.
- Metronome values are shown as integers, but the exact decimal value is used in playback.
- When no tempo is set, playback runs at 120 bpm.

| Entry | Result | Notes |
|---|---|---|
| `q=120` | Metronome mark ♩ = 120 | The beat unit comes from §0.3, e.g. `h=60`, `q.=80`, `e=200`, `h.=40` |
| `q=96-112` | Metronome range | A hyphen separates the minimum and maximum. The display separator is an Engraving Option. |
| `(q=52)` | Parenthesized metronome mark | |
| `[q=96]` | Hidden tempo mark (still plays back) | |
| `Adagio`, `Allegro`, `Allegretto`, `Rubato`, ... | Absolute tempo change (text) | A suggestion supplies a default bpm |
| `Presto q=176` | Text plus metronome mark | Text first, then a space, then the mark |
| `più`, `meno` | Listed among absolute-tempo examples | |
| `Mosso`, `Lento` | Relative tempo change | A percentage change can be set later as a property |
| `rit.`, `ritardando` | Gradual tempo change | |
| `rit....` | rit. with a continuation line | Text plus three periods (a property override) |
| `rall.`, `rallentando`, `rall....` | Gradual tempo change (with line) | |
| `accel.`, `accelerando`, `accel....` | Gradual tempo change (with line) | |
| `e=e.` | Tempo equation ♪ = ♪. | Pattern `[beat unit]=[beat unit]`. Tuplet units are not supported yet. |
| `q=e`, `q.=h` | Tempo equations (metric modulation) | |
| `Light swing 8ths`, `Medium swing 16ths`, `Heavy swing 8ths`, ... | Rhythmic feel for swing playback | The full set is light/medium/heavy x 8ths/16ths |
| `Straight (no swing)` | Straight feel | |
| `2:1 swing 8ths (fixed)`, `2:1 swing 16ths (fixed)` | Triplet swing, fixed | |
| `3:1 swing 8ths (fixed)`, `3:1 swing 16ths (fixed)` | Dotted swing, fixed | |

Separating `rit-ar-dan-do` into syllables works only when a suggestion with the full valid text is picked from the menu.
Typing hyphens by hand comes later, by editing the text.

**Not documented (unverified):**

- `c. q=120` or `ca. q=120` as an approximate entry.
  Approximate is documented only as a property (Is approximate).
- `a tempo`, `Tempo primo`, `Tempo I`, `poco rit.`, `molto rall.`, `poco meno mosso`, `più mosso`.
  They appear in the Tempo panel (Reset Tempo section, and modifiers on gradual/relative changes), and the popover's suggestion menu would probably match them.
  Their behaviour as typed text has not been checked.
- `q=h` (the user's example).
  It follows the documented `[unit]=[unit]` pattern, so it should give a tempo equation, but the manual's examples are only `e=e.`, `q=e`, and `q.=h`.
- Decimal bpm such as `q=72.5` is implied to work by the note on decimals, but the exact syntax is not shown.

---

## 4. Ornaments popover (`Shift-O`)

Sources:
[Popover Ref: Ornaments popover](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_ornaments_r.html) ·
[Ornaments](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_ornaments_ornaments_r.html) ·
[Trill intervals](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_ornaments_trill_intervals_r.html) ·
[Jazz ornaments](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_ornaments_jazz_ornaments_r.html) ·
[Jazz articulations](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_ornaments_jazz_articulations_r.html) ·
[Arpeggio signs](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_ornaments_arpeggio_signs_r.html) ·
[Glissando lines](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_ornaments_glissando_lines_r.html) ·
[Guitar techniques](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_ornaments_guitar_r.html) ·
[Pro Help: Inputting ornaments/trills](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_ornaments_inputting_popover_t.html) ·
[Arpeggio input](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_arpeggio_signs_inputting_popover_t.html) ·
[Glissando input](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_glissando_lines_inputting_popover_t.html) ·
[Jazz articulation input](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_jazz_articulations_inputting_popover_t.html)

### 4.1 Ornaments and trills

| Entry | Result | Notes |
|---|---|---|
| `tr` / `trill` | Trill (with a wiggly extension line) | Spans the selection, or during note input the next note or Space advance. The default interval is a major or minor 2nd, depending on context. |
| `tr m3`, `trill M2`, `tr p4`, `tr aug2` | Trill with a set interval | A **space** between `tr` and the interval is required. The interval applies only to the first selected note. |
| `shorttr` | Short trill | |
| `mordent` / `mor` | Mordent | |
| `turn` | Turn | |
| `invertedturn` / `invturn` | Inverted turn | |

Trill interval tokens: degree `1`-`8`, with quality `M`/`maj`/`major`, `m`/`min`/`minor` (case matters for M and m), `p`/`per`/`perf`, `d`/`dim`/`diminished`, or `a`/`aug`/`augmented`.
A Preference (Note Input and Editing > Editing) makes Dorico input a separate trill for each selected note.

Not documented (unverified): inverted mordent, pralltriller, `tr` with an accidental such as `tr#`, and turn variants other than the inverted turn.
They may be reachable only from the Ornaments panel.

### 4.2 Jazz ornaments and articulations

| Entry | Result |
|---|---|
| `brassbend` | Bend (jazz ornament) |
| `flip` | Flip |
| `jazz` / `shake` | Jazz turn / shake |
| `smear` | Smear |
| `plop` / `plopsmooth` | Plop (bend / smooth) |
| `scoop` | Scoop |
| `doit` / `doitsmooth` | Doit (bend / smooth) |
| `fall` / `fallsmooth` | Fall (bend / smooth) |

Jazz articulations attach to every selected note, which during note input is the last note entered.
Their line style follows the project-wide settings.

### 4.3 Arpeggio signs

| Entry | Result | Notes |
|---|---|---|
| `arp`, `arpup`, `arpeggioup` | Up arpeggio | During note input this works only in **chord mode** (press `Q` first). On existing music it covers every note in the selected voices, and it can cross staves within one instrument. |
| `arpdown`, `arpeggiodown` | Down arpeggio | |
| `nonarp`, `nonarpeggio` | Non-arpeggio bracket | |
| `slurarp` | Curved arpeggio | |

### 4.4 Glissando lines

| Entry | Result | Notes |
|---|---|---|
| `gliss` | Glissando in the default style | **Not available during note input**, and not from the last note on a staff. Select two or more notes, or a single note to connect it to the next note in the same voice. |
| `glissstraight` | Straight line | |
| `glisswavy` | Wavy line | |

### 4.5 Guitar techniques

| Entry | Result |
|---|---|
| `bend` | Guitar bend |
| `vibbend` / `vibscoop` / `vibdip` | Vibrato bar dive and return / scoop / dip |
| `wbar`, `w/bar` | Vibrato bar line |
| `hammer`, `ho` | Hammer-on |
| `pull`, `po` | Pull-off |
| `hammerpull`, `hopo`, `hp`, `ligado`, `lig` | Hammer-on/pull-off (ligado) |
| `tap` / `tappull` | Right-hand tap / with pull-off |
| `lhtap` / `lhtappull` | Left-hand tap / with pull-off |

---

## 5. Holds and pauses popover (`Shift-H`)

Sources:
[Popover Ref: Holds and pauses](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_holds_pauses_r.html) ·
[Fermatas](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_holds_pauses_fermatas_r.html) ·
[Breath marks](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_holds_pauses_breath_marks_r.html) ·
[Caesuras](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_holds_pauses_caesuras_r.html) ·
[Pro Help: Inputting holds and pauses](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_holds_pauses_inputting_popover_t.html) ·
[Types of fermatas](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/notation_reference/notation_reference_holds_pauses/notation_reference_holds_pauses_types_fermatas_r.html)

Placement: a fermata appears on **all staves** at the position of the earliest selected item.
A caesura appears on all staves, to the *left* of the caret or note.
A breath mark appears only on the selected staves, to the *right* of the caret or note.

| Entry | Result |
|---|---|
| `fer`, `fermata`, `pause` | Fermata |
| `verylongfermata`, `verylongfer` | Very long fermata |
| `longfermata`, `longfer` | Long fermata |
| `shortfermata`, `shortfer` | Short fermata |
| `veryshortfermata`, `veryshortfer` | Very short fermata |
| `shorthenzefermata`, `shorthenzefer` | Short fermata (Henze) |
| `longhenzefermata`, `longhenzefer` | Long fermata (Henze) |
| `curlew` | Curlew (Britten) |
| `breathmarkcomma`, `comma`, `,` | Breath mark (comma) |
| `breathmarktick` | Breath mark (tick-like) |
| `breathmarkupbow` | Breath mark (up-bow-like) |
| `breathmarksalzedo` | Breath mark (Salzedo) |
| `caes`, `caesura`, `//` | Caesura |
| `caesurathick`, `thickcaesura`, `thick//` | Thick caesura |
| `caesuracurved`, `curvedcaesura`, `curved//` | Curved caesura |
| `caesurashort`, `shortcaesura`, `short//` | Short caesura |
| `caesurasingle`, `singlecaesura`, `single//` | Single-stroke caesura |

Each fermata type plays back with a different hold length.

---

## 6. Time signatures popover (`Shift-M`)

Sources:
[Popover Ref: Time signatures](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_time_signatures_time_sigs_r.html) ·
[Pick-up bars](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_time_signatures_pick_up_bars_r.html) ·
[Pro Help: Inputting time signatures](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_time_signatures_inputting_popover_t.html) ·
[Pro Help: Inputting pick-up bars](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_time_signatures_pick_up_bars_inputting_popover_t.html) ·
[Types of time signatures](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/notation_reference/notation_reference_time_signatures/notation_reference_time_signatures_types_r.html)

**Whitespace and separators change the meaning.**
Watch the spaces in the table below.

| Entry | Result | Notes |
|---|---|---|
| `2/4`, `3/4`, `6/8`, `5/4`, `2/2` | Simple, compound, or irregular meter | |
| `c` | Common time (4/4 symbol) | |
| `cutc`, `cut`, `¢` | Cut common time (2/2 symbol) | |
| `x` / `X` | Open meter shown as X | You add barlines and beats yourself. |
| `open` | Open meter with no indication | |
| `3+2+2/8` | Additive meter: beat groups are set and shown | |
| `[2+3+2]/8` | 7/8 shown, with beat grouping 2+3+2 that is not shown | |
| `6/8 + 3/4` | **Alternating** meter | Needs a space on **both** sides of `+` |
| `2/4\|6/8` | **Aggregate** meter with dashed barlines between the parts | Pipe with no spaces |
| `2/4:6/8` | Aggregate meter without the dashed barlines | Colon |
| `2/4 (6/8)` | Interchangeable, parenthesized style | Space before `(` |
| `2/4 / 6/8` | Interchangeable, slash style | Spaces around `/` |
| `2/4 = 6/8` | Interchangeable, equals style | Spaces around `=` |
| `2/4 - 6/8` | Interchangeable, dash style | Spaces around the dash. The manual prints an en dash, but a plain hyphen is the expected keyboard character. Check this. |
| `4/4,1` | 4/4 with a one-quarter pick-up | Pattern `[meter],[pick-up]`. The number counts **denominator units**. |
| `4/4,1.5` | 4/4 with a dotted-quarter pick-up | |
| `4/4,0.25` | 4/4 with a 16th pick-up | |
| `3/4,0.75` | 3/4 with a dotted-8th pick-up | |
| `6/8,2` | 6/8 with a pick-up of two eighths | |
| `2/2,0.5` | 2/2 with a quarter pick-up | |

Notes:

- Return inserts the meter on all staves.
  Alt/Opt-Return limits it to the selected staves (an independent meter).
- Dorico re-bars the music that follows.
  It adds beats at the end of the affected region only when **Insert mode** (`I`) is on.
- Adding a pick-up at the start of a flow does not push existing music later.
- Non-power-of-two meters such as `5/6` are supported as a type.
  Fractional meters are not.

---

## 7. Key signatures popover (`Shift-K`)

Sources:
[Popover Ref: Key signatures](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_key_signatures_r.html) ·
[Pro Help: Inputting key signatures](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_key_signatures_inputting_popover_t.html) ·
[Types of key signatures](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/notation_reference/notation_reference_key_signatures/notation_reference_key_signatures_types_r.html)

| Entry | Result | Notes |
|---|---|---|
| `C`, `D`, `G`, `Bb`, `F#`, `Ab` | Major key | **Upper case** means major |
| `c`, `d`, `g`, `f#`, `bb`, `eb` | Minor key | **Lower case** means minor |
| `#` or `s` | Sharp in a key name | e.g. `Fs` = F♯ major, `cs` = c♯ minor |
| `b` or `f` | Flat in a key name | e.g. `Bf` = B♭ major. Watch out: `f` alone means F minor. |
| `3#`, `3s` | Major key with 3 sharps (A major) | Counted forms always give a major key |
| `4b`, `4f` | Major key with 4 flats (A♭ major) | |
| `1s` | G major | Example from the task page |
| `open`, `atonal` | Open/atonal key signature | Shows no accidentals. Accidentals are spelled from the melodic direction. |

Notes:

- Return inputs the key on all staves.
  Alt/Opt-Return limits it to the selected staves.
- Transposing instruments get their key signatures automatically, so do not enter them yourself.
- Custom key signatures can be input only from the panel, not the popover.

**Not supported or not documented:**

- `0` as an entry.
  Use `C` or `open`.
- Mode names (`Dm dorian`, `D dor`).
  Modes appear only in the **note tools scale-mapping** entries and in **chord symbols** (modal chord symbols), not in key signatures.

---

## 8. Clefs and octave lines popover (`Shift-C`)

Sources:
[Popover Ref: Clefs](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_clefs_octave_lines_clefs_r.html) ·
[Clef octave shifts](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_clefs_octave_lines_clef_octave_shifts_r.html) ·
[Octave lines](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_clefs_octave_lines_octave_lines_r.html) ·
[Pro Help: Inputting clefs](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_clefs_inputting_popover_t.html) ·
[Pro Help: Inputting octave lines](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_octave_lines_inputting_popover_t.html)

### 8.1 Clefs

| Entry | Result |
|---|---|
| `g`, `g2`, `sol`, `treble` | Treble (G) clef |
| `f`, `f4`, `fa`, `bass` | Bass (F) clef |
| `ca`, `c3`, `ut3`, `alto` | Alto C clef |
| `ct`, `c4`, `ut4`, `tenor` | Tenor C clef |
| `g8ba`, `g8d`, `treble8ba`, `treble8d` | Treble 8 below |
| `g15ba`, `g15d`, `treble15ba`, `treble15d` | Treble 15 below (Pro) |
| `g8va`, `g8u`, `treble8va`, `treble8u` | Treble 8 above (Pro) |
| `g15ma`, `g15u`, `treble15ma`, `treble15u` | Treble 15 above (Pro) |
| `ca8ba`/`ca8d`/`alto8ba`/`alto8d`, `ct8ba`/`ct8d`/`tenor8ba`/`tenor8d` | Alto or tenor 8 below (Pro) |
| `f8ba`/`f8d`/`bass8ba`/`bass8d`, `f15ba`/`f15d`/`bass15ba`/`bass15d` | Bass 8 or 15 below (Pro) |
| `f8va`/`f8u`/`bass8va`/`bass8u`, `f15ma`/`f15u`/`bass15ma`/`bass15u` | Bass 8 or 15 above (Pro) |
| `perc` | Unpitched percussion clef |
| `tab4`, `tab6` | 4- or 6-string tablature clef |
| `g1` | French violin clef (Pro) |
| `soprano`/`c1`/`ut1`, `mezzo`/`c2`/`ut2`, `baritone`/`c5`/`ut5` | Soprano, mezzo-soprano, baritone C clefs (Pro) |
| `baritonebass`, `subbass` | Baritone F, sub-bass F clefs (Pro) |
| `invisible` | Invisible clef (Pro) |

Octave shift on a clef (it changes the written octave without an octave indicator): clef name + `+N` or `-N`, optionally followed by `c` (concert-pitch layouts only) or `t` (transposed-pitch layouts only).
Examples: `g+2`, `g-2`, `treble+1t`.

Outside note input, selecting a range adds the clef at the start of the range and a restoring clef at its end.

### 8.2 Octave lines

| Entry | Result | Notes |
|---|---|---|
| `8va`, `8`, `8u`, `1u` | One octave up | Placed above the staff |
| `15ma`, `15`, `15u`, `2u` | Two octaves up | |
| `22ma`, `22`, `22u`, `3u` | Three octaves up | |
| `8ba`, `8vb`, `8d`, `1d` | One octave down | Placed below the staff |
| `15ba`, `15vb`, `15d`, `2d` | Two octaves down | |
| `22ba`, `22vb`, `22d`, `3d` | Three octaves down | |
| `loco` | Loco indication | |
| `\|` or `stop` | Ends the octave line at the caret (note input) | |

The line spans the selected notes.
During note input it starts at the caret and grows as you input notes or press Space.
Alt/Opt-Return limits it to the selected voice.
Dorico adjusts the written pitches automatically.
`15mb` (the user's example) is **not documented**, so use `15ba` or `15vb`.

---

## 9. Bars and barlines popover (`Shift-B`)

Sources:
[Popover Ref: Bars](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_bars_barlines_bars_r.html) ·
[Beats](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_bars_barlines_beats_r.html) ·
[Barlines](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_bars_barlines_barlines_r.html) ·
[Pro Help: Inputting bars/beats](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_bars_inputting_popover_t.html) ·
[Pro Help: Inputting barlines](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_barlines_inputting_popover_t.html)

### 9.1 Bars and beats

| Entry | Result | Notes |
|---|---|---|
| `+4` or `4` | Adds 4 bars | Bars go in after a selected barline, or before other selected items. During note input they go in at the caret, and a partial bar is filled out first. |
| `-2` | Deletes 2 bars | |
| `rest` | Adds a bar rest | |
| `trim` | Deletes empty bars (or beats) at the end of the flow | |
| `+2q`, `+2-6`, `+2 6`, `+2/4` | Adds two quarter beats | Beat unit from §0.3, or a fraction written like a meter |
| `-2q`, `-2-6`, `-2 6`, `-2/4` | Deletes two quarter beats | Type a plain hyphen. The manual's first example shows an en dash typo. |

`x2` is **not documented** in any form.

### 9.2 Barlines

| Entry | Result | Notes |
|---|---|---|
| `\|`, `single`, `normal` | Normal barline (explicit, so it breaks multi-bar rests) | |
| `\|\|`, `double` | Double barline | |
| `\|\|\|`, `triple` | Triple barline (Pro) | |
| `:`, `dash`, `dashed` | Dashed barline | |
| `\|]`, `fin`, `final` | Final barline | At the end of the last bar this may also trim the flow. |
| `'`, `tick` | Tick (top) (Pro) | |
| `tickbottom` | Tick (bottom) (Pro) | |
| `,`, `short` | Short (centre) (Pro) | |
| `shorttop` | Short (top) (Pro) | |
| `thick` | Thick (Pro) | |
| `doublethick`, `thickdouble` | Double thick | |
| `\|:`, `start` | Start repeat | With a range selected, an end repeat is also added at the end of the range. |
| `:\|`, `end` | End repeat | |
| `:\|:`, `:\|\|:`, `end-start`, `endstart` | End/start repeat | A repeat typed on an existing repeat combines with it. |

Barlines on single staves need an independent meter on those staves first.

---

## 10. Repeats and tremolos popover (`Shift-R`)

Sources:
[Popover Ref: Repeats and tremolos](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_repeats_r.html) ·
[Repeat endings](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_repeats_endings_r.html) ·
[Repeat markers](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_repeats_markers_r.html) ·
[Single-note tremolos](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_repeats_tremolos_single_r.html) ·
[Multi-note tremolos](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_repeats_tremolos_multi_r.html) ·
[Slash regions](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_repeats_slash_regions_r.html) ·
[Numbered bar regions](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_repeats_numbered_bar_regions_r.html) ·
[Bar repeat regions](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_repeats_bar_repeat_regions_r.html) ·
[Pro Help: Repeat endings](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_repeat_endings_inputting_popover_t.html) ·
[Additional endings](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_repeat_endings_inputting_additional_endings_popover_t.html) ·
[Repeat markers](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_repeat_markers_inputting_popover_t.html) ·
[Tremolos](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_tremolos_inputting_popover_t.html)

### 10.1 Repeat endings

| Entry | Result | Notes |
|---|---|---|
| `end`, `ending` | Repeat ending: 1st ending over the selected bars, plus a 2nd ending in the next bar | An end repeat barline is added if none exists. |
| `add` | Adds another ending segment | The selection must start at the first bar of the current last ending. |

### 10.2 Repeat markers (jumps and sections)

| Entry | Result | Notes |
|---|---|---|
| `D.C.`, `dc`, `da capo` | D.C. | Jump markers (D.C., D.S., Fine) line up to the right of the position. Select the barline where the instruction should end. |
| `D.C. al Fine`, `DC al Fine`, `dcalf` | D.C. al Fine | |
| `D.C. al Coda`, `DC al Coda`, `dcalc` | D.C. al Coda | |
| `D.S.`, `ds`, `dal segno` | D.S. | |
| `D.S. al Fine`, `DS al Fine`, `dsalf` | D.S. al Fine | |
| `D.S. al Coda`, `DS al Coda`, `dsalc` | D.S. al Coda | |
| `to coda`, `toc`, `tc` | To Coda | |
| `segno`, `seg`, `s` | Segno | The task page also gives `$` for segno, which the table does not list. |
| `fine`, `fin`, `f` | Fine | `fin` also means a final barline, but only in the *bars and barlines* popover. |
| `coda`, `co`, `c` | Coda section | A gap is left before the coda automatically. |

### 10.3 Tremolos

| Entry | Result | Notes |
|---|---|---|
| `/`, `\`, `1` | Single-note tremolo, 1 stroke | Goes on every note of a tie chain |
| `//`, `\\`, `2` | 2 strokes | |
| `///`, `\\\`, `3` | 3 strokes | |
| `////`, `\\\\`, `4` | 4 strokes | |
| `z`, `zonstem` | Z on stem (buzz roll) | |
| `//rel`, `//r`, `2rel`, `2r` | Tremolo with release | Leaves out the last note of the tie chain |
| `//att`, `//a`, `2att`, `2a` | Tremolo with attack | Leaves out the first note of the tie chain |
| `/2`, `\2`, `12` | Multi-note tremolo, 1 stroke | Needs two or more notes in one voice with the same duration. Written durations are adjusted, e.g. two quarters become two halves. |
| `//2`, `\\2`, `22` | Multi-note tremolo, 2 strokes | |
| `///2`, `\\\2`, `32` | Multi-note tremolo, 3 strokes | |
| `////2`, `\\\\2`, `42` | Multi-note tremolo, 4 strokes | |
| `0`, `clear` | Removes all tremolos | |

### 10.4 Regions

| Entry | Result | Notes |
|---|---|---|
| `slash` | Slash region over the selection | |
| `num`, `nb`, `numbars`, `number bars` | Numbered bar region | Counts like "1 (-8)" for regions of 4 or more bars. Hidden in full score by default. |
| `%` or `%1` | Bar repeat region, repeating the last bar | Not allowed in bar 1. Select empty bars. |
| `%2`, `%4` | Repeats the last 2 or 4 bars | |
| `%1,2`, `%1,4`, `%2,4` | Bar repeat with a count grouping (group every 2 or 4) | |

---

## 11. Rehearsal marks (`Shift-A`, no popover)

Source: [Pro Help: Inputting rehearsal marks](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_rehearsal_marks_inputting_t.html) · [Rehearsal marks](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/notation_reference/notation_reference_rehearsal_marks/notation_reference_rehearsal_marks_c.html)

- `Shift-A` inserts a rehearsal mark at the selected barline or item, or at the caret.
  No text is typed.
- The sequence (letters, numbers, or bar numbers) renumbers itself automatically, so marks can go in any order.
- Only one mark is input at a time.
- The index, sequence type, and prefix/suffix are set afterwards as properties.

---

## 12. Chord symbols popover (`Shift-Q`), brief

Sources:
[Popover Ref: Chord symbols](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_chord_symbols_r.html) (subpages: [roots](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_chord_symbols_roots_r.html), [accidentals](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_chord_symbols_accidentals_r.html), [qualities](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_chord_symbols_qualities_r.html), [intervals](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_chord_symbols_intervals_r.html), [alterations](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_chord_symbols_alterations_r.html), [modal](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_chord_symbols_modal_r.html), [other](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_chord_symbols_other_r.html)) ·
[Pro Help: Inputting chord symbols](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_chord_symbols_inputting_t.html)

| Component | Entry examples | Notes |
|---|---|---|
| Root | `C`, `Db`, `F#`; German `Des`, `Fis`, `H`; solfège `do`, `reb`, `fa#`, `ti`; Nashville `1`, `2b`, `4#`, `7` | |
| Accidentals | `#`, `b`, `x`/`##`, `x#`/`#x`/`###`, `bb`, `bbb` | |
| Quality | major: `M`, `maj`, `ma`, or nothing; minor: `m`, `min`, `mi`; `dim`/`di`/`o`; `aug`/`au`/`ag`/`+`; `half-dim`/`halfdim`/`hd`; 6/9: `6/9`, `69`, `%` | M and m are case-sensitive |
| Intervals | `7`, `9`, `13`; major 7th: `^7` or `^`; major 9th: `^9`, `maj9`, `9maj7` | |
| Alterations | `#9`/`+9`, `b5`/`-5`, `add9`, `addb9`, `add+11`, `addF#`, `sus4`, `sus9`, `omit3`/`no3` | |
| Modal | `dorian`, `lydian`, `mixolydian`, `melodic minor`, `whole tone`, `diminished half whole`, ... | |
| Altered bass | `Cmajb5/Eb` or `Cmajb5,Eb` | |
| Polychord | `Cmaj7\|D` or `Cmaj7;D` | |
| No chord | `N.C.`, `NC`, `no chord`, `none` | |
| Region | `reg` | Chord symbol region over the selection |
| Parenthesized | `(Cmaj7)` | |

Notes:

- Engraving Options decides how the result looks, not the spelling typed, so `C`, `Cmaj`, and `CM` all give the same symbol.
- Space moves to the next beat, and Tab moves to the next bar.
- Alt/Opt-L switches to local chord symbols, and Alt/Opt-G to global.

---

## 13. Fingering popover (`Shift-F`), brief

Sources: [Non-fretted](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_fingering_non_fretted_r.html) · [Fretted](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_fingering_fretted_r.html) · [Pro Help: Inputting fingerings](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_fingering_inputting_t.html)

| Entry | Result |
|---|---|
| `1` ... `7` | Single finger, brass valve, or trombone position |
| `12` | Valve combination 1+2 |
| `1,3,5` | One fingering per chord note (keyboard hand ordering is automatic) |
| `L2` (also `G`, `S`, `I`, `H` prefixes) / `R5` (also `D`, `M`) | Left-hand / right-hand fingering |
| `T` | Thumb |
| `2343` | Sequence on one note (ornaments) |
| `1,1` | The same finger on adjacent notes |
| `2(3)` / `[4]` | Alternative / editorial fingering |
| `1-3` | Finger substitution |
| `2/` | String shift indicator |
| Fretted LH: `0`-`5`, thumb `t`; RH: `p i m a e` or `1`-`5`, thumb `p`/`t`/`1`, pinky `e`/`x`/`c`/`o`/`5` | Up/Down Arrow switches the hand |

Fingerings go on one rhythmic position and one voice (the top voice) at a time.
There can be no more fingerings than notes.
Space moves to the next note.

---

## 14. Lyrics popover (`Shift-L`)

Sources: [Popover Ref: Lyrics](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_lyrics_r.html) · [Pro Help: Inputting lyrics](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_lyrics_inputting_t.html) · [Navigation during lyric input](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_lyrics_inputting_navigation_r.html)

Select the first note, open the popover, type one syllable, then advance.

| Key/entry | Effect |
|---|---|
| Space | Ends a word (or the last syllable) and moves to the next note. Leaves a gap or an extender line, depending on space and tie chains. |
| `-` (hyphen) | Ends a non-final syllable and moves on, with a hyphen drawn between syllables |
| Space or `-` pressed repeatedly | Skips notes, for melismas |
| Shift-Alt/Opt-Space | Non-breaking space, so several words form one lyric |
| Alt/Opt-`-` | Literal hyphen inside a syllable without advancing |
| `_` (underscore) | Elision slur |
| Up/Down Arrow | Changes the lyric line number (Up past line 1 reaches the chorus line `c`) |
| Shift-Up/Down Arrow | Moves the line above or below the staff |
| Alt/Opt-Down Arrow | Translation line (shown as `1*`) |
| Left/Right Arrow, Alt/Opt-Left/Right | Moves by character / by syllable |
| Return or Esc | Closes the popover. It also closes on its own at the last note of the voice. |

Lyrics can also be pasted from outside.
Syllable type (gap or hyphen) can be changed later as a property.
A single `Definition=` string can only make one syllable.
A multi-syllable tool has to repeat the advance step for each note.

---

## 15. Cues popover (`Shift-U`, Pro only), brief

Sources: [Popover Ref: Cues](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_cues_r.html) · [Pro Help: Inputting cues](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_cues_inputting_t.html) · [Cues popover](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_cues_popover_r.html)

- Select a range on the destination staff and type the name of the source instrument as it is named in the project, e.g. `Flute 1`, `Piano (a)`, or a single kit instrument.
  Then pick it from the candidate menu.
- If the full name is typed by hand, Return has to be pressed **twice**.
- An instrument name that is not in the project creates nothing.
- A name shared by several instruments, such as `violin`, picks the first player.
- A new cue at the same position replaces the existing cue there.
- Whole percussion kits cannot be cued.
- Cues are shown in parts and only as signposts in the full score by default.

---

## 16. Other popovers (for completeness)

| Popover | Key | Entry summary | Source |
|---|---|---|---|
| Tuplets | `;` | `3` / `3:2` / `3/2` / `3 2`, `5:4`, `6:4`, `7:4`, `9:8`, `2:3`, `5:4q.` / `5:4-6.`. Ratio first, optional beat unit. `:` returns to normal notes. | [Tuplets](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_tuplets_r.html) |
| Note tools | `Shift-I` | Add intervals `3`, `-4`, `3,6`, `maj3`; transpose `t3`, `t-6`, `t top -8`; invert `inv C4`; reverse `rev`; rotate `rot 2`; repeat `rep 2 pit`; map pitch `c4=eb4`; map scale `c M to c m`, `snap cmin`, `spell Cmaj` (modes `dor`, `phryg`, `lyd`, `mix`, `loc`, ...) | [Note tools](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_note_tools_r.html) |
| Figured bass | `Shift-G` | `6#42`, `6,#4,2`, `(#643)`, `4->3` / `4_3`, `r=2`, `d=n`, `tasto`/`ts`, chord-symbol-to-figures (`G/B`) | [Figured bass](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_figured_bass_figures_r.html) |
| MIDI trigger regions | `Shift-0` | `C4`, `60`, `C4,E4,G4`, `C4,E4,G4(112)` (velocity in brackets) | [MIDI trigger regions](https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_midi_trigger_regions_r.html) |
| Text | `Shift-X` / `Shift-Alt/Opt-X` | Rich text editor, not a popover. Esc or Ctrl/Cmd-Return closes it. | [Inputting text items](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_text_adding_t.html) |

Jazz articulations have no popover of their own.
They are typed in the **ornaments** popover (§4.2).

---

## Sources

- Dorico Popover Reference 6.2 (en), index: https://www.steinberg.help/r/dorico/doricopopovers/6.2/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_c.html
- Dorico Pro Help 6.2 (en), Write mode > Notations input task pages, URLs listed per section above.
- Dorico Pro Help 6.2, Popovers in Dorico: https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/program_concepts/program_concepts_popovers_c.html
- Dorico Pro Help 6.2, Key commands in Dorico: https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/program_concepts/program_concepts_key_commands_in_dorico_r.html
- Dorico Pro Help 6.2, Dynamics notation reference pages (types, groups, linked, niente, messa di voce, truncation), URLs in §1.
- Dorico Pro Help 6.2, Tempo notation reference and Tempo panel, URLs in §3.
- Dorico Pro Help 5.1, Dynamics popover (older single-page table with the "modifier text is free" remark): https://www.steinberg.help/r/dorico-pro/5.1/en/dorico/topics/write_mode/write_mode_notations_input/write_mode_dynamics_popover_r.html
- The content was fetched through the Fluid Topics API behind steinberg.help (`/api/khub/maps/{mapId}/topics/{contentId}/content`), with map IDs `iuRC2znMppy_r3SiZ6eo_w` (Popover Reference 6.2) and `BYbh2hvBDwUCjSijIhHcqA` (Pro Help 6.2).


---

## Measured live (Dorico 6.2.30, doricomcp fixture, 2026-10-19)

Each entry was sent as `NoteInput.CreateDynamic?Definition=<entry>` on a selection of two notes (or `NoteInput.CreateTempo` on an anchor), then read back with `read_markings`.

### Dynamics

| Entry | Created | Read back as |
|---|---|---|
| `n`, `niente`, `o` | nothing | - |
| `sf`, `sff` | force dynamic | sf |
| `sffz`, `sfzp` | force dynamic | sfz (sffz and sfz read the same) |
| `fz`, `ffz` | force dynamic | fz |
| `rf` | force dynamic | rf |
| `rinf`, `rfz` | force dynamic | rfz |
| `fp`, `f-p`, `ff-pp`, `pf`, `sfp`, `sfpp` | a combined dynamic | level not readable |
| `p sub` | p | p, subito |
| `s p` | p | p, not subito (`s` is not a subito shorthand) |
| `f molto`, `meno f`, `più p` | the level with its modifier | f / p (the modifier is not readable) |
| `cresc`, `cresc.`, `poco <` | crescendo over the selection | cresc |
| `dim.`, `dim. al niente` | diminuendo over the selection | dim |
| `dal niente` | nothing | - |
| `p<.`, `p<?` | p and a crescendo | p, cresc |
| `p<f` on three notes | one group: p, crescendo to the last selected note, f | p, cresc (2 crotchets), f |
| `pp<ff>pp` on three notes | one group of five parts spread over the notes | pp, cresc, ff, dim, pp |
| `o<`, `f>o` | niente hairpins | cresc / f, dim |
| `p<>` | p and a messa di voce | p, messa di voce |
| `p<f` on one note | p, crescendo to the next note, f | hairpin length 1 crotchet |

### Tempo

| Entry | Read back as |
|---|---|
| `c. q=120` | text "c.", 120 bpm |
| `a tempo`, `Tempo primo` | the text |
| `poco rit.` | text "rit." (poco is dropped from the text), final 75% |
| `accel.` | final 125% |
| `più mosso` | relative 110% |
| `Allegro` | text, 140 bpm from the preset, metronome mark hidden |
| `q=120-132` | 120 bpm (the range is not readable) |
| `q=h`, `e=e.` | a metric modulation; nothing readable |
