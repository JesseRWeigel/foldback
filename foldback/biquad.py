"""The anti alias filter, in the form the browser actually has.

THE FILTER IS THE SAME OBJECT IN BOTH PLACES. Web Audio's `BiquadFilterNode` in `lowpass` mode is
the Audio EQ Cookbook second order section, and the coefficient formulas below are that section
written out, so the page and this file are running the same filter rather than two filters that
resemble each other. The page does not use a `BiquadFilterNode`, because the filter has to sit
BEFORE the sampler and Web Audio has no such place, but it runs these coefficients through the
same difference equation in the same order, and `scripts/browser_check.py` compares the two
sample by sample.

WHY A CASCADE AND NOT ONE SECTION. One second order section rolls off at twelve decibels an
octave, which at one and a half times Nyquist is worth about six decibels, and six decibels of
attenuation on an alias is a checkbox that changes almost nothing. Butterworth sections in series
multiply, so four sections give forty eight decibels an octave, and the page can offer orders two
through eight and show the reader what each one buys. The Q values are the Butterworth pole Qs,

    Q_k = 1 / (2 * cos((2k + 1) * pi / (2N)))    for k = 0 .. N/2 - 1

and the reason they are not all 0.707 is that a cascade of identical sections is not a
Butterworth filter, it is a filter whose passband droops long before the corner. With the right
Qs the passband is flat to the corner and the product of the sections is exactly the bilinear
transform of the analog Butterworth of order N. `scripts/check_independent.py` checks this
against the closed form, which shares no code with anything here.

WHAT THE CORNER COSTS AT NYQUIST, which is the honest part nobody puts on the checkbox. A
Butterworth is three decibels down at its corner, so a corner placed at Nyquist itself would take
three decibels off the top of the audible band. Placed below Nyquist it takes less off the top
and gives away some of the stopband. There is no setting that does both, and the page says so
next to the control rather than picking one and calling it correct.

THE STATE IS PER SECTION AND CARRIES OVER BETWEEN BLOCKS. A filter reset every audio block clicks
at every block boundary, which is audible and which would be blamed on aliasing by exactly the
reader this page is for.
"""

from __future__ import annotations

import cmath
import math


class Section:
    """One direct form I biquad, the shape Web Audio specifies for `BiquadFilterNode`."""

    __slots__ = ("b0", "b1", "b2", "a1", "a2", "x1", "x2", "y1", "y2")

    def __init__(self, b0, b1, b2, a1, a2):
        self.b0, self.b1, self.b2, self.a1, self.a2 = b0, b1, b2, a1, a2
        self.reset()

    def reset(self) -> None:
        self.x1 = self.x2 = self.y1 = self.y2 = 0.0

    def process(self, x: float) -> float:
        y = (self.b0 * x + self.b1 * self.x1 + self.b2 * self.x2
             - self.a1 * self.y1 - self.a2 * self.y2)
        self.x2, self.x1 = self.x1, x
        self.y2, self.y1 = self.y1, y
        return y


def butterworth_qs(order: int):
    """The pole Qs for a Butterworth cascade of the given even order."""
    if order < 2 or order % 2:
        raise ValueError(f"order {order} is not an even number of two or more")
    return [1.0 / (2.0 * math.cos((2 * k + 1) * math.pi / (2 * order)))
            for k in range(order // 2)]


def lowpass_coefficients(cutoff: float, rate: float, q: float):
    """The Audio EQ Cookbook lowpass, normalised by a0, exactly as Web Audio computes it."""
    if not 0.0 < cutoff < rate / 2.0:
        raise ValueError(f"a cutoff of {cutoff} Hz is not inside the band at {rate} Hz")
    w0 = 2.0 * math.pi * cutoff / rate
    cosine = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * q)
    a0 = 1.0 + alpha
    return ((1.0 - cosine) / 2.0 / a0, (1.0 - cosine) / a0, (1.0 - cosine) / 2.0 / a0,
            (-2.0 * cosine) / a0, (1.0 - alpha) / a0)


def design(order: int, cutoff: float, rate: float):
    """A Butterworth lowpass of the given order, as a list of sections in series."""
    return [Section(*lowpass_coefficients(cutoff, rate, q)) for q in butterworth_qs(order)]


class Cascade:
    """Sections in series, with state that survives from one block to the next."""

    def __init__(self, order: int, cutoff: float, rate: float):
        self.order = order
        self.cutoff = cutoff
        self.rate = rate
        self.sections = design(order, cutoff, rate)

    def reset(self) -> None:
        for section in self.sections:
            section.reset()

    def process(self, x: float) -> float:
        for section in self.sections:
            x = section.process(x)
        return x

    def response(self, frequency: float) -> float:
        """The magnitude at one frequency, from the coefficients rather than from a signal.

        Evaluated on the unit circle, section by section. This is one of the three routes to the
        same number that this project keeps apart on purpose: here from the coefficients, in the
        tests from the amplitude of a signal that has actually been through the filter, and in
        `scripts/check_independent.py` from the closed form for a Butterworth, which never looks
        at a coefficient at all.
        """
        z = cmath.exp(-2j * math.pi * frequency / self.rate)
        total = 1.0
        for s in self.sections:
            numerator = s.b0 + s.b1 * z + s.b2 * z * z
            denominator = 1.0 + s.a1 * z + s.a2 * z * z
            total *= abs(numerator / denominator)
        return total

    def response_db(self, frequency: float) -> float:
        magnitude = self.response(frequency)
        return -math.inf if magnitude <= 0.0 else 20.0 * math.log10(magnitude)
