"""The teaching claim, put through a measurement that could refute it.

The page tells a reader that a sine above Nyquist comes back down, and where. That claim is
arithmetic, so it is checkable, and this is where it gets checked. Every frequency below is
rendered into actual samples by `foldback.sampler`, transformed by `foldback.dft`, and the peak
of the spectrum is compared against `foldback.fold.alias_of`. Nothing here compares the formula
against itself.

WHAT IS COVERED. 1250 frequencies across two sample rates, from a fortieth of Nyquist up to
7.9 times it, which is seven reflections. The three kinds of boundary all appear on purpose:
Nyquist itself, the sample rate itself, and the multiples of both above them, where a zero phase
sine samples to silence and there is no peak to find.

THE TOLERANCE IS TIGHT ON PURPOSE. A whole bin, which is what a demonstration would usually ask
for, is loose enough that a wrong formula could pass. The worst error measured over the whole
sweep is 0.014 of a bin, so the bound here is a twentieth of a bin. `scripts/sabotage.py` breaks
the formula six ways and every one of them moves the answer by more than that.

WHERE IT IS LOOSER, AND WHY THAT IS WRITTEN DOWN. `dft.peak` is dragged sideways within about a
bin of DC or of Nyquist by the tone's own mirror image, which `tests/test_dft.py` measures. A
sweep that quietly left those frequencies out would be hiding the boundary cases, so instead they
are counted, held to half a bin, and the count is asserted to be small.
"""

from __future__ import annotations

import unittest

from foldback import dft, fold, sampler

RATES = (44100.0, 48000.0)
WARMUP = 8192
WINDOW = 8192
TIGHT_BINS = 0.05
NEAR_EDGE_BINS = 0.5
EDGE_GUARD_BINS = 2.0


STEPS = range(1, 633)


def frequency_at(rate, step):
    """One expression, called from everywhere.

    Written once and looked up by STEP rather than by frequency, because `96 * 0.0125` and `1.2`
    are different doubles and a dictionary keyed on the frequency then misses by a hair.
    """
    return step * 0.0125 * (rate / 2.0)


def sweep_frequencies(rate):
    """Every eightieth of Nyquist, from a fortieth of it up to 7.9 times it."""
    return [frequency_at(rate, step) for step in STEPS]


def render_and_measure(rate, frequency):
    voice = sampler.Sampler(rate, frequency, filter_on=False)
    voice.render(WARMUP)
    return dft.peak(voice.render(WINDOW), rate)


