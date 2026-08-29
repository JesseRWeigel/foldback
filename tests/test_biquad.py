"""The filter, checked against the analog prototype it is supposed to be.

The cookbook coefficients in `foldback/biquad.py` are one way to write a Butterworth lowpass.
There is a second way that never mentions a coefficient: the bilinear transform of the analog
Butterworth has magnitude

    |H(e^{jw})| = 1 / sqrt(1 + (tan(w/2) / tan(wc/2))^(2N))

and that closed form is what most of this file compares against. Two routes to the same curve,
sharing nothing but the two numbers that go in.

WHY THE PASSBAND MATTERS AS MUCH AS THE STOPBAND. A cascade of N/2 identical sections at
Q = 0.707 is the mistake this design exists to avoid, and it is invisible if only the stopband is
checked, because in the stopband it is a perfectly good rolloff. What it does wrong is droop in
the passband, several decibels down long before the corner, which on this page would take audible
signal off the top of the band while the checkbox still said the filter was working.
"""

from __future__ import annotations

import math
import unittest

from foldback import biquad


def analytic_db(frequency: float, cutoff: float, rate: float, order: int) -> float:
    """The Butterworth magnitude, from the bilinear transform, without any coefficients."""
    w = math.pi * frequency / (rate / 2.0)
    wc = math.pi * cutoff / (rate / 2.0)
    ratio = math.tan(w / 2.0) / math.tan(wc / 2.0)
    return -10.0 * math.log10(1.0 + ratio ** (2 * order))


class PoleQs(unittest.TestCase):

    def test_a_second_order_butterworth_has_the_one_q_everybody_knows(self):
        qs = biquad.butterworth_qs(2)
        self.assertEqual(len(qs), 1)
        self.assertAlmostEqual(qs[0], 1.0 / math.sqrt(2.0), places=12)

    def test_the_higher_orders_have_the_pairs_the_tables_print(self):
        self.assertEqual(len(biquad.butterworth_qs(4)), 2)
        for computed, printed in zip(biquad.butterworth_qs(4), (0.54120, 1.30656)):
            self.assertAlmostEqual(computed, printed, places=4)
        for computed, printed in zip(biquad.butterworth_qs(8),
                                     (0.50980, 0.60134, 0.89998, 2.56292)):
            self.assertAlmostEqual(computed, printed, places=4)

    def test_they_are_never_all_the_same(self):
        for order in (4, 6, 8):
            qs = biquad.butterworth_qs(order)
            self.assertGreater(max(qs) - min(qs), 0.1,
                               f"order {order} came out as identical sections")

    def test_it_refuses_an_order_it_cannot_build(self):
        for order in (0, 1, 3, 5, -2, 7):
            with self.assertRaises(ValueError, msg=f"order {order}"):
                biquad.butterworth_qs(order)


class Coefficients(unittest.TestCase):

    def test_a_lowpass_passes_dc_untouched(self):
        b0, b1, b2, a1, a2 = biquad.lowpass_coefficients(4000.0, 48000.0, 0.7071)
        self.assertAlmostEqual((b0 + b1 + b2) / (1.0 + a1 + a2), 1.0, places=9)

    def test_the_numerator_is_symmetric_as_a_lowpass_numerator_has_to_be(self):
        b0, b1, b2, _, _ = biquad.lowpass_coefficients(9000.0, 96000.0, 1.3)
        self.assertAlmostEqual(b0, b2, places=12)
        self.assertAlmostEqual(b1, 2.0 * b0, places=12)

    def test_it_refuses_a_cutoff_outside_the_band(self):
        for cutoff in (0.0, -100.0, 24000.0, 30000.0):
            with self.assertRaises(ValueError, msg=f"{cutoff} Hz at 48000"):
                biquad.lowpass_coefficients(cutoff, 48000.0, 0.7071)


