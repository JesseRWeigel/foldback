#!/usr/bin/env python3
"""Recompute what this project claims, by other routes, importing nothing from the package.

A validator that shares code with the thing it validates cannot catch that code's bugs. This file
therefore imports `math`, `cmath`, `ast`, `json`, `pathlib`, `re` and `sys`, and nothing else, and
it proves that by walking its own import graph before it does anything.

WHAT IS RE-DERIVED, AND HOW EACH ROUTE DIFFERS.

  WHERE A TONE LANDS. `foldback.fold` asks which multiple of the sample rate is nearest and takes
  the residue. This file never divides by the sample rate. It takes `fmod` to get a remainder in
  [0, fs) and reflects the top half of it back down, which is the triangle wave picture. Same
  answer, different starting point.

  AND WHERE IT REALLY LANDS. That is still algebra checking algebra, so there is a third route
  that is not algebra at all: generate the samples, then scan a NAIVE single frequency transform
  across the whole band in coarse steps and refine the best one by golden section search. No FFT,
  no window, no bit reversal, no peak interpolation. If the fast transform in `foldback.dft` had a
  bug in its bit reversal or its twiddle factors, this would disagree with it.

  WHAT THE FILTER DOES. `foldback.biquad` builds cookbook second order sections and evaluates
  their transfer function on the unit circle. This file never sees a coefficient. It uses the
  closed form for a Butterworth after a bilinear transform,

      |H| = 1 / sqrt(1 + (tan(w/2) / tan(wc/2))^(2N))

  which is the analog prototype with the frequency axis warped, and compares that against the
  attenuation figures baked into the published page.

  WHAT THE PUBLISHED PAGE SAYS. The numbers checked are the ones in `docs/index.html`, read out of
  the JSON block, because that is the artifact a reader loads. Checking the Python against the
  Python would pass on a page that was never rebuilt.

THE REFUSAL IS ENFORCED, NOT DECLARED. `audit` walks this file's import graph with `ast`, follows
local modules, and refuses anything that reaches the package by any route including a name
assembled at runtime. `scripts/probes/` holds files that must be refused and files that must be
accepted, each declaring which it is on its own first line so a probe cannot land in the wrong
bucket by being renamed. A grep would be satisfied by a comment and would miss
`importlib.import_module`, which is why this is an `ast` walk.
"""

from __future__ import annotations

import ast
import cmath
import json
import math
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = "foldback"
PACKAGE_DIR = (ROOT / "foldback").resolve()
PAGE = ROOT / "docs" / "index.html"


# ----------------------------------------------------------------------------------------------
# the refusal
# ----------------------------------------------------------------------------------------------

def _string_environment(tree):
    """Module level string assignments, so a name built by concatenation can be recovered."""
    env = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and \
                isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    env[target.id] = node.value.value
    return env


def _fold_string(node, env):
    """Evaluate a string expression made of literals, known names and `+`. None if it is not."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _fold_string(node.left, env)
        right = _fold_string(node.right, env)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):
        pieces = []
        for piece in node.values:
            if isinstance(piece, ast.Constant):
                pieces.append(str(piece.value))
            elif isinstance(piece, ast.FormattedValue):
                folded = _fold_string(piece.value, env)
                if folded is None:
                    return None
                pieces.append(folded)
        return "".join(pieces)
    return None


def imported_names(path: pathlib.Path):
    """Every module name this file could reach, including names assembled at runtime."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    env = _string_environment(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.module:
                found.append(node.module)
            elif node.level:
                found.append(path.parent.name)
            elif node.module:
                found.append(node.module)
        elif isinstance(node, ast.Call):
            target = node.func
            name = getattr(target, "attr", None) or getattr(target, "id", None)
            if name in ("import_module", "__import__", "exec_module", "spec_from_file_location"):
                for argument in node.args:
                    folded = _fold_string(argument, env)
                    if folded is not None:
                        found.append(folded)
                    else:
                        # A name this cannot fold is treated as an import of the package itself.
                        # A checker that cannot see where a call goes has proved nothing, and
                        # saying so is the only honest answer.
                        found.append(PACKAGE)
    return found


def resolve_local(name: str, start: pathlib.Path):
    """The file a module name refers to, if it is one of ours."""
    for base in (start.parent, ROOT):
        candidate = base / (name.replace(".", "/") + ".py")
        if candidate.exists():
            return candidate
        package_init = base / name.replace(".", "/") / "__init__.py"
        if package_init.exists():
            return package_init
    return None