class TheFoldBack(unittest.TestCase):
    """Rendered once for the whole class, because 1264 renders is the expensive part."""

    measured = None

    @classmethod
    def setUpClass(cls):
        cls.measured = {}
        for rate in RATES:
            for step in STEPS:
                frequency = frequency_at(rate, step)
                cls.measured[(rate, step)] = render_and_measure(rate, frequency)

    def rows(self):
        for (rate, step), peak in self.measured.items():
            frequency = frequency_at(rate, step)
            yield rate, frequency, peak, fold.alias_of(frequency, rate)

    def test_the_sweep_is_as_wide_as_it_claims_to_be(self):
        """A tolerance means nothing without knowing what it was applied to."""
        self.assertEqual(len(self.measured), 1264)
        for rate in RATES:
            top = max(frequency_at(rate, s) for r, s in self.measured if r == rate)
            self.assertGreater(top / (rate / 2.0), 7.8)
            crossings = sum(1 for r, s in self.measured
                            if r == rate and fold.folds_below(frequency_at(rate, s), rate) > 0)
            self.assertGreater(crossings, 550, "most of the sweep should be above Nyquist")

    def test_every_peak_lands_where_the_formula_says(self):
        worst, where = 0.0, None
        near_edge = 0
        for rate, frequency, peak, expected in self.rows():
            spacing = rate / WINDOW
            if fold.is_degenerate(frequency, rate):
                self.assertIsNone(peak, f"{frequency} Hz at {rate} Hz should be silent")
                continue
            self.assertIsNotNone(peak, f"{frequency} Hz at {rate} Hz measured as silence")
            error = abs(peak - expected) / spacing
            edge = min(expected, rate / 2.0 - expected) / spacing
            if edge < EDGE_GUARD_BINS:
                near_edge += 1
                self.assertLess(error, NEAR_EDGE_BINS,
                                f"{frequency} Hz at {rate} Hz lands {edge:.2f} bins from an end "
                                f"and came out {error:.3f} bins off")
                continue
            if error > worst:
                worst, where = error, (rate, frequency, expected, peak)
        self.assertLess(worst, TIGHT_BINS,
                        f"worst disagreement {worst:.4f} bins at {where}")
        self.assertLess(near_edge, 40,
                        f"{near_edge} frequencies land within {EDGE_GUARD_BINS} bins of an end, "
                        f"which is more of the sweep than the loose bound should cover")

    def test_the_tolerance_could_have_failed(self):
        """A bound nothing ever approaches is a bound that proves nothing about the measurement.

        The sweep's worst error is a real number rather than zero, so the tight bound is doing
        work. If this ever fails because the error went to zero, the measurement has stopped
        measuring and the bound should be looked at rather than tightened.
        """
        worst = 0.0
        for rate, frequency, peak, expected in self.rows():
            if peak is None:
                continue
            spacing = rate / WINDOW
            edge = min(expected, rate / 2.0 - expected) / spacing
            if edge < EDGE_GUARD_BINS:
                continue
            worst = max(worst, abs(peak - expected) / spacing)
        self.assertGreater(worst, 0.001, f"worst error came out {worst}, which is suspiciously "
                                         f"good for a windowed transform")

    def test_every_degenerate_frequency_is_silent_and_there_are_the_right_number_of_them(self):
        silent = [(rate, frequency) for rate, frequency, peak, _ in self.rows() if peak is None]
        for rate, frequency in silent:
            self.assertTrue(fold.is_degenerate(frequency, rate),
                            f"{frequency} Hz at {rate} Hz was silent and should not have been")
        # Multiples of Nyquist at 0.0125 steps: every eightieth point, seven of them in range.
        self.assertEqual(len(silent), 14, "seven degenerate frequencies at each of two rates")

    def test_the_heard_frequency_never_leaves_the_band(self):
        for rate, frequency, peak, expected in self.rows():
            self.assertLessEqual(expected, rate / 2.0 + 1e-9)
            if peak is not None:
                self.assertLessEqual(peak, rate / 2.0 + rate / WINDOW)
                self.assertGreaterEqual(peak, -1e-9)

    def test_the_pitch_really_does_come_back_down(self):
        """The sentence a reader is supposed to leave with, as an assertion.

        Above Nyquist the frequency you hear is strictly less than the one you asked for, and by
        the time the sweep is at seven times Nyquist it is a seventh of it or less.
        """
        rate = 44100.0
        for step in (96, 152, 184, 288, 416, 592):
            frequency = frequency_at(rate, step)
            heard = self.measured[(rate, step)]
            self.assertGreater(frequency, rate / 2.0)
            self.assertIsNotNone(heard)
            self.assertLess(heard, frequency,
                            f"{frequency / (rate / 2.0):.3f} x Nyquist did not come down")

    def test_two_frequencies_a_reflection_apart_are_measured_as_the_same_pitch(self):
        """The mirror image the spectrum plot shows, measured on both sides of the mirror."""
        rate = 44100.0
        pairs = 0
        for step in (16, 32, 48, 64, 96, 112, 128, 144):
            mirrored = 320 - step          # 320 steps is four times Nyquist, so twice the rate
            low, high = frequency_at(rate, step), frequency_at(rate, mirrored)
            below, above = self.measured[(rate, step)], self.measured[(rate, mirrored)]
            self.assertIsNotNone(below, f"{low} Hz measured as silence")
            self.assertIsNotNone(above, f"{high} Hz measured as silence")
            self.assertAlmostEqual(below, above, delta=rate / WINDOW,
                                   msg=f"{low:.1f} Hz and {high:.1f} Hz should sound the same")
            pairs += 1
        self.assertEqual(pairs, 8)


