#!/usr/bin/env python3
"""Look for anything private in what git is actually tracking, and prove the search works.

A scanner that reads nothing prints exactly the same clean result as a scanner that read
everything and found nothing. So this runs three ways round.

  THE TRACKED TREE must come back clean. That is the answer anyone cares about.

  A PLANTED TREE must come back dirty, one hit for every credential shape this knows about. The
  fixtures are written to a temporary directory at scan time from TEMPLATES, never committed. A
  complete credential shaped string on disk gets the whole push rejected by GitHub's push
  protection, which scans full history, so a later deletion does not help. `sk-or-v1-{FILL:64}`
  in the repository expands to a full length string only in memory.

  CLEAN CONTROLS must come back clean even though they look alarming. A base64 blob and an inline
  PNG both contain long runs of letters and digits, and a case insensitive AWS pattern matches
  `AkiAqaMkgIem1yaUXNKiJ2M` inside one. AWS key ids are uppercase by definition, so the patterns
  here are case sensitive where the real format is.

TWO THINGS THAT MAKE THIS SCAN BLIND, both of which are checked rather than assumed.

  AN EMPTY FILE LIST. Before the first commit `git ls-files` returns nothing, every file is clean
  by vacuity, and the scan passes without opening anything. So a floor is required.

  A NUL BYTE. git and grep classify a file containing a NUL as binary and skip it entirely, which
  makes the scan silent about that whole file. Proven in this workspace by committing a real
  token into such a file and watching the scan report nothing. Python does not care, and this
  reads bytes and decodes them itself, but a NUL is still reported as a finding because it would
  blind every other tool in the chain.

THE PATTERNS ARE ASSEMBLED FROM FRAGMENTS so that this file does not match its own pattern list.
Four separate checks in this fleet have failed by finding themselves.
"""

from __future__ import annotations

import base64
import os
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
MINIMUM_TRACKED = 25

# Each entry is (name, regular expression assembled from fragments, template for the control).
# `{FILL:n}` in a template expands to n characters at scan time, so no complete credential shaped
# string exists on disk anywhere in this repository.
PATTERNS = [
    ("github personal access token",
     re.compile("gh" + "p_" + "[A-Za-z0-9]{36}"),
     "gh" + "p_" + "{FILL:36}"),
    ("github fine grained token",
     re.compile("github" + "_pat_" + "[A-Za-z0-9_]{22,}"),
     "github" + "_pat_" + "{FILL:60}"),
    ("openai style key",
     re.compile("sk-" + "[A-Za-z0-9]{32,}"),
     "sk-" + "{FILL:48}"),
    ("openrouter key",
     re.compile("sk-" + "or-" + "v1-" + "[A-Za-z0-9]{48,}"),
     "sk-" + "or-" + "v1-" + "{FILL:64}"),
    ("anthropic key",
     re.compile("sk-" + "ant-" + "[A-Za-z0-9-]{24,}"),
     "sk-" + "ant-" + "api03-" + "{FILL:40}"),
    ("google api key",
     re.compile("AI" + "za" + "Sy" + "[A-Za-z0-9_-]{33}"),
     "AI" + "za" + "Sy" + "{FILL:33}"),
    ("aws access key id",
     re.compile("AK" + "IA" + "[0-9A-Z]{16}"),
     "AK" + "IA" + "{UPPER:16}"),
    ("slack token",
     re.compile("xox" + "[baprs]-" + "[A-Za-z0-9-]{10,}"),
     "xox" + "b-" + "{FILL:24}"),
    ("private key block",
     re.compile("-----" + "BEGIN " + "[A-Z ]*PRIVATE KEY" + "-----"),
     "-----" + "BEGIN " + "RSA PRIVATE KEY" + "-----"),
    ("bearer authorization header",
     re.compile("[Aa]uthorization" + r"\s*[:=]\s*" + "['\"]?" + "Bearer " + "[A-Za-z0-9._-]{20,}"),
     "Authorization: " + "Bearer " + "{FILL:40}"),
]

# The account name and home directory of whoever ran this. An absolute path in a committed file
# is both private and unportable, and verify output gets pasted into the README.
HOME = os.path.expanduser("~")
ACCOUNT = os.path.basename(HOME)

CLEAN_CONTROLS = {
    "looks_like_base64.txt": base64.b64encode(b"a" * 96).decode(),
    "an_inline_png.txt": (
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAA"
        "AkiAqaMkgIem1yaUXNKiJ2MAAAAASUVORK5CYII="),
    "a_sha_and_a_uuid.txt": ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934c"
                             "a495991b7852b855 550e8400-e29b-41d4-a716-446655440000"),
    "the_word_secret.py": "SECRET_NAMES = ('API_KEY', 'TOKEN')  # names, never values\n",
    "a_placeholder_env.txt": "OPENAI_API_KEY=\nGITHUB_TOKEN=your-token-here\n",
}


