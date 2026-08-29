"""A sampler with a place to put the anti alias filter.

WEB AUDIO HAS NO SUCH PLACE, which is the reason this class exists in both languages instead of
the page simply wiring a `BiquadFilterNode` in front of an oscillator. An anti alias filter is
defined by WHERE it sits: it belongs on the continuous signal, BEFORE the sampler, because once a
tone has folded there is nothing left in the recording to tell it apart from a tone that was
always down there. A filter after the sampler is a tone control. It removes the alias and the
honest signal at the same pitch with the same hand, and it teaches the reader the opposite of the
lesson.

So this makes a place. The signal is generated at `oversample` times the output rate, which
stands in for "continuous", the filter runs there, and every `oversample`-th filtered value is
kept. The reader can then hear both:

  FILTER OFF. Every internal sample is thrown away except the first of each frame, so the output
  is exactly `amplitude * sin(2*pi*f*n/fs + phase)`, which is the naive oscillator every beginner
  writes and the one that folds. Bit for bit the same as computing that expression directly, which
  `tests/test_sampler.py` checks rather than asserting in a comment.

  FILTER ON. The tone is attenuated at its TRUE frequency before it is ever sampled, so what folds
  down is what is left of it, and above the corner that is very little.

EIGHT TIMES IS NOT INFINITY, and the page says so. The internal rate is 8*fs, so this sampler can
only be honest about tones below 4*fs, and a tone above that folds INSIDE the oversampled domain
before the filter ever sees it. That is a real limit of the model rather than a spare parameter,
and `tests/test_sampler.py` pins the frequency at which it starts to matter.

THE FILTER STATE SURVIVES BETWEEN CALLS. Rendering ten blocks of 1024 gives the same samples as
rendering one block of 10240, which `tests/test_sampler.py` checks, because a filter reset at
every block boundary clicks once per block and the reader would hear it as aliasing.
"""

from __future__ import annotations

import math

from . import biquad

DEFAULT_OVERSAMPLE = 8
DEFAULT_ORDER = 4
DEFAULT_CUTOFF_FRACTION = 0.9


class Sampler:
    """A sine, an optional anti alias filter, and the decimation that samples them."""

    def __init__(self, sample_rate: float, frequency: float = 440.0,
                 oversample: int = DEFAULT_OVERSAMPLE, order: int = DEFAULT_ORDER,
                 cutoff_fraction: float = DEFAULT_CUTOFF_FRACTION,
                 filter_on: bool = False, amplitude: float = 1.0, phase: float = 0.0):
        if sample_rate <= 0:
            raise ValueError("sample rate must be positive")
        if oversample < 1:
            raise ValueError("oversampling must be at least one")
        if not 0.0 < cutoff_fraction < 1.0:
            raise ValueError("the cutoff must be a fraction of Nyquist between zero and one")
        self.sample_rate = float(sample_rate)
        self.oversample = int(oversample)
        self.internal_rate = self.sample_rate * self.oversample
        self.cutoff = cutoff_fraction * self.sample_rate / 2.0
        self.frequency = float(frequency)
        self.amplitude = float(amplitude)
        self.filter_on = bool(filter_on)
        self.phase = float(phase)
        self.cascade = biquad.Cascade(order, self.cutoff, self.internal_rate)

    @property
    def order(self) -> int:
        return self.cascade.order

    def set_order(self, order: int) -> None:
        self.cascade = biquad.Cascade(order, self.cutoff, self.internal_rate)

    def render(self, count: int):
        """The next `count` output samples, at `sample_rate`."""
        step = 2.0 * math.pi * self.frequency / self.internal_rate
        out = [0.0] * count
        phase = self.phase
        for n in range(count):
            for i in range(self.oversample):
                value = self.amplitude * math.sin(phase)
                if self.filter_on:
                    value = self.cascade.process(value)
                if i == 0:
                    out[n] = value
                phase += step
            # Kept inside the loop rather than folded into one multiplication at the end, so that
            # the JavaScript in the page can do exactly this and be compared sample by sample.
            # Wrapping here rather than letting the accumulator grow keeps the two languages from
            # drifting apart in the last bits after a few million samples.
            if phase > 2.0 * math.pi:
                phase -= 2.0 * math.pi * math.floor(phase / (2.0 * math.pi))
        self.phase = phase
        return out

    def settle(self, samples: int = 4096) -> None:
        """Run the filter until its startup transient is over, and throw the result away."""
        self.render(samples)
