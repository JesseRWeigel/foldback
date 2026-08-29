#!/usr/bin/env bash
# The exit code of this script IS the result. Nothing below prints success for a step it did not
# run. A step that cannot run is a FAILURE with an install command attached, never a skip, because
# a skipped check and a passing check are the same line in a log a week later.
set -u
cd "$(dirname "$0")/.."
PY=${PY:-python3}
STEP=0
FAILED=0
step() { STEP=$((STEP + 1)); printf '\n== %d. %s\n' "$STEP" "$1"; }
check() {
  if [ "$1" -eq 0 ]; then printf '   PASS\n'
  else printf '   FAIL (exit %d)\n' "$1"; FAILED=$((FAILED + 1)); fi
}

BEFORE=$("$PY" - <<'EOF'
import hashlib, pathlib
h = hashlib.sha256()
for p in sorted(pathlib.Path(".").rglob("*")):
    if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts:
        h.update(str(p).encode()); h.update(p.read_bytes())
print(h.hexdigest())
EOF
)

step "python, node and a browser, and the standard library only"
"$PY" - <<'EOF'
import shutil, subprocess, sys
sys.path.insert(0, ".")
import foldback.biquad, foldback.dft, foldback.fold, foldback.reference, foldback.sampler
for name in ("numpy", "scipy", "matplotlib", "soundfile", "librosa", "torch"):
    if name in sys.modules:
        print(f"   FAIL {name} is loaded, and this project is standard library only")
        raise SystemExit(1)
missing = []
node = shutil.which("node")
if node is None:
    missing.append("node, needed to run the page's own JavaScript: apt-get install nodejs")
browser = None
for candidate in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
    browser = browser or shutil.which(candidate)
if browser is None:
    missing.append("chrome or chromium, needed to open the page: apt-get install chromium-browser")
for line in missing:
    print(f"   FAIL {line}")
if missing:
    print("   Neither is optional. Without node the page's arithmetic is never compared against "
          "the tested Python, and without a browser nothing here has been shown to run in one.")
    raise SystemExit(1)
versions = []
for argv in ([node, "--version"], [browser, "--version"]):
    done = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    versions.append(done.stdout.strip().splitlines()[0] if done.stdout.strip() else "unknown")
print(f"   python {sys.version.split()[0]}, node {versions[0]}, {versions[1]}, "
      f"standard library only")
EOF
check $?

step "unit tests"
# Counts and verdict only, never elapsed time. This transcript is pasted into the README and
# compared against a fresh run, and a figure in milliseconds could never converge.
OUT=$("$PY" -W ignore::ResourceWarning -m unittest discover -s tests -t . 2>&1)
RC=$?
echo "$OUT" | grep -E "^Ran [0-9]+ tests" | sed -E 's/ in [0-9.]+s//' | sed 's/^/   /'
echo "$OUT" | grep -E "^(OK|FAILED)" | sed 's/^/   /'
check $RC

step "the test count the README claims is the count that exists"
"$PY" - <<'EOF'
import re, subprocess, sys
out = subprocess.run([sys.executable, "-W", "ignore::ResourceWarning", "-m", "unittest",
                      "discover", "-s", "tests", "-t", "."], capture_output=True, text=True)
ran = int(re.search(r"^Ran (\d+) tests", out.stderr, re.M).group(1))
text = open("README.md", encoding="utf-8").read()
claimed = [int(n) for n in re.findall(r"Ran (\d+) tests", text)]
claimed += [int(n) for n in re.findall(r"(\d+) unit tests", text)]
if not claimed:
    print("   FAIL the README pastes no test count, so it cannot be checked"); raise SystemExit(1)
if any(number != ran for number in claimed):
    print(f"   FAIL the README claims {sorted(set(claimed))} and the runner ran {ran}")
    raise SystemExit(1)
# The phrasing here deliberately avoids the two patterns it searches for. This transcript is
# pasted into the README, so a line reading "the README says 126 unit tests" would become a
# claim the next run counts, and the count would climb by one every time it was pasted.
print(f"   the runner ran {ran}, and every count claimed in the README agrees with it")
EOF
check $?

step "the alias arithmetic, over a sweep wide enough for the tolerance to mean something"
"$PY" - <<'EOF'
import sys
sys.path.insert(0, ".")
sys.path.insert(0, "tests")
import test_alias_physics as physics
from foldback import fold
rates = physics.RATES
total = len(rates) * len(physics.STEPS)
tops = [max(physics.frequency_at(rate, s) for s in physics.STEPS) / (rate / 2.0)
        for rate in rates]
above = sum(1 for rate in rates for s in physics.STEPS
            if fold.folds_below(physics.frequency_at(rate, s), rate) > 0)
