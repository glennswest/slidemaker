"""Unit tests for the parts of slidemaker that need no GPU and no server.

Every case here is either something that shipped broken once, or something
whose failure would quietly corrupt a whole deck rather than raise.
"""
import os
import sys
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / 'bin'
pros = SourceFileLoader('pros', str(BIN / 'slidemaker-prosody')).load_module()
idx = SourceFileLoader('idx', str(BIN / 'slidemaker-clone-indextts.py')).load_module()


class SentenceSplitting(unittest.TestCase):
    def split(self, text, max_words=32):
        return pros.split_sentences(text, max_words)

    def test_plain(self):
        self.assertEqual(self.split("One. Two. Three."),
                         ["One.", "Two.", "Three."])

    def test_initialism_is_not_a_boundary(self):
        # Splitting inside "L.L.M." leaves fragments the model reads as
        # separate gasping sentences.
        out = self.split("I showed you L.L.M. Pager running a model. It works.")
        self.assertEqual(len(out), 2)
        self.assertIn("L.L.M. Pager", out[0])

    def test_abbreviation_is_not_a_boundary(self):
        out = self.split("Ask Dr. West about it. He knows.")
        self.assertEqual(out, ["Ask Dr. West about it.", "He knows."])

    def test_decimal_and_lowercase_continuation(self):
        self.assertEqual(len(self.split("It costs 1.5 million dollars today.")), 1)

    def test_long_sentence_splits_on_a_comma(self):
        long = ' '.join(['word'] * 20) + ', ' + ' '.join(['tail'] * 20) + '.'
        self.assertEqual(len(self.split(long, max_words=32)), 2)

    def test_empty(self):
        self.assertEqual(self.split("   "), [])


class Markers(unittest.TestCase):
    def segs(self, text, base=(0.5, 0.5)):
        os.environ['SM_E_STRUCT'] = '0'
        pros.CFG = pros.Config()
        return pros.build_segments(text, base)

    def test_energy_marker(self):
        s = self.segs("[e=0.9] Loud one. [e=0.2] Quiet one.")
        self.assertAlmostEqual(s[0]['energy'], 0.9)
        self.assertAlmostEqual(s[1]['energy'], 0.2)

    def test_energy_ramp(self):
        s = self.segs("[e=0.2>0.8] First line here. Second line here. "
                      "Third line here.")
        self.assertAlmostEqual(s[0]['energy'], 0.2)
        self.assertAlmostEqual(s[-1]['energy'], 0.8)
        self.assertLess(s[0]['energy'], s[1]['energy'])

    def test_valence_and_tone_words(self):
        s = self.segs("[v=-0.8] Bad news here. [bright] Good news here.")
        self.assertAlmostEqual(s[0]['valence'], -0.8)
        self.assertGreater(s[1]['valence'], 0)
        s = self.segs("[problem] It failed badly.")
        self.assertLess(s[0]['valence'], 0)

    def test_one_word_sentences_merge(self):
        # A lone word is synthesized as its own gasping fragment, so it is
        # folded into its neighbour rather than kept as a segment.
        s = self.segs("A full sentence here. Yes. Another full sentence.")
        self.assertEqual(len(s), 2)
        self.assertIn('Yes.', s[0]['text'])

    def test_beat_extends_the_gap(self):
        plain = self.segs("One sentence. Two sentence.")
        beat = self.segs("One sentence. [beat=0.9] Two sentence.")
        self.assertGreater(beat[0]['beat'], plain[0]['beat'])

    def test_markers_never_appear_in_spoken_text(self):
        for text in ("[e=0.9] Hello there.", "[v=-0.5] Hello there.",
                     "[problem] Hello there.", "[beat] Hello there.",
                     "[e=0.1>0.9] Hello there."):
            joined = ' '.join(s['text'] for s in self.segs(text))
            self.assertNotIn('[', joined, text)
            self.assertEqual(joined.strip(), 'Hello there.')

    def test_unrecognised_marker_is_never_spoken(self):
        # A mistyped directive must not reach the synthesizer, and must not
        # swallow the sentence boundary that follows it.
        s = self.segs("First one here. [e=?] Second one here.")
        joined = ' '.join(x['text'] for x in s)
        self.assertNotIn('[', joined)
        self.assertEqual(len(s), 2)

    def test_clamped(self):
        s = self.segs("[e=5.0] Over the top. [e=-3] Under the floor.")
        self.assertLessEqual(s[0]['energy'], 1.0)
        self.assertGreaterEqual(s[1]['energy'], 0.0)