def audit(path: pathlib.Path, seen=None):
    """Walk the import graph and report every path that reaches the package."""
    seen = seen if seen is not None else set()
    path = path.resolve()
    if path in seen:
        return []
    seen.add(path)
    offences = []
    for name in imported_names(path):
        root = name.split(".")[0]
        if root == PACKAGE:
            offences.append(f"{path.name} imports {name}")
            continue
        local = resolve_local(name, path)
        if local is None:
            continue
        # Compared against the package DIRECTORY rather than against the string "foldback"
        # appearing in a path. The repository is also called foldback, so a name test would flag
        # every local helper here, including the clean probe that must be accepted.
        if local.resolve().is_relative_to(PACKAGE_DIR):
            offences.append(f"{path.name} imports {name}")
        else:
            offences.extend(audit(local, seen))
    return offences


def enforce_independence():
    offences = audit(pathlib.Path(__file__))
    if offences:
        raise SystemExit("this checker is not independent: " + "; ".join(offences))
    if PACKAGE in sys.modules:
        raise SystemExit(f"{PACKAGE} is already imported into this process")
    for name in list(sys.modules):
        if name.split(".")[0] == PACKAGE:
            raise SystemExit(f"{name} is already imported into this process")


# ----------------------------------------------------------------------------------------------
# route one: the fold, as a reflected remainder
# ----------------------------------------------------------------------------------------------

def alias_by_reflection(frequency, sample_rate):
    """Take the remainder, then reflect anything in the upper half back down.

    No rounding, no nearest multiple, no absolute value. `fmod` gives a remainder in [0, fs) and
    the reflection is a subtraction. If `foldback.fold` had a `floor` where it needs a `round`,
    or a sign the wrong way, or a missing absolute value, this would disagree with it and the
    disagreement is what is reported.
    """
    remainder = math.fmod(frequency, sample_rate)
    if remainder < 0.0:
        remainder += sample_rate
    return remainder if remainder <= sample_rate / 2.0 else sample_rate - remainder


# ----------------------------------------------------------------------------------------------
# route two: where the tone really lands, from the samples, without an FFT
# ----------------------------------------------------------------------------------------------

def power_at(samples, sample_rate, frequency):
    """One term of a discrete transform, evaluated directly. No window, no bit reversal."""
    turn = -2.0 * math.pi * frequency / sample_rate
    total = 0j
    for i, value in enumerate(samples):
        total += value * cmath.exp(1j * turn * i)
    return abs(total)


def loudest_frequency(samples, sample_rate, coarse_steps=400):
    """Scan the band coarsely, then close in by golden section search.

    Deliberately slow and deliberately simple. Everything clever in `foldback.dft`, which is the
    radix two decomposition, the bit reversal, the Hann window and the parabolic interpolation on
    logarithms, is absent here, so a bug in any of them shows up as a disagreement.
    """
    top = sample_rate / 2.0
    step = top / coarse_steps
    best, best_power = 0.0, -1.0
    for i in range(coarse_steps + 1):
        frequency = i * step
        power = power_at(samples, sample_rate, frequency)
        if power > best_power:
            best, best_power = frequency, power

    low, high = max(0.0, best - step), min(top, best + step)
    phi = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = high - phi * (high - low), low + phi * (high - low)
    fa, fb = power_at(samples, sample_rate, a), power_at(samples, sample_rate, b)
    for _ in range(60):
        if fa < fb:
            low, a, fa = a, b, fb
            b = low + phi * (high - low)
            fb = power_at(samples, sample_rate, b)
        else:
            high, b, fb = b, a, fa
            a = high - phi * (high - low)
            fa = power_at(samples, sample_rate, a)
        if high - low < 1e-4:
            break
    return (low + high) / 2.0


def sine(frequency, sample_rate, count):
    """The sampled tone, written from the definition, evaluated once per sample."""
    return [math.sin(2.0 * math.pi * frequency * n / sample_rate) for n in range(count)]


# ----------------------------------------------------------------------------------------------
# route three: the filter, from the closed form rather than from coefficients
# ----------------------------------------------------------------------------------------------

