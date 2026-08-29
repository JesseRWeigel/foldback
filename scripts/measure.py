#!/usr/bin/env python3
"""Everything this project claims, printed as one deterministic block of numbers.

WHY THIS EXISTS. `scripts/sabotage.py` breaks the code on purpose and asks whether anything
notices. Gate two of the three gate rule is "the measured output moved", and that gate needs a
measurement. This is it: one command, no arguments, no clock, no randomness, no paths, printing
the same characters every time it runs on correct code.

WHAT IS IN IT, and the rule for what belongs. Every line here is something a sabotage could get
wrong. The fold formula, the fold counts, the degenerate flags, the peak of a real transform of a
real rendered signal, the filter's pole Qs, its response from coefficients, the attenuation
measured as a ratio of two renders, the ABSOLUTE amplitude of a filtered tone, and a digest of
the samples themselves. If a sabotage survives, the first question is whether this block is too
narrow, and the answer is usually to widen it rather than to weaken the check that missed it.

THE ABSOLUTE AMPLITUDES ARE NOT REDUNDANT. The attenuation figures are a RATIO of two
measurements, so anything that scales both cancels out of them. Dropping the window's coherent
gain from `dft.amplitude_at` is exactly that kind of change, and it would be invisible here
without a line that reports an amplitude on its own.

THE PAGE'S JAVASCRIPT IS IN HERE TOO, and that is not decoration. The deliverable a reader opens
runs JavaScript, so a sabotage that changes only the page would move nothing in a measurement of
the Python alone, gate two would fail, and the honest looking conclusion would be that the page
cannot be attacked. It can. The core block is extracted from `page/index.html` and run under node,
and its answers are part of this block.

NOTHING IN THIS OUTPUT NAMES THIS MACHINE. No working directory, no home directory, no time, no
process id. `scripts/verify.sh` checks that, because a fingerprint that folds in its own path
passes gate two for free and the whole sabotage run is then void.
"""

from __future__ import annotations

import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pagecore  # noqa: E402
from foldback import biquad, dft, fold, reference, sampler  # noqa: E402

RATES = (44100.0, 48000.0)
WARMUP = 8192
WINDOW = 8192

# Multiples of NYQUIST. The whole numbers are the degenerate points where a sine samples to
# silence, and they are in the list rather than avoided, because a measurement that avoided them
# would let a page that invents a peak out of an empty spectrum through.
SWEEP = (0.05, 0.5, 0.9, 0.98, 1.0, 1.02, 1.25, 1.5, 1.75, 1.98, 2.0, 2.02,
         2.4, 2.6, 3.0, 3.2, 3.7, 4.0, 4.5, 5.3, 6.0, 6.4, 7.1, 7.9)

ORDERS = (2, 4, 6, 8)
CORNERS = (0.8, 0.9, 0.95)
ATTENUATION_MULTIPLES = (1.5, 2.5, 3.4)


def line(*parts):
    print(" ".join(str(p) for p in parts))


def report_the_fold():
    line("# the fold formula, and a transform of the samples it predicts")
    for rate in RATES:
        for multiple in SWEEP:
            frequency = multiple * fold.nyquist(rate)
            expected = fold.alias_of(frequency, rate)
            voice = sampler.Sampler(rate, frequency, filter_on=False)
            voice.render(WARMUP)
            samples = voice.render(WINDOW)
            peak = dft.peak(samples, rate)
            loudest = max(abs(v) for v in samples)
            line(f"fold rate={rate:.0f} mult={multiple:.2f} asked={frequency:.4f}",
                 f"formula={expected:.4f}",
                 f"peak={'silent' if peak is None else format(peak, '.4f')}",
                 f"folds={fold.folds_below(frequency, rate)}",
                 f"degenerate={int(fold.is_degenerate(frequency, rate))}",
                 f"loudest={loudest:.9f}")


def report_the_samples():
    line("# a digest of the samples themselves, so a change nothing else looks at still shows")
    for rate in RATES:
        for multiple in (0.5, 1.4, 2.6, 3.7):
            for filter_on in (False, True):
                voice = sampler.Sampler(rate, multiple * fold.nyquist(rate),
                                        filter_on=filter_on, order=4)
                voice.render(WARMUP)
                digest = hashlib.sha256()
                for value in voice.render(4096):
                    digest.update(format(value, ".12e").encode())
                line(f"samples rate={rate:.0f} mult={multiple:.2f}",
                     f"filter={int(filter_on)} sha={digest.hexdigest()[:24]}")