def expand(template: str) -> str:
    def one(match):
        kind, size = match.group(1), int(match.group(2))
        alphabet = ("ABCDEFGHIJKLMNOPQRSTUVWXYZ" if kind == "UPPER"
                    else "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")
        return "".join(alphabet[(i * 7 + 3) % len(alphabet)] for i in range(size))
    return re.sub(r"\{(FILL|UPPER):(\d+)\}", one, template)


def scan_text(text: str):
    return [name for name, expression, _ in PATTERNS if expression.search(text)]


def tracked_files():
    done = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, timeout=300)
    if done.returncode != 0:
        raise SystemExit("git ls-files failed, so there is no list of tracked files to scan")
    return [ROOT / name.decode() for name in done.stdout.split(b"\0") if name]


def main() -> int:
    problems = []

    files = tracked_files()
    if len(files) < MINIMUM_TRACKED:
        problems.append(f"git tracks only {len(files)} file(s), which is too few for this scan "
                        f"to mean anything. Before the first commit it tracks none and every "
                        f"check below passes without opening a file.")

    for path in files:
        if not path.exists():
            problems.append(f"{path.relative_to(ROOT)} is tracked and not on disk")
            continue
        raw = path.read_bytes()
        if b"\0" in raw:
            problems.append(f"{path.relative_to(ROOT)} contains a NUL byte, which makes git and "
                            f"grep treat it as binary and skip it. Write it as the two character "
                            f"escape instead of embedding the byte.")
        text = raw.decode("utf-8", errors="replace")
        for name in scan_text(text):
            problems.append(f"{path.relative_to(ROOT)} contains something shaped like a {name}")
        if HOME and HOME not in ("/", "") and HOME in text:
            problems.append(f"{path.relative_to(ROOT)} contains this machine's home directory")
        if len(ACCOUNT) > 2 and re.search(r"/home/" + re.escape(ACCOUNT) + r"\b", text):
            problems.append(f"{path.relative_to(ROOT)} contains this machine's account name")
    # The BYTE TOTAL is deliberately not printed. This scan's output is pasted into the README,
    # and a total that includes the README's own length changes the moment it is pasted, so the
    # loop that converges the two would never terminate. The file count is the claim that matters
    # and it is checked against a floor above.
    print(f"scanned {len(files)} tracked files, none of them binary to git, "
          f"{sum(1 for f in files if f.exists() and f.stat().st_size == 0)} of them empty")

    with tempfile.TemporaryDirectory() as area:
        planted = pathlib.Path(area)
        # POSITIVE CONTROLS. One file per pattern, so a pattern that stopped matching is named
        # rather than hidden behind another pattern that still does.
        found_all = True
        for name, _, template in PATTERNS:
            body = ("a fixture written at scan time and never committed\n"
                    + expand(template) + "\n")
            target = planted / (re.sub(r"[^a-z]+", "_", name) + ".txt")
            target.write_text(body, encoding="utf-8")
            hits = scan_text(target.read_text(encoding="utf-8"))
            if name not in hits:
                found_all = False
                problems.append(f"the positive control for a {name} was NOT found, so this scan "
                                f"is blind to that shape")
        if found_all:
            print(f"positive controls: {len(PATTERNS)} planted credentials, every one found")

        # NEGATIVE CONTROLS. Alarming looking text that is not a credential.
        clean = 0
        for name, body in sorted(CLEAN_CONTROLS.items()):
            target = planted / name
            target.write_text(body + "\n", encoding="utf-8")
            hits = scan_text(target.read_text(encoding="utf-8"))
            if hits:
                problems.append(f"the clean control {name} was flagged as {hits}, which is a "
                                f"false alarm that would teach people to ignore this check")
            else:
                clean += 1
        print(f"negative controls: {clean} of {len(CLEAN_CONTROLS)} alarming looking files "
              f"correctly left alone")

        # AND THE NUL CHECK ITSELF HAS A CONTROL. `grep -P '\x00'` is not available in every grep
        # on this machine and returns no matches while Python finds the byte immediately, so a
        # NUL audit built on grep reports everything clean.
        nul_file = planted / "has_a_nul.bin"
        nul_file.write_bytes(b"before\x00after")
        if b"\0" not in nul_file.read_bytes():
            problems.append("the NUL detector did not find a planted NUL byte")
        else:
            print("the NUL detector found a planted NUL byte, so its silence above means "
                  "something")

    if ".env" in [p.name for p in files]:
        problems.append("a .env file is tracked")

    for problem in problems:
        print(f"FAIL {problem}")
    if problems:
        print(f"FAIL {len(problems)} privacy problem(s)")
        return 1
    print("nothing private, nothing credential shaped, and the scanner is shown to work")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