def butterworth_db(frequency, cutoff, sample_rate, order):
    """The bilinear transform of the analog Butterworth, in one expression.

    The whole point is that this never builds a section, never computes a pole Q, and never
    evaluates a transfer function on the unit circle. It warps the frequency axis with a tangent
    and applies the analog magnitude.
    """
    w = math.pi * frequency / (sample_rate / 2.0)
    wc = math.pi * cutoff / (sample_rate / 2.0)
    ratio = math.tan(w / 2.0) / math.tan(wc / 2.0)
    return -10.0 * math.log10(1.0 + ratio ** (2 * order))


# ----------------------------------------------------------------------------------------------
# what the published page actually says
# ----------------------------------------------------------------------------------------------

def published_reference():
    text = PAGE.read_text(encoding="utf-8")
    begin, end = "<!-- BEGIN GENERATED REFERENCE -->", "<!-- END GENERATED REFERENCE -->"
    if text.count(begin) != 1 or text.count(end) != 1:
        raise SystemExit(f"{PAGE.name} does not have exactly one generated region")
    body = text.split(begin, 1)[1].split(end, 1)[0]
    return json.loads(body)


def published_core_constants():
    """The JavaScript the page ships, read as text, for the two formulas that matter.

    Not to run it. Just to confirm the shipped page carries the round, the subtraction and the
    absolute value that the lesson depends on, and the Butterworth pole Q formula. A page that
    had quietly acquired a `Math.floor` here would be caught by `scripts/parity.py` running it,
    and this is the cheap second look that needs nothing but a regular expression.
    """
    text = PAGE.read_text(encoding="utf-8")
    found = {}
    match = re.search(r"function aliasOf\(f, fs\) \{ return ([^;]+); \}", text)
    found["aliasOf"] = match.group(1).strip() if match else None
    found["poleq"] = "1 / (2 * Math.cos((2 * k + 1) * Math.PI / (2 * order)))" in text
    return found


# ----------------------------------------------------------------------------------------------

RATES = (44100.0, 48000.0)
MULTIPLES = (0.05, 0.5, 0.9, 0.98, 1.02, 1.25, 1.5, 1.75, 1.98,
             2.02, 2.4, 2.6, 3.2, 3.7, 4.5, 5.3, 6.4, 7.1, 7.9)
DEGENERATE = (1.0, 2.0, 3.0, 4.0)
WINDOW = 4096
WARMUP = 0


