#!/usr/bin/env python3
"""Run the page's own arithmetic under node and compare it against the Python, value by value.

THE PROBLEM THIS SOLVES. The tests in `tests/` check Python. The page a reader opens runs
JavaScript. Two implementations of the same formulas is two chances to be wrong, and the usual
outcome is that the tested one is right and the shipped one quietly is not.

So the JavaScript is not copied out of the page for this. It is EXTRACTED from `page/index.html`
between the two core markers, which is the same text the page hands to `addModule` to build its
AudioWorklet. There is one copy of that arithmetic in the repository and this is it, running.

WHAT IS COMPARED, and it is not only the headline formula:

  the fold, over the same sweep the tests use, including the degenerate boundaries
  the fold count and the degenerate flag
  the Butterworth pole Qs and the cookbook coefficients, digit for digit
  a cascade's response in decibels
  the RENDERED SAMPLES, one at a time, with the filter off and with it on
  the window, the transform, the peak finder and the single frequency amplitude

WHAT THE TOLERANCES ARE AND WHY THEY ARE NOT ZERO. Anything that is arithmetic on doubles agrees
exactly, and is required to. Anything downstream of a `sin` or a `cos` does not, because V8 ships
its own polynomial for those and CPython calls the platform libm, so the two disagree in the last
place or two. The bounds below were measured rather than guessed, and each one is written next to
the thing it bounds.

IF NODE IS NOT INSTALLED THIS FAILS. It does not skip. A skipped check and a passing check look
the same in a log a week later, and the whole point of this file is to stop the page and the
tests from drifting apart unnoticed.
"""

from __future__ import annotations

import json
import math
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from foldback import biquad, dft, fold, sampler  # noqa: E402

PAGE = ROOT / "page" / "index.html"
BEGIN = "// === FOLDBACK CORE BEGIN ==="
END = "// === FOLDBACK CORE END ==="

RATES = (44100.0, 48000.0)
SWEEP = tuple(i * 0.05 for i in range(1, 159))     # 0.05 to 7.90 times Nyquist
ORDERS = (2, 4, 6, 8)
CORNERS = (0.8, 0.9, 0.95)

# Every bound here was measured by running this file and reading the reported worst case. They are
# a little above what was seen, so an ordinary rebuild does not trip them and a changed formula
# does.
LIMITS = {
    "alias": 1e-9,          # pure arithmetic on doubles, measured at 0
    "folds": 0,             # integers, exact or nothing
    "degenerate": 0,        # a flag, exact or nothing
    "poleqs": 1e-15,        # cos only, measured at 0
    "coefficients": 1e-15,  # sin and cos, measured at 0
    "response": 1e-12,      # a chain of the above, measured at 2.6e-14
    "samples": 1e-12,       # sin once per internal step, measured at 1.6e-15
    "window": 1e-15,        # cos, measured at 5.6e-17
    "spectrum": 1e-9,       # a transform of a windowed sine, relative, measured at 2.2e-16
    "peak": 1e-6,           # hertz, after an interpolation on logarithms, measured at 0
    "amplitude": 1e-12,     # measured at 6.7e-16
}


def core_source() -> str:
    text = PAGE.read_text(encoding="utf-8")
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise SystemExit(f"{PAGE.name} must contain exactly one core block, "
                         f"found {text.count(BEGIN)} begin and {text.count(END)} end markers")
    body = text.split(BEGIN, 1)[1].split(END, 1)[0]
    # Comments are stripped before this search, because the block's own header says in prose that
    # it must never touch `document` or `window`, and a search over the raw text finds that
    # sentence and refuses the file for saying the right thing.
    code = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL))
    for forbidden in ("document.", "window.", "location.", "navigator.", "self.",
                      "getElementById", "requestAnimationFrame"):
        if forbidden in code:
            raise SystemExit(f"the core block uses {forbidden}, so an AudioWorklet running it "
                             f"would throw, and the page and this check would diverge")
    return BEGIN + body + END


