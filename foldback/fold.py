"""Where a tone above Nyquist actually comes out.

THE WHOLE LESSON IS ONE LINE. A sine at frequency `f`, sampled at rate `fs`, produces exactly
the same sequence of numbers as a sine at

    alias(f, fs) = abs(f - round(f / fs) * fs)

and every sample rate, every frequency and every fold below is that expression and nothing else.

WHY THAT IS TRUE, in four lines, because the demo is worth nothing if the reader has to take it
on faith. Write f as k*fs + r, where k = round(f/fs) and r is what is left over, so r lies in
[-fs/2, +fs/2]. Then

    sin(2*pi*f*n/fs) = sin(2*pi*k*n + 2*pi*r*n/fs) = sin(2*pi*r*n/fs)

because n and k are whole numbers and a whole number of turns is no turn at all. And a sine at a
negative frequency is the same tone as a sine at the positive one, upside down, which is why the
absolute value is there and why the fold is inaudible as anything but pitch.

THREE PLACES THIS GOES WRONG, all three of them in the sabotage suite:

  `floor` instead of `round`. Then r is the fractional part, in [0, fs), and for f = 0.6*fs the
  formula answers 0.6*fs, which is above Nyquist and cannot be what came out of the sampler.

  A plus instead of a minus. The answer stops being a residue at all and grows without bound.

  A missing absolute value. Half of the answers come out negative, and a negative frequency is
  not a thing a spectrum analyser can show you.

BANKER'S ROUNDING IS HARMLESS HERE, AND ONLY HERE. Python's `round` sends 0.5 to 0 and 1.5 to 2;
JavaScript's `Math.round` sends both up. So the two languages pick DIFFERENT k at every half
integer ratio. They still agree on the answer, because the two candidate residues at a half
integer are +fs/2 and -fs/2, and the absolute value makes them the same number. That is worth
knowing rather than worth relying on, so `tests/test_fold.py` checks it at every half integer up
to 4*fs rather than trusting the argument.
"""

from __future__ import annotations


def nyquist(sample_rate: float) -> float:
    """Half the sample rate. The highest frequency the rate can carry without folding."""
    return sample_rate / 2.0


def alias_of(frequency: float, sample_rate: float) -> float:
    """The frequency that actually comes out when `frequency` is sampled at `sample_rate`."""
    if sample_rate <= 0:
        raise ValueError("sample rate must be positive")
    if frequency < 0:
        raise ValueError("frequency must not be negative")
    return abs(frequency - round(frequency / sample_rate) * sample_rate)


def folds_below(frequency: float, sample_rate: float) -> int:
    """How many times the tone has turned around on its way down.

    Zero while the tone is still under Nyquist, one after the first fold, and so on. This is the
    number the page prints next to the fold map, so a reader can see which leg of the zigzag the
    marker is sitting on.
    """
    if sample_rate <= 0:
        raise ValueError("sample rate must be positive")
    if frequency < 0:
        raise ValueError("frequency must not be negative")
    return int(frequency // (sample_rate / 2.0))


def is_degenerate(frequency: float, sample_rate: float, tolerance: float = 1e-9) -> bool:
    """True at the frequencies where a zero phase SINE samples to silence.

    At every whole multiple of fs/2 the sine is caught exactly on its zero crossings and the
    recorded signal is all zeros. Not a bug and not a rounding artefact: sin(pi*n) is zero for
    every whole n. A cosine at the same frequency comes out at full amplitude, alternating +1 and
    -1 at Nyquist and sitting at a constant +1 at fs, so the silence belongs to the phase and not
    to the frequency.

    Every measurement in this project has to know about these points, because "find the peak in
    the spectrum" has no answer when the spectrum is empty.
    """
    half = sample_rate / 2.0
    return abs(frequency / half - round(frequency / half)) < tolerance


def fold_map(sample_rate: float, top: float, steps: int):
    """The zigzag the page draws: (true frequency, heard frequency) along a sweep."""
    if steps < 2:
        raise ValueError("a map needs at least two points")
    return [(f, alias_of(f, sample_rate))
            for f in (top * i / (steps - 1) for i in range(steps))]
