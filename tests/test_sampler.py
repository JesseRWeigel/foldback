"""The sampler, and the place it makes for a filter that Web Audio has nowhere to put.

Three claims live here and all three are checkable. With the filter off the output is the naive
oscillator, to a bound that was measured rather than hoped for. With the filter on the tone is
attenuated BEFORE it folds, which is the whole point and is why the filter runs at the internal
rate. And the state survives from one block to the next, because a filter reset every block
clicks once per block and a reader would blame the click on aliasing.
"""

from __future__ import annotations

import math
import pathlib
import unittest

from foldback import fold, sampler


class FilterOff(unittest.TestCase):

    def test_it_is_the_naive_oscillator_to_within_a_billionth(self):
        """Not bit for bit, and the first draft of sampler.py said it was.

        The phase here is accumulated one internal step at a time, so its rounding error grows
        with n, where evaluating sin(2*pi*f*n/fs) rounds once. Measured at 44100 on a tone at 1.5
        times Nyquist over 4096 samples: exactly half the values match to the last bit and the
        largest disagreement is 8.3e-12.
        """
        rate = 44100.0
        for frequency in (440.0, 11025.0, 33075.0, 57330.0, 156555.0):
            voice = sampler.Sampler(rate, frequency, filter_on=False)
            out = voice.render(4096)
            worst = max(abs(v - math.sin(2.0 * math.pi * frequency * n / rate))
                        for n, v in enumerate(out))
            self.assertLess(worst, 1e-9,
                            f"{frequency} Hz drifted {worst} from the closed form")

    def test_and_the_bound_is_not_zero_which_is_why_it_is_written_as_a_bound(self):
        rate, frequency = 44100.0, 33075.0
        voice = sampler.Sampler(rate, frequency, filter_on=False)
        out = voice.render(4096)
        exact = sum(1 for n, v in enumerate(out)
                    if v == math.sin(2.0 * math.pi * frequency * n / rate))
        self.assertLess(exact, len(out),
                        "if every value matched to the last bit the docstring is now wrong")
        self.assertGreater(exact, len(out) // 4)

    def test_the_amplitude_is_the_amplitude_that_was_asked_for(self):
        for amplitude in (1.0, 0.25, 0.01):
            voice = sampler.Sampler(44100.0, 1000.0, amplitude=amplitude)
            self.assertAlmostEqual(max(voice.render(2048)), amplitude, delta=amplitude * 1e-3)

    def test_a_starting_phase_is_honoured(self):
        voice = sampler.Sampler(44100.0, 1000.0, phase=math.pi / 2.0)
        self.assertAlmostEqual(voice.render(1)[0], 1.0, places=9)

    def test_the_degenerate_frequencies_really_do_come_out_silent(self):
        rate = 48000.0
        for k in range(1, 8):
            frequency = k * rate / 2.0
            self.assertTrue(fold.is_degenerate(frequency, rate))
            voice = sampler.Sampler(rate, frequency, filter_on=False)
            self.assertLess(max(abs(v) for v in voice.render(4096)), 1e-6,
                            f"{k} x Nyquist should sample to silence")


class Blocks(unittest.TestCase):

    def test_ten_blocks_are_one_long_block(self):
        for filter_on in (False, True):
            one = sampler.Sampler(44100.0, 33075.0, filter_on=filter_on)
            whole = one.render(10240)
            other = sampler.Sampler(44100.0, 33075.0, filter_on=filter_on)
            pieces = []
            for _ in range(10):
                pieces.extend(other.render(1024))
            self.assertEqual(whole, pieces, f"filter_on={filter_on}")

    def test_the_phase_wrap_does_not_move_the_signal(self):
        """Renders long enough for the wrap in render to fire many times."""
        rate, frequency = 44100.0, 997.0
        voice = sampler.Sampler(rate, frequency, filter_on=False)
        out = voice.render(200000)
        worst = max(abs(out[n] - math.sin(2.0 * math.pi * frequency * n / rate))
                    for n in range(0, 200000, 37))
        self.assertLess(worst, 1e-7, f"the wrap let the phase drift by {worst}")

    def test_rendering_nothing_returns_nothing_and_moves_nothing(self):
        voice = sampler.Sampler(44100.0, 1000.0)
        before = voice.phase
        self.assertEqual(voice.render(0), [])
        self.assertEqual(voice.phase, before)


class FilterOn(unittest.TestCase):

    def test_it_makes_a_tone_above_the_corner_quieter(self):
        rate, frequency = 44100.0, 33075.0
        loud = sampler.Sampler(rate, frequency, filter_on=False)
        loud.render(8192)
        quiet = sampler.Sampler(rate, frequency, filter_on=True)
        quiet.render(8192)
        self.assertLess(max(abs(v) for v in quiet.render(4096)),
                        0.5 * max(abs(v) for v in loud.render(4096)))

    def test_it_leaves_a_tone_well_below_the_corner_alone(self):
        rate, frequency = 44100.0, 1000.0
        voice = sampler.Sampler(rate, frequency, filter_on=True)
        voice.settle()
        self.assertAlmostEqual(max(abs(v) for v in voice.render(4096)), 1.0, delta=0.01)

    def test_a_higher_order_takes_more_off(self):
        rate, frequency = 44100.0, 33075.0
        levels = []
        for order in (2, 4, 6, 8):
            voice = sampler.Sampler(rate, frequency, order=order, filter_on=True)
            voice.settle()
            levels.append(max(abs(v) for v in voice.render(4096)))
        for quieter, louder in zip(levels[1:], levels):
            self.assertLess(quieter, louder * 0.9)

    def test_the_filter_sits_before_the_decimation_and_not_after_it(self):
        """The claim the whole file exists for, put where a test can reach it.

        A filter after the sampler sees a tone that has already folded to 11025 Hz, which is
        below its corner, so it would leave it almost untouched. A filter before the sampler sees
        it at 33075 Hz and takes it down. The difference between those two outcomes is what this
        measures, so moving the filter out of the oversampled loop cannot pass.
        """
        rate, frequency = 44100.0, 33075.0
        heard = fold.alias_of(frequency, rate)
        self.assertAlmostEqual(heard, 11025.0, places=6)

        before = sampler.Sampler(rate, frequency, order=4, filter_on=True)
        before.settle()
        level_before = max(abs(v) for v in before.render(4096))

        # The same filter, running at the OUTPUT rate on the already folded samples.
        naive = sampler.Sampler(rate, frequency, order=4, filter_on=False)
        naive.render(8192)
        from foldback import biquad
        after = biquad.Cascade(4, 0.9 * rate / 2.0, rate)
        for value in naive.render(8192):
            after.process(value)
        level_after = max(abs(after.process(v)) for v in naive.render(4096))

        self.assertLess(level_before, 0.2, "the filter before the sampler barely worked")
        self.assertGreater(level_after, 0.7, "the filter after the sampler was supposed to be "
                                             "nearly useless against an alias this low")

    def test_set_order_changes_the_order(self):
        voice = sampler.Sampler(44100.0, 33075.0, order=2)
        self.assertEqual(voice.order, 2)
        voice.set_order(8)
        self.assertEqual(voice.order, 8)
        self.assertEqual(len(voice.cascade.sections), 4)


class WhatTheModelCannotDo(unittest.TestCase):

    def test_the_internal_rate_has_its_own_nyquist_and_the_model_stops_there(self):
        """Eight times oversampling is a model of continuous, and it is honest to four times fs.

        Above four times the sample rate the tone folds INSIDE the oversampled domain, so the
        filter is handed a tone that is already at the wrong frequency and the whole demonstration
        stops meaning what it says. This pins where that starts rather than leaving it in prose.
        """
        rate = 44100.0
        internal = rate * sampler.DEFAULT_OVERSAMPLE
        self.assertEqual(internal, 352800.0)
        for multiple in (0.5, 1.0, 2.0, 3.5, 3.99):
            frequency = multiple * rate
            self.assertAlmostEqual(fold.alias_of(frequency, internal), frequency, places=6,
                                   msg=f"{multiple} x fs should be safe inside the model")
        for multiple in (4.01, 5.0, 8.0):
            frequency = multiple * rate
            self.assertLess(fold.alias_of(frequency, internal), frequency - 1.0,
                            f"{multiple} x fs should already have folded inside the model")

    def test_the_page_sweeps_no_further_than_that(self):
        """The slider's top is four times the sample rate, which is exactly the honest limit."""
        root = pathlib.Path(__file__).resolve().parent.parent
        text = (root / "page" / "index.html").read_text(encoding="utf-8")
        self.assertIn("function top() { return sampleRate * 4; }", text)


class Refusals(unittest.TestCase):

    def test_it_refuses_a_sample_rate_that_is_not_one(self):
        for rate in (0.0, -44100.0):
            with self.assertRaises(ValueError):
                sampler.Sampler(rate, 1000.0)

    def test_it_refuses_oversampling_below_one(self):
        for oversample in (0, -1):
            with self.assertRaises(ValueError):
                sampler.Sampler(44100.0, 1000.0, oversample=oversample)

    def test_it_refuses_a_corner_outside_the_band(self):
        for fraction in (0.0, 1.0, 1.5, -0.5):
            with self.assertRaises(ValueError):
                sampler.Sampler(44100.0, 1000.0, cutoff_fraction=fraction)


if __name__ == "__main__":
    unittest.main()