DRIVER = r"""
const RATES = %RATES%;
const SWEEP = %SWEEP%;
const ORDERS = %ORDERS%;
const CORNERS = %CORNERS%;

const out = { alias: [], poleqs: {}, coefficients: [], response: [], samples: [],
              window: null, spectrum: [], peak: [], amplitude: [] };

for (const rate of RATES) {
  for (const multiple of SWEEP) {
    const f = multiple * rate / 2;
    out.alias.push([rate, multiple, FOLDBACK.aliasOf(f, rate),
                    FOLDBACK.foldsBelow(f, rate), FOLDBACK.isDegenerate(f, rate) ? 1 : 0]);
  }
}

for (const order of ORDERS) out.poleqs[order] = FOLDBACK.butterworthQs(order);

const internal = 44100 * 8;
for (const corner of CORNERS) {
  const cutoff = corner * 44100 / 2;
  for (const order of ORDERS) {
    const c = FOLDBACK.makeCascade(order, cutoff, internal);
    c.sections.forEach((s, i) => {
      out.coefficients.push([corner, order, i, s.b0, s.b1, s.b2, s.a1, s.a2]);
    });
    for (const m of [0.5, 0.98, 1.0, 1.5, 2.5, 3.4, 4.0]) {
      out.response.push([corner, order, m, FOLDBACK.cascadeResponseDb(c, m * 44100 / 2)]);
    }
  }
}

for (const rate of RATES) {
  for (const multiple of [0.5, 1.4, 2.6, 3.7]) {
    for (const filterOn of [false, true]) {
      const state = FOLDBACK.makeSampler({
        sampleRate: rate, frequency: multiple * rate / 2, amplitude: 1,
        filterOn: filterOn, order: 4, cutoffFraction: 0.9, oversample: 8
      });
      const warm = new Float64Array(8192);
      FOLDBACK.render(state, warm, warm.length);
      const block = new Float64Array(1024);
      FOLDBACK.render(state, block, block.length);
      out.samples.push([rate, multiple, filterOn ? 1 : 0, Array.from(block)]);
    }
  }
}

out.window = Array.from(FOLDBACK.hann(64));

{
  const n = 1024, rate = 44100;
  const values = new Float64Array(n);
  for (let i = 0; i < n; i++) values[i] = Math.sin(2 * Math.PI * 7000 * i / rate)
                                        + 0.3 * Math.sin(2 * Math.PI * 15000 * i / rate);
  out.spectrum = Array.from(FOLDBACK.magnitudes(values));
}

for (const rate of RATES) {
  for (const multiple of [0.3, 0.9, 1.4, 2.6, 3.7, 5.3]) {
    const state = FOLDBACK.makeSampler({
      sampleRate: rate, frequency: multiple * rate / 2, amplitude: 1,
      filterOn: false, order: 4, cutoffFraction: 0.9, oversample: 8
    });
    const warm = new Float64Array(8192);
    FOLDBACK.render(state, warm, warm.length);
    const block = new Float64Array(8192);
    FOLDBACK.render(state, block, block.length);
    out.peak.push([rate, multiple, FOLDBACK.peakOf(block, rate)]);
    const alias = FOLDBACK.aliasOf(multiple * rate / 2, rate);
    out.amplitude.push([rate, multiple, FOLDBACK.amplitudeAt(block, rate, alias)]);
  }
}

process.stdout.write(JSON.stringify(out));
"""


def run_node(source: str):
    node = shutil.which("node")
    if node is None:
        raise SystemExit(
            "node is not on the path, and this check runs the page's own JavaScript.\n"
            "Install it with: apt-get install nodejs   (or: nvm install 24)\n"
            "Without it the Python is still covered by tests/, and the page's copy of the same "
            "formulas is NOT compared against it, which is the one thing this step is for.")
    driver = (DRIVER
              .replace("%RATES%", json.dumps(list(RATES)))
              .replace("%SWEEP%", json.dumps(list(SWEEP)))
              .replace("%ORDERS%", json.dumps(list(ORDERS)))
              .replace("%CORNERS%", json.dumps(list(CORNERS))))
    with tempfile.TemporaryDirectory() as area:
        path = pathlib.Path(area) / "parity.mjs"
        path.write_text(source + "\n" + driver, encoding="utf-8")
        done = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=600)
    if done.returncode != 0:
        raise SystemExit(f"node exited {done.returncode}:\n{done.stderr[-2000:]}")
    return json.loads(done.stdout)


