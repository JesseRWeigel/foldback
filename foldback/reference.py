"""The numbers the page is checked against, computed here and embedded there.

The page can compute an alias frequency itself, and it can render a tone through Web Audio and
take a transform of the result. Those are two routes and they can still agree while both being
wrong, which is the failure this fleet has hit before: a page checked against the script that
generated it cannot catch a bug in the script. So a third set of numbers is computed HERE, by the
Python that the unit tests exercise, written into the page at build time, and compared against the
other two inside the reader's browser.

The frequencies are written out at full precision on purpose. A double survives the trip through
JSON and back into JavaScript unchanged as long as nobody rounds it, and the whole comparison is
worth nothing if the page is asked about a slightly different frequency than Python was.

THE DEGENERATE FREQUENCIES ARE IN THE LIST, not left out of it. At every whole multiple of half
the sample rate the sine samples to silence, and the page has to report silence there rather than
a peak. A reference list that quietly avoided those points would let a page that invents a peak
out of an empty spectrum pass.
"""

from __future__ import annotations

import math

from . import biquad, dft, fold, sampler

# Multiples of NYQUIST, not of the sample rate, because Nyquist is the line the page is about.
# Three of these land exactly on a fold boundary and sample to silence.
ALIAS_MULTIPLES = (0.5, 0.98, 1.0, 1.4, 2.0, 2.6, 3.0, 3.7, 5.3, 7.1)

RATES = (44100.0, 48000.0)

# (rate, multiple of Nyquist, filter order)
ATTENUATION_CASES = (
    (44100.0, 1.5, 2),
    (44100.0, 1.5, 4),
    (44100.0, 1.5, 8),
    (44100.0, 2.5, 4),
    (44100.0, 3.4, 4),
    (48000.0, 1.5, 4),
)

WARMUP = 8192
WINDOW = 8192


def measured_alias(frequency: float, rate: float):
    """The alias, measured from a rendered signal rather than computed from the formula."""
    voice = sampler.Sampler(rate, frequency, filter_on=False)
    voice.render(WARMUP)
    return dft.peak(voice.render(WINDOW), rate)


def measured_attenuation_db(frequency: float, rate: float, order: int,
                            cutoff_fraction: float = 0.9) -> float:
    """How much quieter the alias is with the filter in front of the sampler, in decibels.

    Both signals are rendered the same way and measured at the same frequency, so everything
    except the filter cancels out of the ratio.
    """
    alias = fold.alias_of(frequency, rate)
    quiet = []
    for filter_on in (False, True):
        voice = sampler.Sampler(rate, frequency, order=order, filter_on=filter_on,
                                cutoff_fraction=cutoff_fraction)
        voice.render(WARMUP)
        quiet.append(dft.amplitude_at(voice.render(WINDOW), rate, alias))
    if quiet[0] <= 0.0:
        raise ValueError("there was nothing to attenuate")
    return 20.0 * math.log10(quiet[1] / quiet[0])


def predicted_attenuation_db(frequency: float, rate: float, order: int,
                             cutoff_fraction: float = 0.9,
                             oversample: int = sampler.DEFAULT_OVERSAMPLE) -> float:
    """The same number from the filter's coefficients, without rendering anything."""
    cascade = biquad.Cascade(order, cutoff_fraction * rate / 2.0, rate * oversample)
    return cascade.response_db(frequency)


def build() -> dict:
    """The whole reference block that goes into the page."""
    alias = {}
    for rate in RATES:
        rows = []
        for multiple in ALIAS_MULTIPLES:
            frequency = multiple * fold.nyquist(rate)
            rows.append([frequency, fold.alias_of(frequency, rate)])
        alias[str(int(rate))] = rows

    attenuation = []
    for rate, multiple, order in ATTENUATION_CASES:
        frequency = multiple * fold.nyquist(rate)
        attenuation.append({
            "rate": rate,
            "frequency": frequency,
            "order": order,
            "alias": fold.alias_of(frequency, rate),
            "db": measured_attenuation_db(frequency, rate, order),
        })

    return {
        "note": "computed by foldback/reference.py, not by the page",
        "warmup": WARMUP,
        "window": WINDOW,
        "alias": alias,
        "attenuation": attenuation,
    }