degenerate = sum(1 for rate in rates for s in physics.STEPS
                 if fold.is_degenerate(physics.frequency_at(rate, s), rate))
print(f"   {total} frequencies across {len(rates)} sample rates, up to "
      f"{min(tops):.2f} times Nyquist, {above} of them above it, {degenerate} of them exactly "
      f"on a fold boundary")
print(f"   the tight bound is {physics.TIGHT_BINS} of a bin, loosened to "
      f"{physics.NEAR_EDGE_BINS} within {physics.EDGE_GUARD_BINS} bins of an end of the spectrum")
if total < 1000 or above < 1000 or degenerate < 10:
    print("   FAIL the sweep is too narrow for its tolerance to prove anything")
    raise SystemExit(1)
EOF
check $?

step "the filter toggle, in decibels, at every order the page offers"
"$PY" - <<'EOF'
import sys
sys.path.insert(0, ".")
sys.path.insert(0, "tests")
import test_attenuation as attenuation
from foldback import reference
bad = 0
for multiple in attenuation.MULTIPLES:
    cells = []
    for order in attenuation.ORDERS:
        measured = reference.measured_attenuation_db(
            multiple * attenuation.RATE / 2.0, attenuation.RATE, order,
            attenuation.CORNER_FRACTION)
        claimed = attenuation.PUBLISHED[(multiple, order)]
        if abs(measured - claimed) > 0.06:
            bad += 1
            print(f"   FAIL {multiple} x Nyquist at order {order}: measured {measured:.2f} dB, "
                  f"published {claimed:.1f} dB")
        cells.append(f"{measured:8.1f} dB")
    print(f"   {multiple} x Nyquist:" + "".join(cells))
print("   orders 2, 4, 6 and 8, at 44100 Hz with the corner at 0.9 of Nyquist")
raise SystemExit(1 if bad else 0)
EOF
check $?

step "the page's own javascript against the tested python, value by value"
OUT=$("$PY" scripts/parity.py 2>&1)
RC=$?
echo "$OUT" | sed 's/^/   /'
check $RC

step "the published page is what a fresh build produces"
"$PY" scripts/build_page.py --check | sed 's/^/   /'
check "${PIPESTATUS[0]}"

step "the page in real headless chrome, on both audio engines"
OUT=$("$PY" scripts/browser_check.py 2>&1)
RC=$?
echo "$OUT" | fold -s -w 96 | sed 's/^/   /'
check $RC

step "the measurement is deterministic and does not track the working directory"
"$PY" - <<'EOF'
import pathlib, shutil, subprocess, sys, tempfile
def fp(tree):
    done = subprocess.run([sys.executable, "scripts/measure.py"], cwd=tree,
                          capture_output=True, text=True, timeout=1800)
    if done.returncode != 0:
        print("   FAIL the measurement would not run:", done.stderr.strip()[-300:])
        raise SystemExit(1)
    return [l.split()[1] for l in done.stderr.splitlines() if l.startswith("FINGERPRINT ")][0]