def report_block_continuity():
    line("# ten blocks against one long block, which is what stops a click every block")
    for filter_on in (False, True):
        one = sampler.Sampler(44100.0, 33075.0, filter_on=filter_on)
        whole = one.render(10240)
        other = sampler.Sampler(44100.0, 33075.0, filter_on=filter_on)
        pieces = []
        for _ in range(10):
            pieces.extend(other.render(1024))
        worst = max(abs(a - b) for a, b in zip(whole, pieces))
        line(f"blocks filter={int(filter_on)} worst={worst:.12e} identical={int(whole == pieces)}")


def report_the_naive_oscillator():
    line("# with the filter off, how close the output is to the closed form sine")
    import math
    rate = 44100.0
    for frequency in (440.0, 11025.0, 33075.0, 57330.0):
        voice = sampler.Sampler(rate, frequency, filter_on=False)
        out = voice.render(4096)
        worst = max(abs(v - math.sin(2.0 * math.pi * frequency * n / rate))
                    for n, v in enumerate(out))
        exact = sum(1 for n, v in enumerate(out)
                    if v == math.sin(2.0 * math.pi * frequency * n / rate))
        line(f"naive freq={frequency:.1f} worst={worst:.6e} exact={exact}")


def report_the_filter():
    line("# the filter, from its coefficients")
    for order in ORDERS:
        qs = " ".join(f"{q:.9f}" for q in biquad.butterworth_qs(order))
        line(f"poleqs order={order} qs={qs}")
    internal = 44100.0 * sampler.DEFAULT_OVERSAMPLE
    for corner in CORNERS:
        cutoff = corner * fold.nyquist(44100.0)
        for order in ORDERS:
            cascade = biquad.Cascade(order, cutoff, internal)
            cells = " ".join(f"{cascade.response_db(m * fold.nyquist(44100.0)):.6f}"
                             for m in (0.5, 0.98, 1.0, 1.5, 2.5, 3.4, 4.0))
            line(f"response corner={corner:.2f} order={order} db={cells}")


def report_the_toggle():
    line("# what the anti alias filter buys, as a ratio of two rendered signals")
    for rate in RATES:
        for multiple in ATTENUATION_MULTIPLES:
            frequency = multiple * fold.nyquist(rate)
            for order in ORDERS:
                measured = reference.measured_attenuation_db(frequency, rate, order, 0.9)
                predicted = reference.predicted_attenuation_db(frequency, rate, order, 0.9)
                line(f"toggle rate={rate:.0f} mult={multiple:.2f} order={order}",
                     f"measured={measured:.6f} predicted={predicted:.6f}",
                     f"gap={abs(measured - predicted):.6f}")


def report_absolute_amplitudes():
    line("# absolute amplitudes, because a ratio cancels anything that scales both sides")
    rate = 44100.0
    for multiple in (0.5, 1.5, 2.5):
        frequency = multiple * fold.nyquist(rate)
        alias = fold.alias_of(frequency, rate)
        for filter_on in (False, True):
            voice = sampler.Sampler(rate, frequency, order=4, filter_on=filter_on)
            voice.render(WARMUP)
            amplitude = dft.amplitude_at(voice.render(WINDOW), rate, alias)
            line(f"amplitude mult={multiple:.2f} filter={int(filter_on)}",
                 f"at={alias:.4f} value={amplitude:.9f}")


def report_the_transform():
    line("# the transform itself, COMPLEX, and not only the magnitudes taken from it")
    # A sign flip in the twiddle factor computes the conjugate transform, and for a real input
    # the conjugate has exactly the same magnitudes. So a block that reported only magnitudes
    # could not see that change at all, and a sabotage that reverses the transform would look
    # inert while `tests/test_dft.py` catches it immediately by comparing complex values. The
    # measurement was widened rather than the sabotage removed.
    import math
    n = 64
    values = [math.sin(2.0 * math.pi * 5.0 * i / n) + 0.4 * math.cos(2.0 * math.pi * 11.0 * i / n)
              for i in range(n)]
    spectrum = dft.fft(values)
    for i in (0, 1, 5, 11, 17, 32, 53, 59, 63):
        line(f"transform bin={i} re={spectrum[i].real:.9f} im={spectrum[i].imag:.9f}")


