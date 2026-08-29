"""The second checkable claim: what the filter toggle actually buys, in decibels.

A toggle that does nothing measurable is a lie told with a checkbox, so the question this file
answers is how much quieter the alias is with the filter in front of the sampler, at several
frequencies and at every order the page offers.

THE NUMBER IS TAKEN AS A RATIO OF TWO RENDERS. The same tone is rendered twice, once with the
filter and once without, and both are measured at the alias frequency with `dft.amplitude_at`.
Everything that is not the filter cancels, including the window's gain and the amplitude the
oscillator was asked for.

AND IT IS CHECKED AGAINST TWO OTHER ROUTES. The coefficients predict the same number without
rendering anything, and `scripts/check_independent.py` predicts it a third time from the closed
form for a Butterworth, which never touches a coefficient. Two derivations that agree can be
wrong together. Three that agree, computed three ways, is a different kind of statement.

WHAT THE NUMBERS ARE, at 44100 Hz with the corner at nine tenths of Nyquist. Every one of these
is the ratio of two rendered signals, and `PUBLISHED` below is the same table in a form a test can
read, so the prose cannot drift away from the measurement:

    tone            order 2     order 4     order 6     order 8
    1.5 x Nyquist   -9.7 dB    -18.5 dB    -27.6 dB    -36.8 dB
    2.5 x Nyquist  -19.1 dB    -38.1 dB    -57.1 dB    -76.2 dB
    3.4 x Nyquist  -25.8 dB    -51.6 dB    -77.4 dB   -103.2 dB

An earlier draft of this table had four of the twelve figures wrong, because they were reasoned
out from the six decibels an octave rule rather than measured. The test below is what caught it.
"""

from __future__ import annotations

import math
import unittest

from foldback import biquad, dft, fold, reference, sampler

RATE = 44100.0
CORNER_FRACTION = 0.9
MULTIPLES = (1.5, 2.5, 3.4)
ORDERS = (2, 4, 6, 8)

# The table in the docstring above, and the one the README prints, in one place.
PUBLISHED = {
    (1.5, 2): -9.7, (1.5, 4): -18.5, (1.5, 6): -27.6, (1.5, 8): -36.8,
    (2.5, 2): -19.1, (2.5, 4): -38.1, (2.5, 6): -57.1, (2.5, 8): -76.2,
    (3.4, 2): -25.8, (3.4, 4): -51.6, (3.4, 6): -77.4, (3.4, 8): -103.2,
}


class WhatTheToggleBuys(unittest.TestCase):

    measured = None

    @classmethod
    def setUpClass(cls):
        cls.measured = {}
        for multiple in MULTIPLES:
            for order in ORDERS:
                frequency = multiple * RATE / 2.0
                cls.measured[(multiple, order)] = reference.measured_attenuation_db(
                    frequency, RATE, order, CORNER_FRACTION)

    def test_the_toggle_does_something_large_and_measurable(self):
        for (multiple, order), db in sorted(self.measured.items()):
            self.assertLess(db, -9.0,
                            f"{multiple} x Nyquist at order {order} only moved {db:.2f} dB")

    def test_every_measured_figure_matches_the_one_the_coefficients_predict(self):
        worst, where = 0.0, None
        for (multiple, order), db in self.measured.items():
            predicted = reference.predicted_attenuation_db(
                multiple * RATE / 2.0, RATE, order, CORNER_FRACTION)
            if abs(db - predicted) > worst:
                worst, where = abs(db - predicted), (multiple, order, db, predicted)
        self.assertLess(worst, 0.05, f"rendered and predicted differ by {worst:.4f} dB at {where}")

    def test_the_published_table_is_the_table_that_was_measured(self):
        """The figures in this file's own docstring, checked against the measurement.

        A table pasted into prose goes stale the moment the corner moves, and nothing notices
        unless something reads it back. This reads it back.
        """
        self.assertEqual(set(PUBLISHED), set(self.measured))
        for key, claimed in sorted(PUBLISHED.items()):
            self.assertAlmostEqual(self.measured[key], claimed, delta=0.06,
                                   msg=f"{key} is published as {claimed} and measured "
                                       f"{self.measured[key]:.2f}")

    def test_and_the_prose_table_above_is_that_same_table(self):
        """The docstring is read back, because a table nobody reads back is a table that rots."""
        for claimed in PUBLISHED.values():
            self.assertIn(f"{claimed:.1f} dB", __doc__,
                          f"{claimed:.1f} dB is in PUBLISHED and not in the docstring table")

    def test_each_step_up_in_order_roughly_doubles_the_decibels(self):
        """Butterworth sections multiply, so the decibels add, order by order."""
        for multiple in MULTIPLES:
            per_order = [self.measured[(multiple, order)] / order for order in ORDERS]
            self.assertLess(max(per_order) - min(per_order), 0.7,
                            f"{multiple} x Nyquist gives {per_order} dB per order")

    def test_a_steeper_filter_is_always_quieter(self):
        for multiple in MULTIPLES:
            for lower, higher in zip(ORDERS, ORDERS[1:]):
                self.assertLess(self.measured[(multiple, higher)],
                                self.measured[(multiple, lower)] - 5.0,
                                f"order {higher} was not clearly quieter than order {lower}")

    def test_a_tone_further_above_nyquist_is_taken_down_further(self):
        for order in ORDERS:
            for lower, higher in zip(MULTIPLES, MULTIPLES[1:]):
                self.assertLess(self.measured[(higher, order)],
                                self.measured[(lower, order)] - 5.0,
                                f"{higher} x Nyquist was not quieter than {lower} at order "
                                f"{order}")

    def test_it_lands_at_the_alias_frequency_and_not_at_the_one_that_was_asked_for(self):
        """The measurement is taken where the tone actually comes out, which is the whole point."""
        for multiple in MULTIPLES:
            frequency = multiple * RATE / 2.0
            alias = fold.alias_of(frequency, RATE)
            self.assertLess(alias, RATE / 2.0)
            self.assertGreater(frequency, RATE / 2.0)
            voice = sampler.Sampler(RATE, frequency, filter_on=False)
            voice.render(8192)
            self.assertAlmostEqual(dft.peak(voice.render(8192), RATE), alias,
                                   delta=RATE / 8192)


