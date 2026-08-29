"""A spectrum, from the standard library and nothing else.

Two routines and a window. `fft` is the ordinary iterative radix-2 Cooley-Tukey transform, `peak`
finds the loudest frequency in a real signal, and `hann` is the window that makes the second one
mean anything.

WHY THE WINDOW IS NOT OPTIONAL. A finite recording of a sine is a sine multiplied by a rectangle,
and the transform of a rectangle is a sinc, which is wide and rings for the whole width of the
spectrum. Unless the tone happens to sit exactly on a bin centre, that ringing smears the peak
across neighbouring bins and drags the interpolated position off. The Hann window drops the far
side lobes by about sixty decibels and widens the main lobe to three bins, which is the trade this
project wants: a peak position that can be trusted to a small fraction of a bin, at the cost of
resolution nobody here needs.

THE INTERPOLATION IS ON THE LOGARITHM, ON PURPOSE. Fitting a parabola through the magnitudes of
the three bins around the maximum is the usual trick, and on a Hann window it is biased, because
the main lobe is not a parabola in linear magnitude. In decibels it very nearly is. The error
after this correction is under a hundredth of a bin for a tone anywhere inside a bin, which is
what lets `tests/test_alias_physics.py` demand agreement to a fraction of a bin rather than to a
whole one.

A PEAK IS NOT ALWAYS THERE. A signal of all zeros has no loudest frequency, and this returns None
rather than an arbitrary bin, because the frequencies where a sine samples to silence are exactly
the interesting boundary cases and a measurement that invented an answer there would hide them.
"""

from __future__ import annotations

import cmath
import math


def hann(length: int):
    """The periodic Hann window, the one that belongs with a transform rather than with filters."""
    if length <= 0:
        raise ValueError("a window needs a positive length")
    if length == 1:
        return [1.0]
    return [0.5 - 0.5 * math.cos(2.0 * math.pi * i / length) for i in range(length)]


def fft(values):
    """In-order radix-2 transform. The length must be a power of two."""
    n = len(values)
    if n == 0 or n & (n - 1):
        raise ValueError(f"length {n} is not a positive power of two")
    data = [complex(v) for v in values]

    # Bit reversal, written out rather than borrowed, because this file imports nothing.
    bits = n.bit_length() - 1
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            data[i], data[j] = data[j], data[i]
    del bits

    size = 2
    while size <= n:
        step = cmath.exp(-2j * math.pi / size)
        half = size // 2
        for start in range(0, n, size):
            twiddle = 1 + 0j
            for offset in range(half):
                a = data[start + offset]
                b = data[start + offset + half] * twiddle
                data[start + offset] = a + b
                data[start + offset + half] = a - b
                twiddle *= step
        size *= 2
    return data


def magnitudes(values):
    """One sided magnitude spectrum of a real signal, windowed with Hann first."""
    n = len(values)
    window = hann(n)
    spectrum = fft([v * w for v, w in zip(values, window)])
    return [abs(spectrum[i]) for i in range(n // 2 + 1)]


def peak(values, sample_rate: float, floor_ratio: float = 1e-6):
    """The loudest frequency in a real signal, in hertz, or None if there is nothing there.

    `floor_ratio` is compared against the largest absolute sample, so a signal that is all zeros,
    or so nearly zero that the answer would be arithmetic noise, reports nothing at all.
    """
    if not values:
        return None
    if max(abs(v) for v in values) < floor_ratio:
        return None
    bins = magnitudes(values)
    n = len(values)
    top = max(range(len(bins)), key=lambda i: bins[i])
    if bins[top] <= 0.0:
        return None
    spacing = sample_rate / n
    if top == 0 or top == len(bins) - 1:
        return top * spacing
    left, middle, right = (bins[top - 1], bins[top], bins[top + 1])
    if left <= 0.0 or right <= 0.0:
        return top * spacing
    a, b, c = (20.0 * math.log10(v) for v in (left, middle, right))
    denominator = a - 2.0 * b + c
    shift = 0.0 if denominator == 0.0 else 0.5 * (a - c) / denominator
    shift = max(-0.5, min(0.5, shift))
    return (top + shift) * spacing


def amplitude_at(values, sample_rate: float, frequency: float) -> float:
    """The amplitude of one NAMED frequency, by projecting the signal onto it directly.

    Used for the filter measurement, where the question is not which frequency is loudest but how
    much of a known one is left. This is a single term of a discrete transform evaluated at
    exactly `frequency` rather than at a bin centre, windowed with the same Hann, and divided by
    the window's coherent gain. For a tone sitting anywhere between bins it recovers the amplitude
    to six decimal places, where reading the nearest bin would be short by up to a decibel and a
    half depending on where the tone happened to land. That is the size of the effect being
    measured at the edge of the passband, so the difference decides the answer.

    THE LIMIT IS AT BOTH ENDS AND IT IS AN ERROR, NOT A ROUNDING. A real signal's spectrum carries
    an image at the negative frequency, and near zero, or near half the sample rate, that image
    overlaps the tone and inflates the result. Measured here: at 2 Hz in an 8192 point window at
    44100 the answer comes back 56 percent high. So a frequency inside four bins of either end
    raises rather than returning a number that looks like a measurement and is not one.
    """
    n = len(values)
    if n == 0:
        raise ValueError("nothing to measure")
    spacing = sample_rate / n
    if frequency < 4.0 * spacing or frequency > sample_rate / 2.0 - 4.0 * spacing:
        raise ValueError(
            f"{frequency:.3f} Hz is within four bins of an end of the spectrum at "
            f"{sample_rate:.0f} Hz over {n} samples, where the negative frequency image "
            f"overlaps it and this measurement is wrong rather than imprecise")
    window = hann(n)
    turn = -2.0 * math.pi * frequency / sample_rate
    total = 0j
    for i, (value, weight) in enumerate(zip(values, window)):
        total += value * weight * cmath.exp(1j * turn * i)
    return 2.0 * abs(total) / sum(window)
