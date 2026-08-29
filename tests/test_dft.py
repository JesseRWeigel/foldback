"""The measuring instrument, checked before anything is measured with it.

Every claim about aliasing in this project is a claim about where a peak landed, so a transform
that is wrong makes every one of those claims wrong in the same direction and the agreement would
look like confirmation. The transform is therefore checked against a naive discrete transform
written out here in one line, and the peak finder is checked against tones placed at known
positions between bins.
"""

from __future__ import annotations

import cmath
import math
import unittest

from foldback import dft


def naive_dft(values):
    """The definition, transcribed. Order n squared, correct by construction, slow on purpose."""
    n = len(values)
    return [sum(complex(values[k]) * cmath.exp(-2j * math.pi * i * k / n) for k in range(n))
            for i in range(n)]


def pseudorandom(count, seed=12345):
    """A deterministic sequence, so a failure here is reproducible rather than occasional."""
    state = seed
    out = []
    for _ in range(count):
        state = (1103515245 * state + 12345) % (1 << 31)
        out.append(state / (1 << 30) - 1.0)
    return out


class Transform(unittest.TestCase):

    def test_it_agrees_with_the_definition(self):
        worst = 0.0
        for size in (2, 4, 8, 16, 32, 64, 128, 256):
            values = pseudorandom(size)
            fast, slow = dft.fft(values), naive_dft(values)
            for a, b in zip(fast, slow):
                worst = max(worst, abs(a - b))
        self.assertLess(worst, 1e-9, f"the transform is off by {worst} against the definition")

    def test_a_pure_tone_on_a_bin_centre_puts_everything_in_that_bin(self):
        n = 64
        for k in (1, 5, 17, 31):
            values = [math.cos(2.0 * math.pi * k * i / n) for i in range(n)]
            spectrum = dft.fft(values)
            for i, value in enumerate(spectrum):
                expected = n / 2.0 if i in (k, n - k) else 0.0
                self.assertAlmostEqual(abs(value), expected, places=6, msg=f"bin {i} of {n}")

    def test_it_refuses_a_length_it_cannot_transform(self):
        for size in (0, 3, 5, 6, 100, 1000):
            with self.assertRaises(ValueError, msg=f"length {size}"):
                dft.fft(pseudorandom(size) if size else [])

    def test_the_one_sided_spectrum_has_the_length_it_should(self):
        for size in (16, 256, 1024):
            self.assertEqual(len(dft.magnitudes(pseudorandom(size))), size // 2 + 1)


class Window(unittest.TestCase):

    def test_the_periodic_hann_starts_at_zero_and_does_not_end_there(self):
        """The periodic window and not the symmetric one, which is the one a transform wants."""
        w = dft.hann(8)
        self.assertAlmostEqual(w[0], 0.0, places=12)
        self.assertGreater(w[-1], 0.0)
        self.assertAlmostEqual(max(w), 1.0, places=12)

    def test_its_coherent_gain_is_half_its_length(self):
        for size in (8, 64, 1024):
            self.assertAlmostEqual(sum(dft.hann(size)), size / 2.0, places=6)

    def test_it_is_symmetric_about_its_middle(self):
        w = dft.hann(64)
        for i in range(1, 32):
            self.assertAlmostEqual(w[i], w[64 - i], places=12)

    def test_a_window_of_one_is_a_window_of_one(self):
        self.assertEqual(dft.hann(1), [1.0])

    def test_it_refuses_a_length_that_is_not_a_length(self):
        for size in (0, -1, -1024):
            with self.assertRaises(ValueError):
                dft.hann(size)


class Peak(unittest.TestCase):

    def test_it_finds_a_tone_sitting_exactly_on_a_bin(self):
        rate, n = 48000.0, 4096
        for k in (7, 100, 999, 2040):
            frequency = k * rate / n
            values = [math.sin(2.0 * math.pi * frequency * i / rate) for i in range(n)]
            self.assertAlmostEqual(dft.peak(values, rate), frequency, delta=1e-6)

    def test_it_finds_a_tone_anywhere_between_two_bins(self):
        """The claim in dft.py's docstring, measured: 0.016 of a bin at worst.

        A peak finder that read the nearest bin would be off by up to half a bin, which at this
        window is 5.9 Hz, and every alias measurement in this project would inherit that.
        """
        rate, n = 48000.0, 4096
        spacing = rate / n
        worst, worst_offset = 0.0, 0.0
        for step in range(0, 201):
            offset = step / 200.0
            frequency = (500 + offset) * spacing
            values = [math.sin(2.0 * math.pi * frequency * i / rate) for i in range(n)]
            error = abs(dft.peak(values, rate) - frequency) / spacing
            if error > worst:
                worst, worst_offset = error, offset
        self.assertLess(worst, 0.017,
                        f"the interpolated peak is off by {worst:.4f} bins at {worst_offset}")
        self.assertGreater(worst, 0.010,
                           "the docstring claims 0.016 of a bin, and a much better answer would "
                           "mean the docstring is stale rather than that all is well")

    def test_and_only_that_good_away_from_the_two_ends(self):
        """The limit dft.py documents, pinned so it cannot quietly change.

        This is the honest half of the interpolation claim. Within a bin of DC or of Nyquist the
        tone overlaps its own mirror image and the three bin fit is dragged sideways by about half
        a bin. Nothing here works around that. It is measured, written down, and the alias tests
        split their frequencies on it.
        """
        rate, n = 48000.0, 4096
        spacing = rate / n
        expected = [(0.5, 0.4, 0.6), (1.0, 0.4, 0.6), (1.5, 0.01, 0.05),
                    (2.5, 0.001, 0.01), (8.5, 0.0, 0.001)]
        for distance, low, high in expected:
            for frequency in (distance * spacing, (n // 2 - distance) * spacing):
                values = [math.sin(2.0 * math.pi * frequency * i / rate) for i in range(n)]
                error = abs(dft.peak(values, rate) - frequency) / spacing
                self.assertGreaterEqual(error, low,
                                        f"{distance} bins from an end came out at {error:.5f}")
                self.assertLessEqual(error, high,
                                     f"{distance} bins from an end came out at {error:.5f}")

    def test_the_interpolation_is_what_buys_that(self):
        """Reading the nearest bin instead is measurably worse, so the correction is not decor."""
        rate, n = 48000.0, 4096
        spacing = rate / n
        frequency = 500.5 * spacing
        values = [math.sin(2.0 * math.pi * frequency * i / rate) for i in range(n)]
        bins = dft.magnitudes(values)
        nearest = max(range(len(bins)), key=lambda i: bins[i]) * spacing
        self.assertGreater(abs(nearest - frequency) / spacing, 0.4)
        self.assertLess(abs(dft.peak(values, rate) - frequency) / spacing, 0.01)

    def test_silence_has_no_loudest_frequency(self):
        self.assertIsNone(dft.peak([0.0] * 1024, 48000.0))
        self.assertIsNone(dft.peak([], 48000.0))

    def test_a_signal_below_the_floor_reports_nothing_rather_than_a_number(self):
        rate, n = 48000.0, 1024
        tiny = [1e-12 * math.sin(2.0 * math.pi * 1000.0 * i / rate) for i in range(n)]
        self.assertIsNone(dft.peak(tiny, rate))

    def test_the_floor_can_be_lowered_if_a_caller_wants_it_lowered(self):
        rate, n = 48000.0, 1024
        tiny = [1e-12 * math.sin(2.0 * math.pi * 1500.0 * i / rate) for i in range(n)]
        found = dft.peak(tiny, rate, floor_ratio=1e-15)
        self.assertIsNotNone(found)
        self.assertAlmostEqual(found, 1500.0, delta=rate / n)


class AmplitudeAtOneFrequency(unittest.TestCase):

    def test_it_recovers_a_known_amplitude_on_a_bin_centre(self):
        rate, n = 48000.0, 8192
        for amplitude in (1.0, 0.25, 0.001):
            frequency = 400 * rate / n
            values = [amplitude * math.sin(2.0 * math.pi * frequency * i / rate)
                      for i in range(n)]
            self.assertAlmostEqual(dft.amplitude_at(values, rate, frequency), amplitude,
                                   delta=amplitude * 1e-6)

    def test_it_recovers_a_known_amplitude_between_bins_too(self):
        """This is the whole reason it exists. The filter measurement lands between bins."""
        rate, n = 48000.0, 8192
        spacing = rate / n
        worst = 0.0
        for step in range(0, 21):
            frequency = (400 + step / 20.0) * spacing
            values = [0.5 * math.sin(2.0 * math.pi * frequency * i / rate) for i in range(n)]
            worst = max(worst, abs(dft.amplitude_at(values, rate, frequency) - 0.5) / 0.5)
        self.assertLess(worst, 1e-5, f"off by {worst * 100:.4f} percent between bins")

    def test_reading_the_nearest_bin_instead_would_be_short_by_over_a_decibel(self):
        """The measurement behind the docstring's claim, kept as a test so it stays true."""
        rate, n = 48000.0, 8192
        spacing = rate / n
        frequency = 400.5 * spacing
        values = [math.sin(2.0 * math.pi * frequency * i / rate) for i in range(n)]
        bins = dft.magnitudes(values)
        window_gain = sum(dft.hann(n))
        nearest = 2.0 * max(bins) / window_gain
        error_db = abs(20.0 * math.log10(nearest))
        self.assertGreater(error_db, 1.0, "reading the nearest bin is supposed to be worse")
        self.assertLess(abs(dft.amplitude_at(values, rate, frequency) - 1.0), 1e-5)

    def test_the_coherent_gain_division_is_load_bearing(self):
        """Without it the answer is off by the window's gain, which is a factor of four."""
        rate, n = 48000.0, 4096
        frequency = 300 * rate / n
        values = [math.sin(2.0 * math.pi * frequency * i / rate) for i in range(n)]
        self.assertAlmostEqual(dft.amplitude_at(values, rate, frequency), 1.0, delta=1e-6)

    def test_it_refuses_the_two_ends_of_the_spectrum_rather_than_answering_wrongly(self):
        """A dormant guard, and the test that makes it possible to sabotage.

        Nothing in normal use asks for a frequency this close to an end, so removing the guard
        changes no measured output at all. It has to be attacked through a test that puts the
        question to it directly, which is what this is.
        """
        rate, n = 44100.0, 8192
        spacing = rate / n
        for frequency in (0.0, 1.0, 2.0, 3.9 * spacing,
                          rate / 2.0, rate / 2.0 - 1.0, rate / 2.0 - 3.9 * spacing):
            with self.assertRaises(ValueError, msg=f"{frequency} Hz should be refused"):
                dft.amplitude_at([0.0] * n, rate, frequency)

    def test_and_the_refusal_is_earned_rather_than_cautious(self):
        """The guard is only justified if the answer really is wrong there, so measure it.

        dft.py claims 56 percent high at 2 Hz in an 8192 point window at 44100. Reproduced here
        with the guard stepped around, because a guard nobody has tested is a guess.
        """
        rate, n = 44100.0, 8192
        frequency = 2.0
        values = [math.sin(2.0 * math.pi * frequency * i / rate) for i in range(n)]
        window = dft.hann(n)
        turn = -2.0 * math.pi * frequency / rate
        total = sum(v * w * cmath.exp(1j * turn * i)
                    for i, (v, w) in enumerate(zip(values, window)))
        unguarded = 2.0 * abs(total) / sum(window)
        self.assertGreater(unguarded, 1.4, f"expected a large overestimate, got {unguarded}")

    def test_it_refuses_an_empty_signal(self):
        with self.assertRaises(ValueError):
            dft.amplitude_at([], 44100.0, 1000.0)


if __name__ == "__main__":
    unittest.main()