class TheBoundariesOnTheirOwn(unittest.TestCase):
    """The degenerate points get their own tests, because they are where a demo tells lies."""

    def test_a_sine_at_nyquist_is_silence_and_a_cosine_at_nyquist_is_not(self):
        import math
        for rate in RATES:
            frequency = rate / 2.0
            voice = sampler.Sampler(rate, frequency, filter_on=False)
            voice.render(WARMUP)
            samples = voice.render(WINDOW)
            self.assertLess(max(abs(v) for v in samples), 1e-6)
            self.assertIsNone(dft.peak(samples, rate))
            cosine = [math.cos(2.0 * math.pi * frequency * n / rate) for n in range(WINDOW)]
            self.assertGreater(max(abs(v) for v in cosine), 0.99)

    def test_a_sine_at_the_sample_rate_itself_is_silence_and_the_formula_says_dc(self):
        for rate in RATES:
            self.assertAlmostEqual(fold.alias_of(rate, rate), 0.0, places=9)
            voice = sampler.Sampler(rate, rate, filter_on=False)
            voice.render(WARMUP)
            self.assertLess(max(abs(v) for v in voice.render(WINDOW)), 1e-6)

    def test_a_hair_either_side_of_nyquist_is_the_same_pitch(self):
        """The fold is continuous, so a hair above and a hair below have to meet."""
        for rate in RATES:
            spacing = rate / WINDOW
            offset = 40.0 * spacing
            below = render_and_measure(rate, rate / 2.0 - offset)
            above = render_and_measure(rate, rate / 2.0 + offset)
            self.assertAlmostEqual(below, above, delta=spacing / 10.0)
            self.assertAlmostEqual(below, rate / 2.0 - offset, delta=spacing / 10.0)

    def test_a_hair_either_side_of_the_sample_rate_is_the_same_pitch(self):
        for rate in RATES:
            spacing = rate / WINDOW
            offset = 40.0 * spacing
            below = render_and_measure(rate, rate - offset)
            above = render_and_measure(rate, rate + offset)
            self.assertAlmostEqual(below, above, delta=spacing / 10.0)
            self.assertAlmostEqual(below, offset, delta=spacing / 2.0)

    def test_the_silence_at_nyquist_is_a_knife_edge_and_not_a_fade(self):
        """A first draft of this test assumed the level faded towards Nyquist. It does not.

        Measured at 44100 over a 65536 sample window, the peak level of a sine one hertz below
        Nyquist is 1.000, and ten hertz below it is 1.000. The level only collapses within a
        hundredth of a hertz, and the reason is not that the tone is any quieter. A tone at
        fs/2 minus delta samples to a sine at fs/2 whose amplitude is modulated at delta, so what
        you see is a beat with a period of fs/delta samples. At ten hertz off, that period is 4410
        samples and the window contains fifteen whole beats, so the peak reaches full height. At a
        hundredth of a hertz off, the period is four and a half million samples and the window
        holds only the very beginning of the first swell.

        So the silence at a degenerate frequency has no width at all. It is one point, and the
        page has to handle it as a case rather than as a limit, which is why `is_degenerate` and
        the None from `dft.peak` both exist.
        """
        rate, window = 44100.0, 65536
        levels = {}
        for delta in (1000.0, 10.0, 1.0, 0.1, 0.01, 0.0):
            voice = sampler.Sampler(rate, rate / 2.0 - delta, filter_on=False)
            voice.render(WARMUP)
            levels[delta] = max(abs(v) for v in voice.render(window))
        for delta in (1000.0, 10.0, 1.0):
            self.assertGreater(levels[delta], 0.99,
                               f"{delta} Hz below Nyquist came out at {levels[delta]:.4f}")
        self.assertLess(levels[0.01], 0.2)
        # Not exactly zero, and the residue is the phase accumulator rather than any signal.
        # Measured at 6.5e-11 over 73728 samples, which is nine orders below the tone beside it.
        self.assertLess(levels[0.0], 1e-9)
        self.assertGreater(levels[0.01] / levels[0.0], 1e6,
                           "only the exact boundary is silent")


if __name__ == "__main__":
    unittest.main()
