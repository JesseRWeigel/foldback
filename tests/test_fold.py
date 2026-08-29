"""The fold formula, checked against properties rather than against itself.

Every test here could be written as "call alias_of and compare against alias_of", which would
pass on any implementation including a broken one. So none of them are. The comparisons are
against a SECOND formula written a different way, against invariants the answer has to satisfy
whatever the formula is, and against hand computed values for the cases a reader would check by
hand.
"""

from __future__ import annotations

import math
import unittest

from foldback import fold

RATES = (8000.0, 44100.0, 48000.0, 96000.0)


def triangle_alias(frequency: float, sample_rate: float) -> float:
    """The same number, from a different starting point.

    Instead of asking which multiple of the sample rate is nearest, this takes the remainder and
    reflects the top half of it back down, which is the picture rather than the algebra. It shares
    no line with `fold.alias_of`, so the two agreeing is evidence and not a tautology.
    """
    remainder = math.fmod(frequency, sample_rate)
    if remainder < 0.0:
        remainder += sample_rate
    return remainder if remainder <= sample_rate / 2.0 else sample_rate - remainder


class TheFormula(unittest.TestCase):

    def test_below_nyquist_nothing_happens(self):
        for rate in RATES:
            for step in range(1, 400):
                frequency = step * (rate / 2.0) / 400.0
                self.assertAlmostEqual(fold.alias_of(frequency, rate), frequency, places=9)

    def test_agrees_with_a_formula_written_the_other_way(self):
        worst = 0.0
        for rate in RATES:
            for step in range(0, 2001):
                frequency = step * (4.0 * rate) / 2000.0
                worst = max(worst,
                            abs(fold.alias_of(frequency, rate) - triangle_alias(frequency, rate)))
        self.assertLess(worst, 1e-6, f"the two derivations disagree by up to {worst} Hz")

    def test_the_answer_is_always_inside_the_band(self):
        for rate in RATES:
            for step in range(0, 4001):
                frequency = step * (9.0 * rate) / 4000.0
                heard = fold.alias_of(frequency, rate)
                self.assertGreaterEqual(heard, -1e-9)
                self.assertLessEqual(heard, rate / 2.0 + 1e-9)

    def test_moving_a_whole_sample_rate_changes_nothing(self):
        rate = 44100.0
        for base in (0.0, 137.0, 5000.0, 21000.0, 22049.5):
            expected = fold.alias_of(base, rate)
            for k in range(1, 12):
                self.assertAlmostEqual(fold.alias_of(base + k * rate, rate), expected, places=6)

    def test_it_is_a_mirror_about_every_multiple_of_the_rate(self):
        rate = 48000.0
        for k in range(1, 6):
            for offset in (1.0, 500.0, 9999.0, 23999.0):
                low = fold.alias_of(k * rate - offset, rate)
                high = fold.alias_of(k * rate + offset, rate)
                self.assertAlmostEqual(low, high, places=6)

    def test_the_worked_examples_a_reader_would_check_by_hand(self):
        cases = [
            (44100.0, 440.0, 440.0),
            (44100.0, 22050.0, 22050.0),
            (44100.0, 30870.0, 13230.0),      # 1.4 x Nyquist, folds once
            (44100.0, 44100.0, 0.0),          # the whole rate, down to DC
            (44100.0, 57330.0, 13230.0),      # 2.6 x Nyquist, folds twice, same pitch as 1.4
            (48000.0, 36000.0, 12000.0),
            (48000.0, 60000.0, 12000.0),
            (48000.0, 100.0, 100.0),
        ]
        for rate, asked, heard in cases:
            self.assertAlmostEqual(fold.alias_of(asked, rate), heard, places=6,
                                   msg=f"{asked} Hz at {rate} Hz")

    def test_two_tones_a_reflection_apart_are_the_same_pitch(self):
        """The claim the page makes out loud, stated as an equality rather than as a picture."""
        rate = 44100.0
        for offset in range(1, 22050, 137):
            self.assertAlmostEqual(fold.alias_of(rate - offset, rate),
                                   fold.alias_of(offset, rate), places=6)

    def test_half_integer_ratios_do_not_depend_on_the_rounding_convention(self):
        """Python rounds 0.5 to even and JavaScript rounds it up, and it does not matter.

        At a half integer ratio the two candidate residues are +fs/2 and -fs/2, so the absolute
        value makes both conventions give the same answer. This checks it at every half integer
        ratio up to four times the sample rate rather than trusting the argument, because the page
        runs the JavaScript convention and the tests run the Python one.
        """
        rate = 44100.0
        for k in range(0, 9):
            frequency = (k + 0.5) * rate
            floor_k = math.floor(frequency / rate)
            for candidate in (floor_k, floor_k + 1):
                self.assertAlmostEqual(abs(frequency - candidate * rate), rate / 2.0, places=6)
            self.assertAlmostEqual(fold.alias_of(frequency, rate), rate / 2.0, places=6)

    def test_a_floor_would_give_a_different_answer_above_half(self):
        """The sabotage this formula is most likely to suffer, shown to be detectable at all.

        If `round` were `floor` the answer for 0.6 times the sample rate would be 0.6 times the
        sample rate, which is above Nyquist and therefore cannot be what came out of a sampler.
        """
        rate = 44100.0
        frequency = 0.6 * rate
        floored = abs(frequency - math.floor(frequency / rate) * rate)
        self.assertGreater(floored, rate / 2.0)
        self.assertLessEqual(fold.alias_of(frequency, rate), rate / 2.0)

    def test_it_refuses_arguments_that_have_no_answer(self):
        with self.assertRaises(ValueError):
            fold.alias_of(1000.0, 0.0)
        with self.assertRaises(ValueError):
            fold.alias_of(1000.0, -44100.0)
        with self.assertRaises(ValueError):
            fold.alias_of(-1.0, 44100.0)