class WhatItCostsInTheAudibleBand(unittest.TestCase):
    """The part a checkbox does not tell you, which the page prints next to the control."""

    def test_the_corner_takes_real_signal_off_the_top_of_the_band(self):
        cost = {}
        for order in ORDERS:
            cascade = biquad.Cascade(order, CORNER_FRACTION * RATE / 2.0,
                                     RATE * sampler.DEFAULT_OVERSAMPLE)
            cost[order] = cascade.response_db(0.98 * RATE / 2.0)
        for order in ORDERS:
            self.assertLess(cost[order], -0.05,
                            f"order {order} costs {cost[order]:.3f} dB at 0.98 x Nyquist, which "
                            f"is less than the page admits to")
        for lower, higher in zip(ORDERS, ORDERS[1:]):
            self.assertLess(cost[higher], cost[lower],
                            "a steeper filter is supposed to cost more inside the band")

    def test_moving_the_corner_up_trades_the_cost_for_the_stopband(self):
        """There is no setting that gives a wall at Nyquist, and this is that statement."""
        frequency = 1.5 * RATE / 2.0
        rows = []
        for fraction in (0.8, 0.9, 0.95):
            cascade = biquad.Cascade(4, fraction * RATE / 2.0,
                                     RATE * sampler.DEFAULT_OVERSAMPLE)
            rows.append((cascade.response_db(0.98 * RATE / 2.0),
                         cascade.response_db(frequency)))
        for (cheap_cost, cheap_stop), (dear_cost, dear_stop) in zip(rows, rows[1:]):
            self.assertGreater(dear_cost, cheap_cost, "a higher corner should cost less inside")
            self.assertGreater(dear_stop, cheap_stop, "and should buy less outside")

    def test_a_butterworth_is_three_decibels_down_at_its_own_corner_wherever_it_is_put(self):
        for fraction in (0.8, 0.9, 0.95):
            for order in ORDERS:
                cascade = biquad.Cascade(order, fraction * RATE / 2.0,
                                         RATE * sampler.DEFAULT_OVERSAMPLE)
                self.assertAlmostEqual(cascade.response_db(fraction * RATE / 2.0),
                                       -10.0 * math.log10(2.0), places=6)


class TheReferenceBlockThePageIsBuiltWith(unittest.TestCase):

    def test_it_carries_both_rates_and_every_frequency_it_says_it_does(self):
        block = reference.build()
        self.assertEqual(set(block["alias"]), {"44100", "48000"})
        for rate_text, rows in block["alias"].items():
            rate = float(rate_text)
            self.assertEqual(len(rows), len(reference.ALIAS_MULTIPLES))
            for asked, heard in rows:
                self.assertAlmostEqual(heard, fold.alias_of(asked, rate), places=9)

    def test_it_includes_the_degenerate_frequencies_rather_than_avoiding_them(self):
        block = reference.build()
        degenerate = sum(1 for rate_text, rows in block["alias"].items()
                         for asked, _ in rows if fold.is_degenerate(asked, float(rate_text)))
        self.assertEqual(degenerate, 6, "three degenerate frequencies at each of two rates")

    def test_every_attenuation_row_is_a_real_measurement(self):
        block = reference.build()
        self.assertEqual(len(block["attenuation"]), len(reference.ATTENUATION_CASES))
        for row in block["attenuation"]:
            self.assertLess(row["db"], -9.0)
            self.assertAlmostEqual(
                row["db"],
                reference.predicted_attenuation_db(row["frequency"], row["rate"], row["order"]),
                delta=0.05)
            self.assertAlmostEqual(row["alias"], fold.alias_of(row["frequency"], row["rate"]),
                                   places=9)

    def test_nothing_in_it_would_break_the_script_element_it_is_written_into(self):
        import json
        body = json.dumps(reference.build())
        for character in ("<", ">", "&"):
            self.assertNotIn(character, body)

    def test_it_refuses_to_measure_silence(self):
        """At a degenerate frequency there is nothing to attenuate, and it says so."""
        with self.assertRaises(ValueError):
            reference.measured_attenuation_db(RATE, RATE, 4)


if __name__ == "__main__":
    unittest.main()