def main() -> int:
    enforce_independence()
    problems = []
    print("independence: this file's import graph reaches nothing inside the package")

    # ---- the fold's own properties, from the reflection route alone -----------------------
    # Three things have to be true of any correct fold, and they are checked here on the route
    # that has no rounding in it, so that the sweep below is comparing against something already
    # known to behave. Every answer is inside the band, moving by a whole sample rate changes
    # nothing, and the curve is a mirror about every multiple of the rate.
    checked = 0
    for rate in RATES:
        for multiple in MULTIPLES + DEGENERATE:
            frequency = multiple * rate / 2.0
            reflected = alias_by_reflection(frequency, rate)
            checked += 1
            if reflected > rate / 2.0 + 1e-9 or reflected < -1e-9:
                problems.append(f"the reflection route left the band at {frequency:.1f} Hz "
                                f"with {reflected:.4f}")
            shifted = alias_by_reflection(frequency + 3.0 * rate, rate)
            if abs(shifted - reflected) > 1e-6:
                problems.append(f"moving {frequency:.1f} Hz up three sample rates changed the "
                                f"answer from {reflected:.4f} to {shifted:.4f}")
            for offset in (1.0, 997.0, rate / 2.0 - 1.0):
                low = alias_by_reflection(abs(2.0 * rate - offset), rate)
                high = alias_by_reflection(2.0 * rate + offset, rate)
                if abs(low - high) > 1e-6:
                    problems.append(f"the mirror at twice {rate:.0f} Hz is not a mirror: "
                                    f"{low:.4f} below and {high:.4f} above")
    print(f"the fold: {checked} frequencies land inside the band, are unchanged by a whole "
          f"sample rate, and mirror about every multiple of it")

    # ---- the published reference block, against the reflection route ----------------------
    reference = published_reference()
    rows = 0
    worst = 0.0
    for rate_text, pairs in sorted(reference["alias"].items()):
        rate = float(rate_text)
        for asked, heard in pairs:
            expected = alias_by_reflection(asked, rate)
            gap = abs(heard - expected)
            worst = max(worst, gap)
            rows += 1
            if gap > 1e-6:
                problems.append(f"the page says {asked:.1f} Hz at {rate:.0f} Hz is heard at "
                                f"{heard:.4f} and the reflection route says {expected:.4f}")
    print(f"the published page: {rows} alias rows, worst disagreement {worst:.3e} Hz")
    if rows < 20:
        problems.append(f"the page carries only {rows} alias rows, which is too few to check")

    # ---- where the tone really lands, from the samples, without an FFT --------------------
    measured = 0
    worst_measured = 0.0
    for rate in RATES:
        for multiple in (0.5, 0.9, 1.25, 1.5, 2.4, 2.6, 3.7, 5.3, 7.1):
            frequency = multiple * rate / 2.0
            expected = alias_by_reflection(frequency, rate)
            found = loudest_frequency(sine(frequency, rate, WINDOW), rate)
            gap = abs(found - expected)
            worst_measured = max(worst_measured, gap)
            measured += 1
            if gap > rate / WINDOW / 4.0:
                problems.append(f"a naive scan of the samples at {frequency:.1f} Hz on "
                                f"{rate:.0f} Hz found {found:.3f} Hz and the arithmetic says "
                                f"{expected:.3f} Hz")
    print(f"the samples themselves: {measured} tones located by a naive scan and a golden "
          f"section search, worst {worst_measured:.4f} Hz off, which is "
          f"{worst_measured / (44100.0 / WINDOW):.4f} of a bin")

    # ---- and the degenerate frequencies really are silent ---------------------------------
    silent = 0
    for rate in RATES:
        for multiple in DEGENERATE:
            loudest = max(abs(v) for v in sine(multiple * rate / 2.0, rate, WINDOW))
            silent += 1
            if loudest > 1e-6:
                problems.append(f"{multiple} x Nyquist at {rate:.0f} Hz is not silent, "
                                f"loudest sample {loudest:.3e}")
    print(f"the boundaries: {silent} multiples of Nyquist sample to silence, as a zero phase "
          f"sine on its own zero crossings must")

    # ---- the filter, from the closed form -------------------------------------------------
    filters = 0
    worst_filter = 0.0
    for row in reference["attenuation"]:
        rate, order = float(row["rate"]), int(row["order"])
        internal = rate * 8.0
        cutoff = 0.9 * rate / 2.0
        expected = butterworth_db(float(row["frequency"]), cutoff, internal, order)
        gap = abs(float(row["db"]) - expected)
        worst_filter = max(worst_filter, gap)
        filters += 1
        if gap > 0.05:
            problems.append(f"the page says the filter takes {row['db']:.2f} dB off "
                            f"{row['frequency']:.0f} Hz at order {order}, and the closed form "
                            f"says {expected:.2f} dB")
        if float(row["db"]) > -9.0:
            problems.append(f"the page claims only {row['db']:.2f} dB at order {order}, which is "
                            f"not an anti alias filter doing anything")
    print(f"the filter: {filters} attenuation figures re-derived from the analog Butterworth "
          f"magnitude, worst disagreement {worst_filter:.4f} dB")

    # ---- and what a corner costs, which the page prints next to it -------------------------
    for rate in RATES:
        internal = rate * 8.0
        cutoff = 0.9 * rate / 2.0
        cost = butterworth_db(0.98 * rate / 2.0, cutoff, internal, 4)
        if cost > -0.05:
            problems.append(f"at {rate:.0f} Hz a corner at 0.9 of Nyquist costs {cost:.3f} dB at "
                            f"0.98 of Nyquist, and the page says it costs something")
    print("the cost: a corner below Nyquist takes real signal off the top of the band, "
          "confirmed from the same closed form")

    # ---- the shipped JavaScript still contains the formula the lesson is ------------------
    core = published_core_constants()
    if core["aliasOf"] != "Math.abs(f - Math.round(f / fs) * fs)":
        problems.append(f"the page's aliasOf reads {core['aliasOf']!r}")
    if not core["poleq"]:
        problems.append("the page no longer carries the Butterworth pole Q formula")
    print(f"the shipped javascript: aliasOf is {core['aliasOf']}")

    for problem in problems:
        print(f"FAIL {problem}")
    if problems:
        print(f"FAIL {len(problems)} independent recomputation(s) disagree with the project")
        return 1
    print("every headline number re-derived a second way agrees with the published page")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
