#!/usr/bin/env python3
"""Break the arithmetic on purpose, and check that something notices.

THREE GATES. A sabotage counts only if it APPLIES (the text it edits is present, exactly once,
in every file it names), MOVES the fingerprint that `scripts/measure.py` prints, and is then
CAUGHT by at least one check. Two of three is not a pass. A sabotage that applies and moves
nothing means the measurement is too narrow, and the repair is to widen the measurement rather
than to soften the check that missed it.

AND A NULL CONTROL, RUN FIRST. An untouched copy of the tree, in a DIFFERENTLY NAMED directory,
must fingerprint identically to the original. Without that, a fingerprint that folded in its own
working directory would pass gate two automatically for every sabotage below while measuring
nothing at all. That happened in this fleet on 2026-08-06 and invalidated eleven sabotages that
had been scored as proven. If the control disagrees, this aborts rather than reporting a score.

EXACTLY ONCE, IN EVERY FILE. The trap that has bitten this fleet repeatedly is anchoring on text
that appears more than once, so the edit lands in a copy nothing runs. The formulas here exist in
two languages and the JavaScript exists in two files, `page/index.html` which every check runs and
`docs/index.html` which the browser opens. So `apply` requires the anchor to appear exactly once
per file and refuses otherwise, and the JavaScript sabotages name BOTH files, which also stops
them from being caught trivially by the published page being out of date.

FOUR CATCHERS, ALL OF THEM RUN, and which ones fired is reported. Short circuiting on the first
failure would be faster and would hide the more interesting fact, which is whether the unit tests
would have caught something on their own or whether only the cross language comparison did.

  tests         `python3 -m unittest discover`
  parity        the page's JavaScript against the Python, value by value
  independent   the closed forms, importing nothing from the package
  browser       the published page in real headless Chrome

DORMANT SABOTAGES INVERT GATE TWO. Code that is dormant while the input is correct, such as the
guard in `dft.amplitude_at` that refuses a frequency too near an end of the spectrum, cannot move
a fingerprint taken over correct input. For those the requirement is the opposite and stricter:
the fingerprint must NOT move and the unit suite must fail anyway.
"""

from __future__ import annotations

import concurrent.futures
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKERS = int(os.environ.get("FOLDBACK_SABOTAGE_WORKERS", "3"))

JS_FILES = ("page/index.html", "docs/index.html")


def _run(argv, tree, timeout=1800):
    return subprocess.run(argv, cwd=tree, capture_output=True, text=True, timeout=timeout)


def fingerprint(tree):
    done = _run([sys.executable, "scripts/measure.py"], tree)
    if done.returncode != 0:
        return None
    for line in done.stderr.splitlines():
        if line.startswith("FINGERPRINT "):
            return line.split()[1]
    return None


CATCHERS = (
    ("tests", [sys.executable, "-W", "ignore::ResourceWarning", "-m", "unittest",
               "discover", "-s", "tests", "-t", "."]),
    ("parity", [sys.executable, "scripts/parity.py"]),
    ("independent", [sys.executable, "scripts/check_independent.py"]),
    ("browser", [sys.executable, "scripts/browser_check.py"]),
)


def who_catches(tree):
    """Every catcher, run, and the names of the ones that failed."""
    return [name for name, argv in CATCHERS if _run(argv, tree).returncode != 0]