class Response(unittest.TestCase):

    def test_it_matches_the_closed_form_everywhere(self):
        rate, cutoff = 352800.0, 19845.0     # eight times 44100, corner at 0.9 of Nyquist
        worst, where = 0.0, None
        for order in (2, 4, 6, 8):
            cascade = biquad.Cascade(order, cutoff, rate)
            for step in range(1, 400):
                frequency = step * (rate / 2.0) / 400.0
                difference = abs(cascade.response_db(frequency)
                                 - analytic_db(frequency, cutoff, rate, order))
                if difference > worst:
                    worst, where = difference, (order, frequency)
        self.assertLess(worst, 1e-6,
                        f"the cascade is {worst} dB from the closed form at {where}")

    def test_it_is_three_decibels_down_at_its_own_corner(self):
        """The definition of a Butterworth corner, and the cost the page prints next to it."""
        for order in (2, 4, 6, 8):
            cascade = biquad.Cascade(order, 19845.0, 352800.0)
            self.assertAlmostEqual(cascade.response_db(19845.0), -10.0 * math.log10(2.0),
                                   places=6, msg=f"order {order}")

    def test_it_passes_dc_and_the_bottom_of_the_band_untouched(self):
        cascade = biquad.Cascade(4, 19845.0, 352800.0)
        for frequency in (1.0, 100.0, 1000.0):
            self.assertAlmostEqual(cascade.response_db(frequency), 0.0, delta=0.001)

    def test_the_rolloff_is_at_least_six_decibels_an_octave_per_order(self):
        """And measurably more than that, which is the bilinear transform showing through.

        The page's order menu advertises 12, 24, 36 and 48 dB per octave, and those are the ANALOG
        numbers. A digital Butterworth is steeper, because the bilinear transform squeezes the
        whole infinite analog frequency axis into the band below Nyquist, so every octave near
        the top of the band covers more of the analog curve than an octave near the bottom.
        Measured here between two and four times the corner, on an internal rate of eight times
        44100, the slopes come out about 1.2 times the analog figure at every order. The menu is
        therefore conservative, which is the direction that does not overstate the filter.
        """
        rate, cutoff = 352800.0, 19845.0
        for order in (2, 4, 6, 8):
            cascade = biquad.Cascade(order, cutoff, rate)
            slope = cascade.response_db(2.0 * cutoff) - cascade.response_db(4.0 * cutoff)
            analog = 6.0206 * order
            self.assertGreater(slope, analog,
                               f"order {order} rolls off {slope:.2f} dB per octave")
            self.assertLess(slope / analog, 1.30,
                            f"order {order} came out {slope / analog:.3f} times the analog slope")
            self.assertGreater(slope / analog, 1.10,
                               f"order {order} came out {slope / analog:.3f} times the analog "
                               f"slope, which is closer to the analog prototype than measured")

    def test_the_slope_the_closed_form_predicts_is_the_slope_it_has(self):
        rate, cutoff = 352800.0, 19845.0
        for order in (2, 4, 6, 8):
            cascade = biquad.Cascade(order, cutoff, rate)
            measured = cascade.response_db(2.0 * cutoff) - cascade.response_db(4.0 * cutoff)
            predicted = (analytic_db(2.0 * cutoff, cutoff, rate, order)
                         - analytic_db(4.0 * cutoff, cutoff, rate, order))
            self.assertAlmostEqual(measured, predicted, places=6, msg=f"order {order}")

    def test_a_cascade_of_identical_sections_is_not_a_butterworth(self):
        """The mistake the pole Qs exist to avoid, measured rather than asserted.

        Measured at nine tenths of the corner, where this page actually puts its corner relative
        to Nyquist: a real fourth order Butterworth is 1.53 dB down and two identical sections at
        Q = 0.707 are 4.35 dB down. Nearly three decibels of signal taken off the top of the band
        for nothing, by a filter that looks correct in the stopband.
        """
        rate, cutoff = 352800.0, 19845.0
        honest = biquad.Cascade(4, cutoff, rate)
        naive = [biquad.Section(*biquad.lowpass_coefficients(cutoff, rate, 1.0 / math.sqrt(2.0)))
                 for _ in range(2)]

        def naive_db(frequency):
            z = complex(math.cos(-2.0 * math.pi * frequency / rate),
                        math.sin(-2.0 * math.pi * frequency / rate))
            total = 1.0
            for s in naive:
                total *= abs((s.b0 + s.b1 * z + s.b2 * z * z)
                             / (1.0 + s.a1 * z + s.a2 * z * z))
            return 20.0 * math.log10(total)

        near = 0.9 * cutoff
        self.assertAlmostEqual(honest.response_db(near), -1.53, delta=0.05)
        self.assertAlmostEqual(naive_db(near), -4.35, delta=0.05)
        self.assertGreater(honest.response_db(near) - naive_db(near), 2.5,
                           "the identical cascade is supposed to droop and it did not")

        # And it is not merely a shifted corner: at half the corner the honest one is flat to a
        # sixtieth of a decibel and the identical cascade is already half a decibel down.
        half = cutoff / 2.0
        self.assertAlmostEqual(honest.response_db(half), -0.016, delta=0.005)
        self.assertAlmostEqual(naive_db(half), -0.511, delta=0.01)

    def test_the_cascade_response_is_the_product_of_its_sections(self):
        cascade = biquad.Cascade(6, 19845.0, 352800.0)
        for frequency in (500.0, 19845.0, 60000.0):
            product = 1.0
            for section in cascade.sections:
                single = biquad.Cascade(2, 19845.0, 352800.0)
                single.sections = [section]
                product += single.response_db(frequency)
            self.assertAlmostEqual(cascade.response_db(frequency), product - 1.0, places=9)

    def test_a_magnitude_of_zero_reports_silence_rather_than_a_domain_error(self):
        cascade = biquad.Cascade(2, 19845.0, 352800.0)
        cascade.sections[0].b0 = cascade.sections[0].b1 = cascade.sections[0].b2 = 0.0
        self.assertEqual(cascade.response_db(1000.0), -math.inf)


