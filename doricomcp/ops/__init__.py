"""Composer-level write operations on a live Session, shared by the MCP server and the confirmation harness, so
what the harness confirms is exactly the code path the tools run.

Every write is one Lua transaction (one undo step), read back and verified; a failed verification undoes it.
Commands that act on "the selection" always get a real selection first (an event starting at the target position,
or a temporary rest deleted in the same transaction): with nothing selected, popover commands can open a modal
dialog that blocks Dorico.

Modules, each importing only the ones before it: common -> dynamics -> markings; common -> notes.
"""
from .common import OpError, _events_by_id, brief, resolve_pos, select_apply
from .dynamics import add_dynamic, add_hairpin
from .markings import (
                       add_articulation,
                       add_barline,
                       add_break,
                       add_clef,
                       add_note_marking,
                       add_rehearsal_mark,
                       add_repeat_marker,
                       add_span,
                       add_text,
                       set_key_signature,
                       set_property,
                       set_tempo,
                       set_time_signature,
)
from .notes import (
                       add_grace_note,
                       add_notes,
                       add_tuplet,
                       add_voice,
                       copy_range,
                       delete_events,
                       delete_range,
                       edit_notes,
                       set_duration,
                       set_pitch,
                       swap_voices,
                       transpose_notes,
)

__all__ = ["OpError", "_events_by_id", "add_articulation", "add_barline", "add_break", "add_clef", "add_dynamic",
           "add_grace_note", "add_hairpin", "add_note_marking", "add_notes", "add_rehearsal_mark", "add_repeat_marker",
           "add_span", "add_text", "add_tuplet", "add_voice", "brief", "copy_range", "delete_events", "delete_range",
           "edit_notes", "resolve_pos", "select_apply", "set_duration", "set_key_signature", "set_pitch",
           "set_property", "set_tempo", "set_time_signature", "swap_voices", "transpose_notes"]