# (name, file or files, find, replace, dormant)
SABOTAGES = [

    # ------------------------------------------------------------------ the fold, in python
    ("the nearest multiple becomes the one below it, so a tone at 0.6 of the rate stays above "
     "nyquist", "foldback/fold.py",
     "    return abs(frequency - round(frequency / sample_rate) * sample_rate)",
     "    return abs(frequency - int(frequency / sample_rate) * sample_rate)", False),
    ("the residue is added rather than subtracted, so the answer grows without bound",
     "foldback/fold.py",
     "    return abs(frequency - round(frequency / sample_rate) * sample_rate)",
     "    return abs(frequency + round(frequency / sample_rate) * sample_rate)", False),
    ("the absolute value goes, so half the answers are negative frequencies",
     "foldback/fold.py",
     "    return abs(frequency - round(frequency / sample_rate) * sample_rate)",
     "    return (frequency - round(frequency / sample_rate) * sample_rate)", False),
    ("the fold is about half the sample rate rather than about the whole of it",
     "foldback/fold.py",
     "    return abs(frequency - round(frequency / sample_rate) * sample_rate)",
     "    return abs(frequency - round(frequency / sample_rate) * sample_rate / 2.0)", False),
    ("the fold count rounds instead of flooring, so it steps early", "foldback/fold.py",
     "    return int(frequency // (sample_rate / 2.0))",
     "    return int(round(frequency / (sample_rate / 2.0)))", False),
    ("the degenerate points are looked for at multiples of the rate rather than of nyquist",
     "foldback/fold.py",
     "    half = sample_rate / 2.0\n    return abs(frequency / half - round(frequency / half))",
     "    half = sample_rate\n    return abs(frequency / half - round(frequency / half))", False),
    ("the degenerate test is so loose that ordinary frequencies count as boundaries",
     "foldback/fold.py",
     "def is_degenerate(frequency: float, sample_rate: float, tolerance: float = 1e-9) -> bool:",
     "def is_degenerate(frequency: float, sample_rate: float, tolerance: float = 0.2) -> bool:",
     False),

    # ------------------------------------------------------------------ the spectrum
    ("the window goes, so the peak smears across neighbouring bins", "foldback/dft.py",
     "    spectrum = fft([v * w for v, w in zip(values, window)])",
     "    spectrum = fft([v for v, w in zip(values, window)])", False),
    ("the peak is the nearest bin with no interpolation, which is half a bin out",
     "foldback/dft.py",
     "    shift = 0.0 if denominator == 0.0 else 0.5 * (a - c) / denominator",
     "    shift = 0.0", False),
    ("silence gets a peak invented for it rather than reporting nothing", "foldback/dft.py",
     "    if max(abs(v) for v in values) < floor_ratio:\n        return None",
     "    if False:\n        return None", False),
    ("the transform runs the wrong way round the unit circle", "foldback/dft.py",
     "        step = cmath.exp(-2j * math.pi / size)",
     "        step = cmath.exp(2j * math.pi / size)", False),
    ("the window's coherent gain is not divided out, so every amplitude is four times too big",
     "foldback/dft.py",
     "    return 2.0 * abs(total) / sum(window)",
     "    return 2.0 * abs(total)", False),
    # DORMANT. Nothing in normal use asks for a frequency within four bins of an end, so this
    # guard never fires on correct input and cannot move the fingerprint. The requirement for it
    # is the opposite: the fingerprint must be UNCHANGED and the unit suite must fail anyway.
    ("the guard on the ends of the spectrum goes, where the answer is 56 percent high",
     "foldback/dft.py",
     "    if frequency < 4.0 * spacing or frequency > sample_rate / 2.0 - 4.0 * spacing:",
     "    if False:", True),

    # ------------------------------------------------------------------ the filter
    ("every section gets the same q, which is not a butterworth and droops in the passband",
     "foldback/biquad.py",
     "    return [1.0 / (2.0 * math.cos((2 * k + 1) * math.pi / (2 * order)))\n"
     "            for k in range(order // 2)]",
     "    return [1.0 / math.sqrt(2.0) for k in range(order // 2)]", False),
    ("the bandwidth term loses its factor of two, so every corner is in the wrong place",
     "foldback/biquad.py",
     "    alpha = math.sin(w0) / (2.0 * q)",
     "    alpha = math.sin(w0) / q", False),
    ("the second numerator term is not squared, so the response is not the filter's",
     "foldback/biquad.py",
     "            numerator = s.b0 + s.b1 * z + s.b2 * z * z",
     "            numerator = s.b0 + s.b1 * z + s.b2 * z", False),
    ("the feedback is added rather than subtracted, so the filter is unstable",
     "foldback/biquad.py",
     "        y = (self.b0 * x + self.b1 * self.x1 + self.b2 * self.x2\n"
     "             - self.a1 * self.y1 - self.a2 * self.y2)",
     "        y = (self.b0 * x + self.b1 * self.x1 + self.b2 * self.x2\n"
     "             + self.a1 * self.y1 - self.a2 * self.y2)", False),
    ("the input history is never updated, so the numerator does nothing",
     "foldback/biquad.py",
     "        self.x2, self.x1 = self.x1, x\n        self.y2, self.y1 = self.y1, y",
     "        self.y2, self.y1 = self.y1, y", False),

    # ------------------------------------------------------------------ the sampler
    ("the filter moves to AFTER the decimation, which is a tone control and not an anti alias "
     "filter", "foldback/sampler.py",
     "            for i in range(self.oversample):\n"
     "                value = self.amplitude * math.sin(phase)\n"
     "                if self.filter_on:\n"
     "                    value = self.cascade.process(value)\n"
     "                if i == 0:\n"
     "                    out[n] = value\n"
     "                phase += step",
     "            for i in range(self.oversample):\n"
     "                value = self.amplitude * math.sin(phase)\n"
     "                if i == 0:\n"
     "                    out[n] = value\n"
     "                phase += step\n"
     "            if self.filter_on:\n"
     "                out[n] = self.cascade.process(out[n])", False),
    ("the filter state is thrown away at every block, which clicks once a block",
     "foldback/sampler.py",
     "        step = 2.0 * math.pi * self.frequency / self.internal_rate",
     "        self.cascade.reset()\n"
     "        step = 2.0 * math.pi * self.frequency / self.internal_rate", False),
    ("the last internal sample of each frame is kept rather than the first",
     "foldback/sampler.py",
     "                if i == 0:\n                    out[n] = value",
     "                if i == self.oversample - 1:\n                    out[n] = value", False),
    ("the filter is designed at the output rate rather than at the rate it runs at",
     "foldback/sampler.py",
     "        self.cascade = biquad.Cascade(order, self.cutoff, self.internal_rate)\n\n"
     "    @property",
     "        self.cascade = biquad.Cascade(order, self.cutoff, self.sample_rate)\n\n"
     "    @property", False),

    # ------------------------------------------------------------------ the reference block
    ("the attenuation is measured at the frequency asked for rather than at the one heard",
     "foldback/reference.py",
     "        quiet.append(dft.amplitude_at(voice.render(WINDOW), rate, alias))",
     "        quiet.append(dft.amplitude_at(voice.render(WINDOW), rate, frequency))", False),

    # ------------------------------------------------------------------ the page's javascript
    # Both copies on purpose. `page/index.html` is what every check here runs, `docs/index.html`
    # is what a browser opens, and editing only one would be caught by the build check for being
    # out of date rather than for being wrong.
    ("the page's fold rounds down instead of to nearest", JS_FILES,
     "function aliasOf(f, fs) { return Math.abs(f - Math.round(f / fs) * fs); }",
     "function aliasOf(f, fs) { return Math.abs(f - Math.floor(f / fs) * fs); }", False),
    ("the page's fold loses its absolute value", JS_FILES,
     "function aliasOf(f, fs) { return Math.abs(f - Math.round(f / fs) * fs); }",
     "function aliasOf(f, fs) { return f - Math.round(f / fs) * fs; }", False),
    ("the page's fold adds where it should subtract", JS_FILES,
     "function aliasOf(f, fs) { return Math.abs(f - Math.round(f / fs) * fs); }",
     "function aliasOf(f, fs) { return Math.abs(f + Math.round(f / fs) * fs); }", False),
    ("the page's fold count rounds instead of flooring", JS_FILES,
     "function foldsBelow(f, fs) { return Math.floor(f / (fs / 2)); }",
     "function foldsBelow(f, fs) { return Math.round(f / (fs / 2)); }", False),
    ("the page's filter uses the same q for every section", JS_FILES,
     "      qs.push(1 / (2 * Math.cos((2 * k + 1) * Math.PI / (2 * order))));",
     "      qs.push(Math.SQRT1_2);", False),
    ("the page filters after the decimation rather than before it", JS_FILES,
     "        let value = state.amplitude * Math.sin(phase);\n"
     "        if (state.filterOn) value = processCascade(state.cascade, value);\n"
     "        if (i === 0) out[n] = value;",
     "        let value = state.amplitude * Math.sin(phase);\n"
     "        if (i === 0) out[n] = state.filterOn "
     "? processCascade(state.cascade, value) : value;",
     False),
    ("the page keeps the last internal sample of each frame rather than the first", JS_FILES,
     "        if (state.filterOn) value = processCascade(state.cascade, value);\n"
     "        if (i === 0) out[n] = value;",
     "        if (state.filterOn) value = processCascade(state.cascade, value);\n"
     "        if (i === state.oversample - 1) out[n] = value;", False),
    ("the page does not divide out the window's gain when it measures an amplitude", JS_FILES,
     "    return 2 * Math.hypot(sr, si) / gain;",
     "    return 2 * Math.hypot(sr, si);", False),
    ("the page's transform runs the wrong way round the unit circle", JS_FILES,
     "      const angle = -2 * Math.PI / size;",
     "      const angle = 2 * Math.PI / size;", False),
    ("the page reads the nearest bin instead of interpolating between three", JS_FILES,
     "    let shift = denominator === 0 ? 0 : 0.5 * (a - c) / denominator;",
     "    let shift = 0;", False),
]