class RunningSignalThroughIt(unittest.TestCase):

    def test_what_comes_out_matches_what_the_coefficients_predicted(self):
        """The third route: a real signal, filtered, and its amplitude measured afterwards."""
        from foldback import dft
        rate, cutoff, n = 352800.0, 19845.0, 8192
        for order in (2, 4, 8):
            for frequency in (5000.0, 19845.0, 40000.0, 70000.0):
                cascade = biquad.Cascade(order, cutoff, rate)
                for i in range(16384):        # let the transient go by
                    cascade.process(math.sin(2.0 * math.pi * frequency * i / rate))
                out = [cascade.process(math.sin(2.0 * math.pi * frequency * (16384 + i) / rate))
                       for i in range(n)]
                measured = 20.0 * math.log10(dft.amplitude_at(out, rate, frequency))
                self.assertAlmostEqual(measured, cascade.response_db(frequency), delta=0.05,
                                       msg=f"order {order} at {frequency} Hz")

    def test_state_carries_over_between_blocks(self):
        """Ten blocks are the same as one long one, which is what stops a click every block."""
        rate, cutoff = 352800.0, 19845.0
        signal = [math.sin(2.0 * math.pi * 30000.0 * i / rate) for i in range(4096)]
        one = biquad.Cascade(4, cutoff, rate)
        whole = [one.process(v) for v in signal]
        other = biquad.Cascade(4, cutoff, rate)
        pieces = []
        for start in range(0, 4096, 512):
            pieces.extend(other.process(v) for v in signal[start:start + 512])
        self.assertEqual(whole, pieces)

    def test_resetting_between_blocks_would_be_audible(self):
        """The same comparison with a reset in the middle, to show the test above has teeth."""
        rate, cutoff = 352800.0, 19845.0
        signal = [math.sin(2.0 * math.pi * 30000.0 * i / rate) for i in range(4096)]
        one = biquad.Cascade(4, cutoff, rate)
        whole = [one.process(v) for v in signal]
        other = biquad.Cascade(4, cutoff, rate)
        clicked = []
        for start in range(0, 4096, 512):
            other.reset()
            clicked.extend(other.process(v) for v in signal[start:start + 512])
        worst = max(abs(a - b) for a, b in zip(whole, clicked))
        self.assertGreater(worst, 1e-4, f"a reset every block changed nothing, worst {worst}")

    def test_reset_really_clears_the_state(self):
        cascade = biquad.Cascade(4, 19845.0, 352800.0)
        for i in range(1000):
            cascade.process(math.sin(i))
        cascade.reset()
        for section in cascade.sections:
            self.assertEqual((section.x1, section.x2, section.y1, section.y2), (0.0,) * 4)

    def test_a_fresh_cascade_answers_an_impulse_the_same_way_twice(self):
        first = biquad.Cascade(4, 19845.0, 352800.0)
        second = biquad.Cascade(4, 19845.0, 352800.0)
        a = [first.process(1.0 if i == 0 else 0.0) for i in range(64)]
        b = [second.process(1.0 if i == 0 else 0.0) for i in range(64)]
        self.assertEqual(a, b)
        self.assertGreater(sum(abs(v) for v in a), 0.0)


if __name__ == "__main__":
    unittest.main()