one, two = fp("."), fp(".")
with tempfile.TemporaryDirectory() as area:
    other = pathlib.Path(area) / "a-completely-different-name"
    shutil.copytree(".", other, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
    three = fp(other)
if not (one == two == three):
    print(f"   FAIL {one} then {two} then {three}")
    print("   A fingerprint that depends on where the code lives passes gate two of the "
          "sabotage rule for free, and the whole sabotage run would be void.")
    raise SystemExit(1)
print(f"   FINGERPRINT {one}")
print("   identical across two runs here and from an untouched copy under another name")
EOF
check $?

step "the measurement carries nothing belonging to this machine"
"$PY" - <<'EOF'
import os, subprocess, sys
done = subprocess.run([sys.executable, "scripts/measure.py"], capture_output=True, text=True,
                      timeout=1800)
if done.returncode != 0:
    print("   FAIL the measurement refused to print:", done.stderr.strip()[-300:])
    raise SystemExit(1)
home = os.path.expanduser("~")
user = os.path.basename(home)
problems = []
if home and home != "/" and home in done.stdout:
    problems.append("the home directory appears in the measurement")
if user and len(user) > 2 and user in done.stdout:
    problems.append("the account name appears in the measurement")
if os.getcwd() in done.stdout:
    problems.append("the path to this checkout appears in the measurement")
for problem in problems:
    print(f"   FAIL {problem}")
print(f"   {len(done.stdout.splitlines())} lines of measurement, none of them this machine's")
raise SystemExit(1 if problems else 0)
EOF
check $?

step "independent recomputation, importing nothing from the package"
OUT=$("$PY" scripts/check_independent.py 2>&1)
RC=$?
echo "$OUT" | fold -s -w 96 | sed 's/^/   /'
check $RC

step "the independent checker refuses every dependent probe"
"$PY" - <<'EOF'
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("chk", "scripts/check_independent.py")
chk = importlib.util.module_from_spec(spec); spec.loader.exec_module(chk)
# Which probes must be refused is declared on each probe's own first line rather than inferred
# from its filename, so renaming one cannot move it silently into the wrong bucket.
probes = []
for path in sorted(pathlib.Path("scripts/probes").glob("probe_*.py")):
    first = path.read_text(encoding="utf-8").splitlines()[0]
    if "MUST BE REFUSED" in first:
        probes.append((path, True))
    elif "MUST BE ACCEPTED" in first:
        probes.append((path, False))
refused = sum(1 for _, want in probes if want)
if refused < 5 or refused == len(probes):
    print(f"   FAIL {refused} must be refused and {len(probes) - refused} must be accepted, "
          f"which proves little either way")
    raise SystemExit(1)
bad = 0
for path, want in probes:
    if bool(chk.audit(path)) != want:
        print(f"   FAIL {path.name} {'was accepted' if want else 'was refused'}")
        bad += 1
print(f"   {refused} probes that reach the package refused, including one through a helper and "
      f"one through a name built at runtime")
print(f"   {len(probes) - refused} probes accepted, one of which names the package in a comment "
      f"and in a string, which is what separates this from a grep")
raise SystemExit(1 if bad else 0)
EOF
check $?

step "privacy scan with planted positive controls and clean negative controls"
OUT=$("$PY" scripts/privacy_scan.py 2>&1)
RC=$?
echo "$OUT" | fold -s -w 96 | sed 's/^/   /'
check $RC

step "sabotage suite, three gates and a null control"
# The slowest step here by a long way, and the one that says whether any of the others have
# teeth. Every sabotage gets its own copy of the tree, so several run at once.
OUT=$("$PY" scripts/sabotage.py 2>&1)
RC=$?
echo "$OUT" | sed 's/^/   /'
check $RC

step "the README is finished and carries this script's own success line"
"$PY" - <<'EOF'
import importlib.util, pathlib, re, sys
text = open("README.md", encoding="utf-8").read()
# Fenced blocks are stripped before the scaffold marker search, because the Status section holds
# this script's own transcript and a search for TODO would otherwise match its own output. The
# success line below is looked for in the WHOLE file, because that is where it lives.
prose = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
problems = []
for marker in ("TODO", "PLACEHOLDER", "FIXME", "NOT YET VERIFIED"):
    if marker in prose:
        problems.append(f"the README still contains {marker!r}")
for heading in ("## Status", "## Unfinished", "## What this is", "## Running it"):
    if heading not in text:
        problems.append(f"no {heading} section")
if "VERIFY PASSED: foldback" not in text:
    problems.append("the Status section does not carry this script's success line")
if chr(0x2014) in text:
    problems.append("the README contains an em dash")

spec = importlib.util.spec_from_file_location("sab", "scripts/sabotage.py")
sab = importlib.util.module_from_spec(spec); spec.loader.exec_module(sab)
if f"{len(sab.SABOTAGES)} sabotages" not in text:
    problems.append(f"the README does not say '{len(sab.SABOTAGES)} sabotages', and there are "
                    f"{len(sab.SABOTAGES)}")
probes = list(pathlib.Path("scripts/probes").glob("probe_*.py"))
declared = [p for p in probes
            if "MUST BE" in p.read_text(encoding="utf-8").splitlines()[0]]
if f"{len(declared)} probes" not in text:
    problems.append(f"the README does not say '{len(declared)} probes', and there are "
                    f"{len(declared)}")
# The README's own byte count is deliberately not printed. This transcript is pasted into the
# README, so any number depending on the README's length changes the moment it is pasted and the
# loop that converges the two would never terminate.
print(f"   {len(re.findall(r'^## ', text, re.M))} sections, {len(problems)} problem(s)")
for message in problems:
    print(f"   {message}")
sys.exit(1 if problems else 0)
EOF
check $?

step "verify did not modify the tree it was verifying"
AFTER=$("$PY" - <<'EOF'
import hashlib, pathlib
h = hashlib.sha256()
for p in sorted(pathlib.Path(".").rglob("*")):
    if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts:
        h.update(str(p).encode()); h.update(p.read_bytes())
print(h.hexdigest())
EOF
)
if [ "$BEFORE" = "$AFTER" ]; then printf '   the tree is byte identical to before this ran\n'; check 0
else printf '   FAIL the tree changed while being verified\n'; check 1; fi

printf '\n'
if [ "$FAILED" -eq 0 ]; then
  printf 'VERIFY PASSED: foldback, %d of %d steps\n' "$STEP" "$STEP"; exit 0
fi
printf 'VERIFY FAILED: foldback, %d of %d steps failed\n' "$FAILED" "$STEP"
exit 1
