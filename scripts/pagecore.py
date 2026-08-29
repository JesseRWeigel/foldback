#!/usr/bin/env python3
"""Pull the arithmetic out of the page and run it under node.

ONE COPY OF THE FORMULAS EXISTS IN JAVASCRIPT and it lives inside `page/index.html`, between the
two core markers. The page hands that element's own text to `addModule` to build its AudioWorklet,
so extracting it here is running the same characters the browser runs rather than a copy that can
drift.

Both `scripts/parity.py` and `scripts/measure.py` need this, which is why it is its own file
rather than two extractions that could disagree about what the core block is.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = ROOT / "page" / "index.html"
BEGIN = "// === FOLDBACK CORE BEGIN ==="
END = "// === FOLDBACK CORE END ==="

# An AudioWorklet has no page around it, so anything here that reached for one would throw inside
# the worklet while working fine in the fallback engine, which is the kind of difference nobody
# notices until a reader opens the page over http.
FORBIDDEN = ("document.", "window.", "location.", "navigator.", "self.",
             "getElementById", "requestAnimationFrame")


class NoNode(RuntimeError):
    pass


def source() -> str:
    text = PAGE.read_text(encoding="utf-8")
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise SystemExit(f"{PAGE.name} must contain exactly one core block, found "
                         f"{text.count(BEGIN)} begin and {text.count(END)} end markers")
    body = text.split(BEGIN, 1)[1].split(END, 1)[0]
    # Comments are stripped before this search. The block's own header says in prose that it must
    # never touch `document` or `window`, and a search over the raw text finds that sentence and
    # refuses the file for saying the right thing.
    code = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL))
    for forbidden in FORBIDDEN:
        if forbidden in code:
            raise SystemExit(f"the core block uses {forbidden}, so an AudioWorklet running it "
                             f"would throw and the page would only work on the fallback engine")
    return BEGIN + body + END


def run(driver: str, timeout: float = 600.0) -> str:
    """Run the core plus a driver under node and return whatever the driver printed."""
    node = shutil.which("node")
    if node is None:
        raise NoNode(
            "node is not on the path, and the page's own JavaScript cannot be run without it.\n"
            "Install it with: apt-get install nodejs   (or: nvm install 24)\n"
            "Nothing here falls back to comparing the Python against itself, because that would "
            "report success for a check that did not run.")
    with tempfile.TemporaryDirectory() as area:
        path = pathlib.Path(area) / "core.mjs"
        path.write_text(source() + "\n" + driver, encoding="utf-8")
        done = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=timeout)
    if done.returncode != 0:
        raise SystemExit(f"node exited {done.returncode}:\n{done.stderr[-2000:]}")
    return done.stdout