def apply(tree: pathlib.Path, target, find: str, replace: str):
    """Edit every file named. Returns None on success, or a reason it could not be applied."""
    targets = (target,) if isinstance(target, str) else tuple(target)
    for name in targets:
        path = tree / name
        if not path.exists():
            return f"{name} does not exist"
        text = path.read_text(encoding="utf-8")
        count = text.count(find)
        if count == 0:
            return f"the text it edits is not in {name}"
        if count != 1:
            # THE TRAP. Anchoring on text that appears twice means the edit may land in a copy
            # nothing runs, and the sabotage then measures nothing while looking like it worked.
            return f"the text it edits appears {count} times in {name}, so the anchor is unsafe"
    for name in targets:
        path = tree / name
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace(find, replace, 1), encoding="utf-8")
    return None


def copy_tree(source: pathlib.Path, destination: pathlib.Path) -> None:
    shutil.copytree(source, destination,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))


def one(clean, index, entry):
    """One sabotage, in a tree of its own, through the three gates.

    Nothing is printed from here. Several of these run at once and interleaved output is
    unreadable, so each returns its lines and the caller prints them in order.
    """
    name, target, find, replace, dormant = entry
    with tempfile.TemporaryDirectory() as area:
        tree = pathlib.Path(area) / f"sabotage-{index:02d}"
        copy_tree(ROOT, tree)

        refused = apply(tree, target, find, replace)
        if refused is not None:
            return ([f"FAIL {index:2d} did not apply: {name}",
                     f"        {refused}"], False, dormant, [])

        moved = fingerprint(tree)
        if dormant:
            if moved != clean:
                where = "the measurement crashed" if moved is None else f"moved to {moved[:12]}"
                return ([f"FAIL {index:2d} is marked dormant and {where}: {name}",
                         "        a guard that changes correct output was never a guard, "
                         "so rerun it as a plain attack"], False, dormant, [])
            catchers = who_catches(tree)
            if "tests" not in catchers:
                return ([f"FAIL {index:2d} is dormant and the unit suite did not fail: {name}",
                         "        nothing else can catch it, because it changes no output"],
                        False, dormant, catchers)
            return ([], True, dormant, catchers)

        if moved == clean:
            return ([f"FAIL {index:2d} changed nothing measurable: {name}",
                     "        either the measurement is too narrow, and the repair is to widen "
                     "it, or this is not a sabotage at all and should be removed"],
                    False, dormant, [])

        catchers = who_catches(tree)
        if not catchers:
            return ([f"FAIL {index:2d} was not caught: {name}",
                     f"        the fingerprint moved to {moved[:12]} and every check passed"],
                    False, dormant, catchers)
        return ([], True, dormant, catchers)


