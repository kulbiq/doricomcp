"""Offline self-check of the write operations (python -m doricomcp.ops): parsing, onset checks, clearing,
grids, hairpin bookkeeping, and the compact/grid reads, against a fake session. No Dorico needed."""
import asyncio
from fractions import Fraction

from .. import reads
from ..model import Event, bar_regions
from .common import OpError, advance_steps, clear_steps, grid_for, parse_notes
from .dynamics import LENGTH, _add_hairpin
from .markings import articulation_targets
from .notes import check_onsets, expected_onsets, notes_text


def main():
    F = Fraction

    def n(i, pos, dur, sp, stream=5, props=None):
        return Event(i, "kNoteEvent", stream, None, F(pos), F(dur), f"kNoteEvent (id:{i}) at {pos}  {sp}", props or {})

    items = parse_notes("Bb1+Bb2:e r Bb1+Bb2 C3:q")
    exp, end = expected_onsets(items, F(10))
    assert [(t, ps) for t, _, ps in exp] == [(10, ["Bb1", "Bb2"]), (11, ["Bb1", "Bb2"]), (F(23, 2), ["C3"])] and end == F(25, 2)
    good = [n(1, 10, "1/2", "Bb1"), n(2, 10, "1/2", "Bb2"), n(3, 11, "1/2", "Bb1"), n(4, 11, "1/2", "Bb2"), n(5, "23/2", 1, "C3")]
    assert check_onsets(exp, good) is None
    split = [n(1, 10, "1/2", "Bb1"), n(2, "21/2", "1/2", "Bb2")] + good[2:]  # first chord typed as two notes (seen live)
    assert check_onsets(exp, split).startswith("CHORDMODE"), check_onsets(exp, split)
    stacked = [n(i, 10, e.dur, e.spelling) for i, e in enumerate(good)]
    assert check_onsets(exp, stacked).startswith("CHORDMODE")
    wrong = good[:4] + [n(5, "23/2", 1, "D3")]
    assert not check_onsets(exp, wrong).startswith("CHORDMODE")
    assert check_onsets(exp, good[:4] + [n(5, "23/2", "1/2", "C3")]) and check_onsets(exp, good[:4] + [n(5, "23/2", "1/2", "C3")], durations=False) is None

    # two sextuplets of semiquavers (6:4 s): 12 notated semiquavers = 3 crotchets notated, 2 sounding
    six = parse_notes("Ab4:s Bb4 D5 F5 D5 Bb4 Ab4 Bb4 D5 F5 D5 Bb4")
    exp, end = expected_onsets(six, F(0), F(4, 6))
    assert end == 2 and exp[6][0] == 1 and sum((d for _, d in six), F(0)) / (6 * F(1, 4)) == 2

    chord = [n(1, 0, 1, "C4"), n(2, 0, 1, "E4"), n(3, 1, 1, "D4"), n(4, 2, 1, "F4", props={"kArticulationDuration": 0})]
    assert articulation_targets(chord, "staccato") == [1, 3]  # one note per chord; F4 already staccato
    assert articulation_targets(chord, "accent") == [1, 3, 4]
    assert notes_text(parse_notes("C4+E4:q. r:e D4")) == "C4+E4:3/2 r:1/2 D4:1/2"

    # replace/delete_range clear notes and rests only; the slur and text stay, an earlier note is shortened
    held, slur = n(10, 6, 3, "G4"), Event(11, "kSlurEvent", 5, 1, F(8), F(2), "kSlurEvent (id:11) at 8", source="dump")
    text = Event(12, "kTextEvent", 5, 1, F(8), F(0), "kTextEvent (id:12) at 8 : div. (paragraph.defaulttext)")
    tie = Event(13, "kTieEvent", 5, 1, F(7), F(2), "kTieEvent (id:13) at 7", source="dump")
    trill_voice = Event(14, "kNoteEvent", 5, 3, F(9), F(1), "kNoteEvent (id:14) at 9  A4", source="dump")
    st = clear_steps(0, [held, slur, text, tie, n(15, 8, 1, "B4"), trill_voice, n(16, 10, 1, "C5")], 5, F(8), F(10))
    assert st == [["delete_ids", 5, [15]], ["duration", 10, "2"],
                  ["cmd", "EventEdit.Delete?FlowID=0&EventID=13&EventBlockID=1"],
                  ["cmd", "EventEdit.Delete?FlowID=0&EventID=14&EventBlockID=3"]], st
    assert grid_for(F(1, 2), F(3, 2)) == F(1, 2) and grid_for(F(2), F(4)) == 1 and grid_for(F(3, 4)) == F(1, 4)
    try:
        grid_for(F(1, 3))
        raise AssertionError("a triplet position has no grid")
    except OpError:
        pass
    assert advance_steps(F(1, 2), F(3, 2)) == [["cmd", "NoteInput.MoveRight"]] * 3

    items = [{"type": "note", "pos": "0", "bar": 1, "beat": "0", "dur": "1", "pitches": ["D5"], "midi": [74], "ids": [1]},
             {"type": "chord", "pos": "1", "bar": 1, "beat": "1", "dur": "1", "pitches": ["F#4", "A4"], "midi": [66, 69], "ids": [2, 3]},
             {"type": "implicit rest", "pos": "2", "bar": 1, "beat": "2", "dur": "2"},
             {"type": "note", "pos": "4", "bar": 2, "beat": "1", "dur": "1/2", "pitches": ["E5"], "midi": [76], "ids": [4]}]
    assert reads.compact(items) == ({"1": "D5:1 F#4+A4 r:2", "2": "@1 E5:1/2"}, {"1": [1, [2, 3], None], "2": [4]})
    g = reads.grid([{"voice": 2, "items": items}, {"voice": 4, "items": items[:1]}], None, bar_regions([(F(0), "3/4", None)]))
    assert g["rows"] == [["1:0", "D5", "D5"], ["1:1", "F#4+A4", "."], ["2:1", "E5", "."]], g
    grp = Event(20, "kDynamicGroupEvent", 1, 1, F(4), F(4), "kDynamicGroupEvent (id:20) at 4  element ID = 3")
    parts = {"parts": [{"sub": 0, "pos": "4", "level": "p"}, {"sub": 1, "pos": "4", "hairpin": "cresc", "length": "2"},
                       {"sub": 2, "pos": "6", "level": "f"}]}
    assert reads.in_force([(grp, parts)], F(5)) == {"level": "p", "since_pos": "4", "in": {"hairpin": "cresc", "from": "4", "to": "6"}}
    assert reads.in_force([(grp, parts)], F(7)) == {"level": "f", "since_pos": "6"}

    class FakeSession:  # Dorico draws a hairpin's length from the gradual part of its dynamic group
        def __init__(self, merge):
            self.merge, self.undone, self.steps = merge, 0, []
            self.groups = {7: [{"id": 1, "props": {"kDynamicImmediateChangeIntensity": {"sealed": True}}}]}
            self.rc = self.bridge = self

        async def events(self, flow, streams=None, lo=None, hi=None):
            g = Event(90, "kDynamicGroupEvent", 1, 1, F(0), F(0), "kDynamicGroupEvent (id:90) at 0  element ID = 7")
            new = Event(91, "kDynamicGroupEvent", 1, 1, F(0), F(1), "kDynamicGroupEvent (id:91) at 0  element ID = 8",
                        {LENGTH: "1"})  # the event's own value, which Dorico does not draw
            return [g] + ([new] if 8 in self.groups else [])

        async def run(self, op, **kw):
            return {"dynamics": [{"id": k, "subs": v} for k, v in self.groups.items()]}

        async def transact(self, flow, steps, verify=None, streams=None, lo=None, hi=None):
            before = await self.events(0)
            self.steps.append(steps)
            part = {"id": 2, "props": {"kDynamicGradualChangeType": "0", LENGTH: "1/2"}}
            if steps[0][0] == "select":
                if self.merge:
                    self.groups[7] = self.groups[7] + [part]
                else:
                    self.groups[8] = [part]
            if steps[0][0] == "subprop":
                subs = self.groups[steps[0][1]]
                subs[-1] = {"id": 2, "props": {**subs[-1]["props"], LENGTH: steps[0][4]}}
            return {"before": before, "after": await self.events(0), "created": {}}

        async def undo(self):
            self.undone += 1

        async def regions(self, flow):
            return bar_regions([(F(0), "4/4", None)]), []

        def mark_written(self):
            pass

    a, b = n(1, 0, 1, "C4"), n(2, 2, 2, "E4")
    for merge, key, element in ((True, "merged_into", 7), (False, "created", 8)):
        fs = FakeSession(merge)
        r = asyncio.run(_add_hairpin(fs, 0, a.pos, b.end, "cresc", [["select", 5, 1]]))
        assert key in r and r["length"] == "4" and "warning" not in r and not fs.undone, (r, fs.steps)
        assert fs.steps[-1][0][:3] == ["subprop", element, 2] and fs.steps[-1][0][4] == "4", fs.steps
    print("ops self-check ok")


main()