class Annotation(unittest.TestCase):
    batch = [('03', ['a', 'b']), ('04', ['c'])]

    def test_single_array(self):
        reply = ('[{"slide":"03","i":1,"energy":0.4,"valence":0},'
                 '{"slide":"03","i":2,"energy":0.8,"valence":1},'
                 '{"slide":"04","i":1,"energy":0.5,"valence":-1}]')
        out = pros.parse_annotation(reply, self.batch)
        self.assertAlmostEqual(out['03'][1]['energy'], 0.8)
        self.assertAlmostEqual(out['04'][0]['valence'], -1.0)

    def test_one_array_per_slide(self):
        # The model answers either way; both must parse.
        reply = ('[{"slide":"03","i":1,"energy":0.4,"valence":0},'
                 '{"slide":"03","i":2,"energy":0.8,"valence":0}]\n\n'
                 '[{"slide":"04","i":1,"energy":0.5,"valence":0}]')
        out = pros.parse_annotation(reply, self.batch)
        self.assertAlmostEqual(out['03'][1]['energy'], 0.8)
        self.assertAlmostEqual(out['04'][0]['energy'], 0.5)

    def test_think_block_and_prose_are_ignored(self):
        reply = ('<think>let me consider [1,2,3]</think>\nSure:\n'
                 '[{"slide":"03","i":1,"energy":0.4,"valence":0}]')
        out = pros.parse_annotation(reply, self.batch)
        self.assertAlmostEqual(out['03'][0]['energy'], 0.4)

    def test_missing_sentence_inherits_rather_than_guesses(self):
        reply = '[{"slide":"03","i":1,"energy":0.9,"valence":1}]'
        out = pros.parse_annotation(reply, self.batch)
        self.assertAlmostEqual(out['03'][1]['energy'], 0.9)

    def test_no_array_raises(self):
        with self.assertRaises(ValueError):
            pros.parse_annotation("I could not do that", self.batch)


class Expansion(unittest.TestCase):
    def store(self, energies):
        return {'01': [{'energy': e, 'valence': 0.0, 'why': ''} for e in energies]}

    def test_compressed_reading_is_stretched(self):
        # The real failure: 70 of 125 sentences at 0.40, one at 0.80.
        es = [0.4] * 70 + [0.3] * 12 + [0.5] * 15 + [0.6] * 10 + [0.7] * 17 + [0.8]
        out = pros.expand_auto(self.store(es), '0.25:0.95')['01']
        got = [r['energy'] for r in out]
        self.assertLess(min(got), 0.35)
        self.assertGreater(max(got), 0.9)

    def test_order_is_preserved(self):
        es = [0.3, 0.4, 0.5, 0.6, 0.7]
        out = pros.expand_auto(self.store(es), '0.25:0.95')['01']
        got = [r['energy'] for r in out]
        self.assertEqual(got, sorted(got))

    def test_flat_input_is_left_alone(self):
        out = pros.expand_auto(self.store([0.5] * 10), '0.25:0.95')['01']
        self.assertTrue(all(r['energy'] == 0.5 for r in out))

    def test_too_few_sentences_left_alone(self):
        out = pros.expand_auto(self.store([0.2, 0.9]), '0.25:0.95')['01']
        self.assertEqual([r['energy'] for r in out], [0.2, 0.9])

    def test_disabled(self):
        out = pros.expand_auto(self.store([0.1, 0.4, 0.9]), '')['01']
        self.assertEqual([r['energy'] for r in out], [0.1, 0.4, 0.9])

    def test_stays_in_range(self):
        out = pros.expand_auto(self.store([0.0, 0.1, 0.5, 0.9, 1.0]), '0.25:0.95')['01']
        for r in out:
            self.assertGreaterEqual(r['energy'], 0.0)
            self.assertLessEqual(r['energy'], 1.0)


class Slew(unittest.TestCase):
    def test_bounds_are_honoured(self):
        os.environ.pop('SM_E_SLEW', None)
        cfg = pros.Config()
        segs = [{'rate': 0, 'pitch': 0, 'volume': 0, 'speed': 1.0},
                {'rate': 90, 'pitch': 90, 'volume': 90, 'speed': 3.0}]
        pros.slew(segs, cfg)
        # Integer rounding can overshoot a limit by half a step; anything
        # beyond that means the limiter is not being applied.
        self.assertLessEqual(segs[1]['rate'] - segs[0]['rate'], 3.5)
        self.assertLessEqual(segs[1]['pitch'] - segs[0]['pitch'], 2.0)
        self.assertLessEqual(segs[1]['volume'] - segs[0]['volume'], 3.5)
        self.assertLessEqual(segs[1]['speed'] - segs[0]['speed'], 0.031)

    def test_downward_jumps_limited_too(self):
        cfg = pros.Config()
        segs = [{'rate': 50, 'pitch': 50, 'volume': 50, 'speed': 2.0},
                {'rate': 0, 'pitch': 0, 'volume': 0, 'speed': 1.0}]
        pros.slew(segs, cfg)
        self.assertGreaterEqual(segs[1]['rate'], 47)