class Comparison:
    def __init__(self):
        self.worst = {}
        self.problems = []

    def check(self, what, left, right, where):
        gap = abs(left - right)
        if gap > self.worst.get(what, (-1.0, None))[0]:
            self.worst[what] = (gap, where)
        if gap > LIMITS[what]:
            self.problems.append(f"{what}: {where} python {left!r} node {right!r} gap {gap}")


def main() -> int:
    source = core_source()
    js = run_node(source)
    c = Comparison()

    for rate, multiple, alias, folds, degenerate in js["alias"]:
        frequency = multiple * rate / 2.0
        c.check("alias", fold.alias_of(frequency, rate), alias, f"{rate} x {multiple}")
        c.check("folds", fold.folds_below(frequency, rate), folds, f"{rate} x {multiple}")
        c.check("degenerate", int(fold.is_degenerate(frequency, rate)), degenerate,
                f"{rate} x {multiple}")

    for order_text, qs in js["poleqs"].items():
        for i, (mine, theirs) in enumerate(zip(biquad.butterworth_qs(int(order_text)), qs)):
            c.check("poleqs", mine, theirs, f"order {order_text} pole {i}")

    for corner, order, index, *values in js["coefficients"]:
        mine = biquad.design(order, corner * 44100.0 / 2.0, 44100.0 * 8)[index]
        for name, left, right in zip("b0 b1 b2 a1 a2".split(),
                                     (mine.b0, mine.b1, mine.b2, mine.a1, mine.a2), values):
            c.check("coefficients", left, right, f"corner {corner} order {order} {name}")

    for corner, order, multiple, db in js["response"]:
        cascade = biquad.Cascade(order, corner * 44100.0 / 2.0, 44100.0 * 8)
        c.check("response", cascade.response_db(multiple * 44100.0 / 2.0), db,
                f"corner {corner} order {order} at {multiple} x Nyquist")

    for rate, multiple, filter_on, block in js["samples"]:
        voice = sampler.Sampler(rate, multiple * rate / 2.0, order=4,
                                filter_on=bool(filter_on), cutoff_fraction=0.9)
        voice.render(8192)
        mine = voice.render(len(block))
        for i, (left, right) in enumerate(zip(mine, block)):
            c.check("samples", left, right,
                    f"{rate} x {multiple} filter {filter_on} sample {i}")

    for i, (left, right) in enumerate(zip(dft.hann(64), js["window"])):
        c.check("window", left, right, f"hann {i}")

    n, rate = 1024, 44100.0
    values = [math.sin(2.0 * math.pi * 7000.0 * i / rate)
              + 0.3 * math.sin(2.0 * math.pi * 15000.0 * i / rate) for i in range(n)]
    mine = dft.magnitudes(values)
    biggest = max(mine)
    for i, (left, right) in enumerate(zip(mine, js["spectrum"])):
        c.check("spectrum", left / biggest, right / biggest, f"bin {i}")

    for rate, multiple, peak in js["peak"]:
        voice = sampler.Sampler(rate, multiple * rate / 2.0, filter_on=False)
        voice.render(8192)
        block = voice.render(8192)
        c.check("peak", dft.peak(block, rate), peak, f"{rate} x {multiple}")

    for rate, multiple, amplitude in js["amplitude"]:
        voice = sampler.Sampler(rate, multiple * rate / 2.0, filter_on=False)
        voice.render(8192)
        block = voice.render(8192)
        alias = fold.alias_of(multiple * rate / 2.0, rate)
        c.check("amplitude", dft.amplitude_at(block, rate, alias), amplitude,
                f"{rate} x {multiple}")

    compared = (len(js["alias"]) * 3 + sum(len(v) for v in js["poleqs"].values())
                + len(js["coefficients"]) * 5 + len(js["response"])
                + sum(len(row[3]) for row in js["samples"]) + len(js["window"])
                + len(js["spectrum"]) + len(js["peak"]) + len(js["amplitude"]))
    print(f"{compared} values compared between the page's JavaScript and the tested Python")
    for what in sorted(c.worst):
        gap, where = c.worst[what]
        print(f"  {what:<13} worst {gap:.3e} at {where}, limit {LIMITS[what]:.0e}")
    for problem in c.problems[:20]:
        print(f"FAIL {problem}")
    if c.problems:
        print(f"FAIL {len(c.problems)} value(s) outside their limit")
        return 1
    print("the page and the tests are running the same arithmetic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