class Counting(unittest.TestCase):

    def test_nothing_has_folded_below_nyquist(self):
        for rate in RATES:
            for step in range(0, 200):
                self.assertEqual(fold.folds_below(step * (rate / 2.0) / 200.0, rate), 0)

    def test_the_count_goes_up_by_one_at_every_multiple_of_nyquist(self):
        rate = 44100.0
        for k in range(0, 9):
            self.assertEqual(fold.folds_below(k * rate / 2.0 + 1.0, rate), k)
            self.assertEqual(fold.folds_below((k + 1) * rate / 2.0 - 1.0, rate), k)

    def test_the_count_lands_exactly_on_the_boundary(self):
        rate = 48000.0
        for k in range(0, 9):
            self.assertEqual(fold.folds_below(k * rate / 2.0, rate), k)

    def test_it_refuses_arguments_that_have_no_answer(self):
        with self.assertRaises(ValueError):
            fold.folds_below(1000.0, 0.0)
        with self.assertRaises(ValueError):
            fold.folds_below(-1.0, 44100.0)


class Degenerate(unittest.TestCase):

    def test_every_multiple_of_half_the_rate_is_degenerate(self):
        for rate in RATES:
            for k in range(0, 17):
                self.assertTrue(fold.is_degenerate(k * rate / 2.0, rate),
                                f"{k} x Nyquist at {rate} Hz")

    def test_nothing_between_them_is(self):
        rate = 44100.0
        for k in range(0, 16):
            for through in (0.02, 0.25, 0.5, 0.75, 0.98):
                frequency = (k + through) * rate / 2.0
                self.assertFalse(fold.is_degenerate(frequency, rate), f"{frequency} Hz")

    def test_a_sine_really_is_silent_there_and_a_cosine_really_is_not(self):
        """The reason the flag exists, checked on the actual samples rather than on the flag."""
        rate = 44100.0
        for k in range(1, 8):
            frequency = k * rate / 2.0
            sine = [math.sin(2.0 * math.pi * frequency * n / rate) for n in range(2048)]
            cosine = [math.cos(2.0 * math.pi * frequency * n / rate) for n in range(2048)]
            self.assertLess(max(abs(v) for v in sine), 1e-8, f"{k} x Nyquist should be silent")
            self.assertGreater(max(abs(v) for v in cosine), 0.99, f"{k} x Nyquist as a cosine")

    def test_nyquist_alternates_and_the_sample_rate_sits_still(self):
        rate = 48000.0
        at_nyquist = [math.cos(2.0 * math.pi * (rate / 2.0) * n / rate) for n in range(8)]
        at_rate = [math.cos(2.0 * math.pi * rate * n / rate) for n in range(8)]
        for n, value in enumerate(at_nyquist):
            self.assertAlmostEqual(value, 1.0 if n % 2 == 0 else -1.0, places=9)
        for value in at_rate:
            self.assertAlmostEqual(value, 1.0, places=9)


class FoldMap(unittest.TestCase):

    def test_it_starts_at_the_origin_and_follows_the_diagonal_until_nyquist(self):
        rate = 44100.0
        points = fold.fold_map(rate, 4.0 * rate, 801)
        self.assertEqual(len(points), 801)
        self.assertEqual(points[0], (0.0, 0.0))
        for asked, heard in points:
            if asked <= rate / 2.0:
                self.assertAlmostEqual(asked, heard, places=6)
            self.assertLessEqual(heard, rate / 2.0 + 1e-9)

    def test_it_turns_around_the_right_number_of_times(self):
        """Count the direction changes in the zigzag and compare against the arithmetic."""
        rate = 44100.0
        points = fold.fold_map(rate, 4.0 * rate, 3201)
        turns = 0
        for i in range(1, len(points) - 1):
            before = points[i][1] - points[i - 1][1]
            after = points[i + 1][1] - points[i][1]
            if before * after < 0:
                turns += 1
        # Seven and not eight. A sweep from zero to four times the sample rate passes eight
        # multiples of Nyquist, and the last of them is the final point of the map, where there
        # is no next point to turn towards. Only the seven interior ones are turns.
        self.assertEqual(turns, 7, "seven interior reflections in four sample rates of sweep")

    def test_a_map_needs_at_least_two_points(self):
        with self.assertRaises(ValueError):
            fold.fold_map(44100.0, 44100.0, 1)


class Nyquist(unittest.TestCase):

    def test_it_is_half_the_rate(self):
        for rate in RATES:
            self.assertEqual(fold.nyquist(rate), rate / 2.0)


if __name__ == "__main__":
    unittest.main()