class Runs(unittest.TestCase):
    def seg(self, e, v=1.0):
        return {'energy': e, 'valence': v, 'text': 'x', 'gap': 0.2}

    def test_respects_max_runs(self):
        segs = [self.seg(e) for e in (0.1, 0.9, 0.1, 0.9, 0.1, 0.9, 0.2, 0.8)]
        self.assertLessEqual(len(idx.split_runs(segs, 3)), 3)

    def test_no_run_shorter_than_two(self):
        segs = [self.seg(e) for e in (0.1, 0.9, 0.15, 0.95, 0.2, 0.85)]
        for r in idx.split_runs(segs, 3):
            self.assertGreaterEqual(len(r['segs']), 2)

    def test_runs_never_straddle_a_valence_sign_change(self):
        segs = [self.seg(0.5, 1.0), self.seg(0.5, 1.0),
                self.seg(0.5, -1.0), self.seg(0.5, -1.0)]
        for r in idx.split_runs(segs, 3):
            signs = {s['valence'] < 0 for s in r['segs']}
            self.assertEqual(len(signs), 1)

    def test_every_sentence_survives_exactly_once(self):
        segs = [self.seg(e) for e in (0.1, 0.4, 0.9, 0.3, 0.7, 0.2)]
        for n in (1, 2, 3, 5):
            flat = [s for r in idx.split_runs(segs, n) for s in r['segs']]
            self.assertEqual(len(flat), len(segs))

    def test_empty(self):
        self.assertEqual(idx.split_runs([], 3), [])


class Emotion(unittest.TestCase):
    def vec(self, e, v, gain=1.6):
        return idx.emotion_vector(e, v, gain=gain)

    def test_neutral_is_not_flat(self):
        # Gating brightness on max(0, valence) drained every neutral
        # sentence, and a technical talk is mostly neutral.
        self.assertGreater(self.vec(0.8, 0.0)[0], 0.05)

    def test_energy_raises_brightness(self):
        self.assertGreater(self.vec(0.95, 1.0)[0], self.vec(0.45, 1.0)[0])

    def test_negative_valence_uses_the_down_axis(self):
        v = self.vec(0.7, -1.0)
        self.assertEqual(v[0], 0.0)          # happy off
        self.assertGreater(v[5], 0.0)        # melancholic
        self.assertGreater(v[2], 0.0)        # sad

    def test_anger_and_disgust_never_used(self):
        for e in (0.0, 0.5, 1.0):
            for val in (-1.0, 0.0, 1.0):
                v = self.vec(e, val)
                self.assertEqual(v[1], 0.0, 'angry')
                self.assertEqual(v[4], 0.0, 'disgusted')

    def test_within_range(self):
        for e in (0.0, 0.5, 1.0):
            for val in (-1.0, 0.0, 1.0):
                for g in (0.5, 1.6, 4.0):
                    for x in self.vec(e, val, gain=g):
                        self.assertGreaterEqual(x, 0.0)
                        self.assertLessEqual(x, 1.0)


class Pacing(unittest.TestCase):
    def test_low_energy_is_slower(self):
        # An earlier version routed tempo through the rate ease curve and
        # made the calm opening outrun the rest of the talk.
        self.assertLess(idx.pacing(0.2)[0], idx.pacing(0.8)[0])

    def test_low_energy_leaves_more_air(self):
        self.assertGreater(idx.pacing(0.2)[1], idx.pacing(0.9)[1])

    def test_peak_eases_back(self):
        self.assertLess(idx.pacing(1.0)[0], idx.pacing(0.85)[0])

    def test_weight_slows_further(self):
        self.assertLess(idx.pacing(0.6, -1.0)[0], idx.pacing(0.6, 1.0)[0])

class SynthRuns(unittest.TestCase):
    """Grouping for the neural-TTS path (issue #3)."""

    def seg(self, e, gap=0.2, beat=0.0, text='A sentence here.', jit=0):
        return {'energy': e, 'rate': 5 + jit, 'pitch': 2 + jit, 'volume': 3,
                'gap': gap, 'beat': beat, 'text': text}

    def test_similar_energy_merges(self):
        runs = pros.synth_runs([self.seg(0.5) for _ in range(4)])
        self.assertEqual(len(runs), 1)

    def test_jitter_does_not_prevent_merging(self):
        # Per-sentence jitter and run grouping would otherwise cancel out.
        segs = [self.seg(0.5, jit=j) for j in (0, 1, -1, 2)]
        self.assertEqual(len(pros.synth_runs(segs)), 1)

    def test_distant_energy_splits(self):
        self.assertEqual(len(pros.synth_runs([self.seg(0.2), self.seg(0.9)])), 2)

    def test_a_beat_ends_a_run(self):
        segs = [self.seg(0.5, beat=0.8), self.seg(0.5)]
        self.assertEqual(len(pros.synth_runs(segs)), 2)

    def test_run_gap_is_the_last_sentence_gap(self):
        segs = [self.seg(0.5, gap=0.2), self.seg(0.5, gap=0.9)]
        self.assertAlmostEqual(pros.synth_runs(segs)[0]['gap'], 0.9)

    def test_run_settings_are_the_mean(self):
        segs = [self.seg(0.5, jit=0), self.seg(0.5, jit=2)]
        self.assertEqual(pros.synth_runs(segs)[0]['rate'], 6)

    def test_no_text_is_lost(self):
        segs = [self.seg(0.5, text=f'Sentence number {i}.') for i in range(6)]
        segs[3]['energy'] = 0.95
        joined = ' '.join(r['text'] for r in pros.synth_runs(segs))
        for i in range(6):
            self.assertIn(f'Sentence number {i}.', joined)


if __name__ == '__main__':
    unittest.main(verbosity=1)