def report_the_edges():
    line("# how well the peak finder does near the two ends, where its own mirror overlaps it")
    rate, n = 48000.0, 4096
    spacing = rate / n
    import math
    for distance in (0.5, 1.0, 1.5, 2.5, 8.5):
        for side, frequency in (("low", distance * spacing),
                                ("high", (n // 2 - distance) * spacing)):
            values = [math.sin(2.0 * math.pi * frequency * i / rate) for i in range(n)]
            error = abs(dft.peak(values, rate) - frequency) / spacing
            line(f"edge side={side} bins={distance:.1f} error={error:.6f}")


def report_the_reference_block():
    line("# the block that is written into the page at build time")
    block = reference.build()
    for rate_text in sorted(block["alias"]):
        for asked, heard in block["alias"][rate_text]:
            line(f"reference rate={rate_text} asked={asked:.6f} heard={heard:.6f}")
    for row in block["attenuation"]:
        line(f"reference rate={row['rate']:.0f} order={row['order']}",
             f"frequency={row['frequency']:.6f} alias={row['alias']:.6f} db={row['db']:.6f}")


JAVASCRIPT_DRIVER = r"""
const out = [];
for (const rate of [44100, 48000]) {
  for (const m of [0.05, 0.5, 0.98, 1.0, 1.25, 1.5, 2.0, 2.6, 3.0, 3.7, 5.3, 7.1, 7.9]) {
    const f = m * rate / 2;
    out.push("js fold rate=" + rate + " mult=" + m.toFixed(2)
             + " alias=" + FOLDBACK.aliasOf(f, rate).toFixed(6)
             + " folds=" + FOLDBACK.foldsBelow(f, rate)
             + " degenerate=" + (FOLDBACK.isDegenerate(f, rate) ? 1 : 0));
  }
}
for (const order of [2, 4, 6, 8]) {
  out.push("js poleqs order=" + order + " qs="
           + FOLDBACK.butterworthQs(order).map(q => q.toFixed(9)).join(" "));
  const c = FOLDBACK.makeCascade(order, 0.9 * 44100 / 2, 44100 * 8);
  out.push("js response order=" + order + " db="
           + [0.5, 0.98, 1.0, 1.5, 2.5, 3.4, 4.0]
               .map(m => FOLDBACK.cascadeResponseDb(c, m * 44100 / 2).toFixed(6)).join(" "));
}
for (const rate of [44100, 48000]) {
  for (const m of [0.5, 1.4, 2.6, 3.7]) {
    for (const filterOn of [false, true]) {
      const state = FOLDBACK.makeSampler({
        sampleRate: rate, frequency: m * rate / 2, amplitude: 1,
        filterOn: filterOn, order: 4, cutoffFraction: 0.9, oversample: 8 });
      const warm = new Float64Array(8192);
      FOLDBACK.render(state, warm, warm.length);
      const block = new Float64Array(8192);
      FOLDBACK.render(state, block, block.length);
      const peak = FOLDBACK.peakOf(block, rate);
      const alias = FOLDBACK.aliasOf(m * rate / 2, rate);
      let sum = 0;
      for (let i = 0; i < block.length; i++) sum += Math.abs(block[i]);
      out.push("js sampled rate=" + rate + " mult=" + m.toFixed(2)
               + " filter=" + (filterOn ? 1 : 0)
               + " peak=" + (peak === null ? "silent" : peak.toFixed(6))
               + " sumabs=" + sum.toFixed(6)
               + " amplitude=" + FOLDBACK.amplitudeAt(block, rate, alias).toFixed(9));
    }
  }
}
{
  const n = 64;
  const re = new Float64Array(n), im = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    re[i] = Math.sin(2 * Math.PI * 5 * i / n) + 0.4 * Math.cos(2 * Math.PI * 11 * i / n);
  }
  FOLDBACK.fft(re, im);
  for (const i of [0, 1, 5, 11, 17, 32, 53, 59, 63]) {
    out.push("js transform bin=" + i + " re=" + re[i].toFixed(9) + " im=" + im[i].toFixed(9));
  }
}
process.stdout.write(out.join("\n") + "\n");
"""


def report_the_page_javascript():
    line("# the same questions, answered by the javascript the page actually ships")
    try:
        printed = pagecore.run(JAVASCRIPT_DRIVER)
    except pagecore.NoNode as missing:
        raise SystemExit(str(missing))
    sys.stdout.write(printed)


def main() -> int:
    digest = hashlib.sha256()

    class Tee:
        def write(self, text):
            digest.update(text.encode())
            return sys.__stdout__.write(text)

        def flush(self):
            sys.__stdout__.flush()

    sys.stdout = Tee()
    try:
        report_the_fold()
        report_the_samples()
        report_block_continuity()
        report_the_naive_oscillator()
        report_the_filter()
        report_the_toggle()
        report_absolute_amplitudes()
        report_the_transform()
        report_the_edges()
        report_the_reference_block()
        report_the_page_javascript()
    finally:
        sys.stdout = sys.__stdout__
    # On stderr on purpose, so a caller can capture the report and the fingerprint separately.
    print(f"FINGERPRINT {digest.hexdigest()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