def main() -> int:
    clean = fingerprint(ROOT)
    if clean is None:
        print("FAIL the clean tree does not fingerprint, so nothing below means anything")
        return 1
    still_clean = who_catches(ROOT)
    if still_clean:
        print(f"FAIL the clean tree fails its own checks: {', '.join(still_clean)}")
        return 1

    with tempfile.TemporaryDirectory() as area:
        control = pathlib.Path(area) / "an-untouched-copy-under-another-name"
        copy_tree(ROOT, control)
        control_print = fingerprint(control)
        if control_print != clean:
            print(f"FAIL null control: {clean} here and {control_print} in an untouched copy "
                  f"elsewhere. The measurement is a function of where the code lives rather than "
                  f"of the code, gate two would pass for free, and this run is void.")
            return 1
    print(f"null control: an untouched copy under another name fingerprints {clean[:16]}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        outcomes = list(pool.map(lambda item: one(clean, *item), enumerate(SABOTAGES, 1)))

    caught = failures = dormant_count = 0
    tally = {name: 0 for name, _ in CATCHERS}
    for lines, ok, was_dormant, catchers in outcomes:
        for line in lines:
            print(line)
        if ok:
            caught += 1
        else:
            failures += 1
        if was_dormant:
            dormant_count += 1
        for name in catchers:
            tally[name] += 1

    total = len(SABOTAGES)
    print(f"{caught} of {total} sabotages caught ({dormant_count} dormant), null control held")
    print("caught by: " + ", ".join(f"{name} {tally[name]}" for name, _ in CATCHERS))
    if failures:
        print(f"FAIL {failures} of {total} sabotages did not behave")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
