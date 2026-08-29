#!/usr/bin/env python3
"""Write docs/index.html from page/index.html and the numbers Python computed.

The page is one file with one generated region in it. Everything a reader sees is hand written in
`page/index.html`; the block between the two markers is replaced here with a table of alias
frequencies and filter attenuations that came out of the tested Python. `scripts/verify.sh`
rebuilds and diffs, so the published page cannot drift away from the code that justifies it.

With `--check` this writes nothing and exits 1 if the published page is not what a rebuild would
produce.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from foldback import reference  # noqa: E402

SOURCE = ROOT / "page" / "index.html"
PUBLISHED = ROOT / "docs" / "index.html"
BEGIN = "<!-- BEGIN GENERATED REFERENCE -->"
END = "<!-- END GENERATED REFERENCE -->"


def render() -> str:
    text = SOURCE.read_text(encoding="utf-8")
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise SystemExit(f"{SOURCE} must contain exactly one generated region")
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    body = json.dumps(reference.build(), indent=1, sort_keys=True)
    if "<" in body or ">" in body or "&" in body:
        # A script element ends at the first `</script`, and JSON with markup in it could close
        # the element early and put the rest of the reference into the page as text.
        raise SystemExit("the reference block contains markup, which would break the page")
    return head + BEGIN + "\n" + body + "\n" + END + tail


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="compare rather than write, and exit 1 on a difference")
    arguments = parser.parse_args()
    built = render()
    if arguments.check:
        if not PUBLISHED.exists():
            print(f"{PUBLISHED.relative_to(ROOT)} does not exist")
            return 1
        current = PUBLISHED.read_text(encoding="utf-8")
        if current != built:
            print(f"{PUBLISHED.relative_to(ROOT)} is not what a rebuild produces "
                  f"({len(current)} characters published, {len(built)} rebuilt)")
            return 1
        print(f"{PUBLISHED.relative_to(ROOT)} matches a fresh build, "
              f"{len(built)} characters")
        return 0
    PUBLISHED.parent.mkdir(parents=True, exist_ok=True)
    PUBLISHED.write_text(built, encoding="utf-8")
    print(f"wrote {PUBLISHED.relative_to(ROOT)}, {len(built)} characters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
