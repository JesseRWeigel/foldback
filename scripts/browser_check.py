#!/usr/bin/env python3
"""Open docs/index.html in real headless Chrome and check what the page actually produced.

WHY THIS IS A REQUIRED STEP AND NOT AN OPTIONAL ONE. Every test in `tests/` imports a module. A
single unbalanced parenthesis anywhere in the page's inline script stops the whole script from
running, the page renders as static HTML with no numbers in it, and all 126 of those tests still
pass. So the assertions here are on values that only the page's own script can have produced.

WHAT IT DOES NOT DO. It does not judge from a screenshot, because the flag that sets the window
size and the flag that sets the viewport are not the same flag. Every measurement below runs as
JavaScript inside the page through `Emulation.setDeviceMetricsOverride`, and the width is asserted
rather than assumed.

IT DOES NOT TRUST THE PAGE'S OWN VERDICT EITHER. The page reports PASS or FAIL for itself, and a
page whose arithmetic is broken is exactly the page whose self report cannot be believed. So the
rendered peaks come back here as numbers and are compared against `foldback.fold` in this process.
The page's verdict is checked as well, and disagreement between the two is itself a failure.

BOTH ENGINES ARE DRIVEN. Over http the page runs an AudioWorklet, which is the supported path.
From a `file://` URL the worklet's module cannot be fetched and the page falls back to a
ScriptProcessorNode. The page's comments claim both work, so both are run here and the engine name
the page reports is asserted, which is what turns that comment into a measurement.

If Chrome is not installed this FAILS with an install command. It does not skip. A skipped check
and a passing check are the same line in a log a week later.
"""

from __future__ import annotations

import functools
import http.server
import json
import pathlib
import socketserver
import subprocess
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from cdp import Chrome, ChromeMissing, find_chrome  # noqa: E402
from foldback import fold  # noqa: E402

PAGE = ROOT / "docs" / "index.html"
TITLE = "Aliasing you can hear"

READY = ("document.getElementById('selfcheck-json') && "
         "document.getElementById('selfcheck-json').textContent !== 'not run' "
         "? document.getElementById('selfcheck-json').textContent : ''")

# The overflow walk. Anything scrolling inside its own container on purpose is skipped, because
# a wide table in a bordered box is correct and only content escaping the page is not. This is
# never fixed with `overflow-x: hidden`, which hides the bug and blanks the probe at once.
OVERFLOW = r"""
(function () {
  var root = document.documentElement;
  var limit = root.clientWidth;
  var offenders = [];
  var all = document.querySelectorAll('body *');
  for (var i = 0; i < all.length; i++) {
    var node = all[i];
    var scrolls = false;
    for (var p = node.parentElement; p; p = p.parentElement) {
      var ox = getComputedStyle(p).overflowX;
      if (ox === 'auto' || ox === 'scroll') { scrolls = true; break; }
    }
    if (scrolls) continue;
    var box = node.getBoundingClientRect();
    if (box.width === 0 && box.height === 0) continue;
    if (box.right > limit + 0.5 || box.left < -0.5) {
      offenders.push({ tag: node.tagName.toLowerCase(), id: node.id || null,
                       left: Math.round(box.left * 10) / 10,
                       right: Math.round(box.right * 10) / 10 });
    }
  }
  return { clientWidth: limit, scrollWidth: root.scrollWidth,
           bodyOverflowX: getComputedStyle(document.body).overflowX,
           offenders: offenders.slice(0, 10), count: offenders.length };
})()
"""

READOUTS = r"""
(function () {
  function text(id) { var n = document.getElementById(id); return n ? n.textContent.trim() : null; }
  function number(id) { return Number(text(id).replace(/,/g, '')); }
  return {
    rate: number('rate'), nyquist: number('nyq'),
    asked: number('asked'), heard: number('heard'),
    side: text('side'), atten: text('atten'),
    filterLabel: text('filter'),
    filterPressed: document.getElementById('filter').getAttribute('aria-pressed'),
    orderRows: document.getElementById('ordertable')
                 .querySelectorAll('tbody tr').length,
    orderCells: Array.prototype.map.call(
      document.getElementById('ordertable').querySelectorAll('tbody tr'),
      function (row) {
        return Array.prototype.map.call(row.cells, function (c) { return c.textContent; });
      }),
    checkRows: document.getElementById('checktable')
                 .querySelectorAll('tbody tr').length,
    verdict: text('selfcheck')
  };
})()
"""

INK = r"""
(function () {
  function ink(id) {
    var canvas = document.getElementById(id);
    var data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
    var r0 = data[0], g0 = data[1], b0 = data[2], count = 0;
    for (var i = 0; i < data.length; i += 4) {
      if (Math.abs(data[i] - r0) + Math.abs(data[i + 1] - g0) + Math.abs(data[i + 2] - b0) > 24) {
        count++;
      }
    }
    return count;
  }
  return { spectrum: ink('spectrum'), foldmap: ink('foldmap') };
})()
"""


class Server:
    """A local server on a port the operating system picks.

    Port zero on purpose. Starting a server on a fixed port that is already bound fails quietly in
    the background while `curl` happily returns 200 from whatever was already there, and the check
    then reads an entirely different project's page.
    """

    def __init__(self, directory: pathlib.Path):
        handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                    directory=str(directory))

        class Quiet(http.server.ThreadingHTTPServer):
            allow_reuse_address = True

            def handle_error(self, request, address):
                pass

        self.server = Quiet(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/index.html"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def quiet_handler_logging():
    http.server.SimpleHTTPRequestHandler.log_message = lambda *args, **kwargs: None


class Report:
    def __init__(self):
        self.problems = []
        self.notes = []

    def require(self, condition, message):
        if not condition:
            self.problems.append(message)
        return condition

    def note(self, message):
        self.notes.append(message)


def read_self_check(chrome, url, report, expected_engine):
    chrome.navigate(url)
    raw = chrome.wait_for(READY, timeout=180)
    result = json.loads(raw)

    report.require(not result["errors"], f"the page reported errors: {result['errors']}")
    report.require(result["engine"] == expected_engine,
                   f"expected the {expected_engine} engine and the page used {result['engine']}")
    report.require(result["ok"], f"the page's own self check said FAIL: {result}")
    report.require(result["liveSampleRate"] in (44100, 48000, 8000, 96000, 22050, 16000),
                   f"the audio context reported {result['liveSampleRate']} Hz")

    # The page's verdict is one opinion. Here is the other one, on the same numbers.
    checked = 0
    for row in result["rows"]:
        rate, asked = float(row["rate"]), float(row["asked"])
        expected = fold.alias_of(asked, rate)
        report.require(abs(row["formula"] - expected) < 1e-6,
                       f"the page's formula says {row['formula']} for {asked} Hz at {rate} Hz "
                       f"and this process says {expected}")
        report.require(abs(row["python"] - expected) < 1e-6,
                       f"the reference block says {row['python']} for {asked} Hz at {rate} Hz")
        report.require(row["rendered"] is not None,
                       f"{asked} Hz at {rate} Hz rendered as silence and should not have")
        if row["rendered"] is not None:
            bin_width = rate / 8192
            report.require(abs(row["rendered"] - expected) < bin_width,
                           f"{asked} Hz at {rate} Hz rendered a peak at {row['rendered']} and the "
                           f"arithmetic says {expected}, which is more than one {bin_width:.2f} "
                           f"Hz bin apart")
        checked += 1
    report.require(checked >= 14,
                   f"only {checked} frequencies were rendered in the browser")

    for row in result["degenerate"]:
        rate, asked = float(row["rate"]), float(row["asked"])
        report.require(fold.is_degenerate(asked, rate),
                       f"{asked} Hz at {rate} Hz was treated as degenerate and is not")
        report.require(row["peak"] is None and row["loudest"] < 1e-6,
                       f"{asked} Hz at {rate} Hz should have sampled to silence, "
                       f"loudest {row['loudest']}")
    report.require(len(result["degenerate"]) >= 6,
                   f"only {len(result['degenerate'])} degenerate frequencies were exercised")

    for row in result["filter"]:
        report.require(row["measured"] < -9.0,
                       f"the filter only moved {row['measured']:.2f} dB at {row['asked']} Hz, "
                       f"order {row['order']}")
        report.require(abs(row["measured"] - row["python"]) < 0.5,
                       f"the browser measured {row['measured']:.2f} dB and Python measured "
                       f"{row['python']:.2f} dB at {row['asked']} Hz, order {row['order']}")
    report.require(len(result["filter"]) >= 6,
                   f"only {len(result['filter'])} filter measurements were taken")

    worst = max((abs(r["rendered"] - r["formula"]) for r in result["rows"]
                 if r["rendered"] is not None), default=None)
    report.note(f"{expected_engine}: {len(result['rows'])} frequencies rendered, worst peak "
                f"{worst:.3f} Hz from the formula, {len(result['filter'])} filter measurements "
                f"from {min(r['measured'] for r in result['filter']):.1f} to "
                f"{max(r['measured'] for r in result['filter']):.1f} dB, "
                f"{len(result['degenerate'])} degenerate frequencies silent")
    return result


def drive_the_controls(chrome, report):
    """Move the slider and the filter toggle, and check the page answers with the right numbers."""
    before = chrome.evaluate(READOUTS, expect_title=TITLE)
    rate = before["rate"]
    report.require(before["orderRows"] == 4,
                   f"the order table has {before['orderRows']} rows and should have four")
    report.require(all(cell.endswith("dB") for row in before["orderCells"] for cell in row[1:]),
                   "the order table has a cell that is not a decibel figure")
    report.require(before["checkRows"] >= 14,
                   f"the self check table has {before['checkRows']} rows")
    report.require(before["verdict"].startswith("PASS"),
                   f"the page's verdict line reads {before['verdict']!r}")

    for multiple in (0.5, 1.4, 2.6, 3.7):
        asked = round(multiple * rate / 2.0)
        chrome.evaluate(
            "(function () { var s = document.getElementById('freq'); s.value = "
            + str(asked) + "; s.dispatchEvent(new Event('input')); return true; })()",
            expect_title=TITLE)
        now = chrome.evaluate(READOUTS, expect_title=TITLE)
        expected = fold.alias_of(asked, rate)
        report.require(now["asked"] == asked,
                       f"the slider was set to {asked} and the page shows {now['asked']}")
        report.require(abs(now["heard"] - expected) < 0.2,
                       f"at {asked} Hz the page says it hears {now['heard']} Hz and the "
                       f"arithmetic says {expected:.1f} Hz")
        above = asked > rate / 2.0
        report.require(("folded" in now["side"]) == above,
                       f"at {asked} Hz the badge reads {now['side']!r}")
        if above:
            report.require(f"folded {fold.folds_below(asked, rate)}" in now["side"],
                           f"at {asked} Hz the badge reads {now['side']!r} and the fold count is "
                           f"{fold.folds_below(asked, rate)}")

    # The toggle. A checkbox that changes no number is the failure this whole project is about.
    off = chrome.evaluate(READOUTS, expect_title=TITLE)
    report.require(off["filterPressed"] == "false", "the filter started switched on")
    report.require("nothing is filtered" in off["atten"],
                   f"with the filter off the page says {off['atten']!r}")
    chrome.evaluate("(document.getElementById('filter').click(), true)", expect_title=TITLE)
    on = chrome.evaluate(READOUTS, expect_title=TITLE)
    report.require(on["filterPressed"] == "true", "clicking the filter button did not press it")
    report.require(on["filterLabel"].endswith("on"),
                   f"the button reads {on['filterLabel']!r} after being pressed")
    report.require("cut by" in on["atten"] and "dB" in on["atten"],
                   f"with the filter on the page says {on['atten']!r}")
    report.require(off["atten"] != on["atten"],
                   "the filter toggle changed nothing the page prints")
    report.note(f"the toggle at {off['asked']:.0f} Hz: {off['atten']!r} becomes {on['atten']!r}")

    # And a steeper order has to print a bigger number, at the same frequency.
    figures = {}
    for order in (2, 4, 6, 8):
        chrome.evaluate(
            "(function () { var s = document.getElementById('order'); s.value = '"
            + str(order) + "'; s.dispatchEvent(new Event('change')); return true; })()",
            expect_title=TITLE)
        text = chrome.evaluate(READOUTS, expect_title=TITLE)["atten"]
        figures[order] = float(text.split("cut by")[1].split("dB")[0])
    for lower, higher in zip((2, 4, 6), (4, 6, 8)):
        report.require(figures[higher] < figures[lower] - 3.0,
                       f"order {higher} prints {figures[higher]} dB and order {lower} prints "
                       f"{figures[lower]} dB")
    report.note("order 2, 4, 6, 8 at that tone: "
                + ", ".join(f"{figures[o]:.1f} dB" for o in (2, 4, 6, 8)))

    chrome.evaluate("(document.getElementById('filter').click(), true)", expect_title=TITLE)


def check_layout(chrome, report):
    for width, height in ((1280, 900), (768, 1024), (390, 844), (320, 720)):
        chrome.viewport(width, height)
        chrome.evaluate("(window.dispatchEvent(new Event('resize')), true)", expect_title=TITLE)
        probe = chrome.evaluate(OVERFLOW, expect_title=TITLE)
        report.require(probe["clientWidth"] == width,
                       f"asked for a {width} pixel viewport and measured {probe['clientWidth']}")
        report.require(probe["bodyOverflowX"] != "hidden",
                       "the body hides horizontal overflow, which masks the bug and blanks "
                       "this probe at the same time")
        report.require(probe["count"] == 0,
                       f"at {width} pixels wide, {probe['count']} element(s) escape the page: "
                       f"{probe['offenders']}")
        report.require(probe["scrollWidth"] <= width + 1,
                       f"at {width} pixels wide the document scrolls to {probe['scrollWidth']}")
    chrome.viewport(1280, 900)
    chrome.evaluate("(window.dispatchEvent(new Event('resize')), true)", expect_title=TITLE)


FLOOR = 2000


def check_drawing(chrome, report, where):
    """Both canvases have to have drawn something, and the count is not printed.

    The exact number of coloured pixels moves by a few hundred between runs, because the spectrum
    is drawn from whatever the audio callback last handed over and that depends on timing. This
    transcript is pasted into the README and compared against a fresh run, so a figure that moves
    would mean the two could never converge. The threshold is the claim, and the exact count
    appears only when it fails, which is when it is worth having.
    """
    ink = chrome.evaluate(INK, expect_title=TITLE)
    low = [name for name, count in sorted(ink.items()) if count <= FLOOR]
    for name in low:
        report.require(False,
                       f"{where}: the {name} canvas has {ink[name]} coloured pixels, which is a "
                       f"canvas that did not draw")
    if not low:
        report.note(f"{where}: both canvases drew, each over {FLOOR} coloured pixels")


def console_messages(chrome):
    """Errors and uncaught exceptions fail. Warnings are printed and do not.

    The split is deliberate. An error or a thrown exception means something the page asked for
    did not happen. A warning here is Chrome's advice about how `getImageData` could be faster,
    which is the browser talking about the check rather than about the page, and failing on it
    would mean the only way to pass is to stop looking at the canvas.
    """
    bad, mild = [], []
    for event in chrome.drain():
        if event.get("method") == "Log.entryAdded":
            entry = event["params"]["entry"]
            line = f"{entry.get('level')}: {entry.get('text', '')[:150]}"
            (bad if entry.get("level") == "error" else mild).append(line)
        if event.get("method") == "Runtime.exceptionThrown":
            details = event["params"]["exceptionDetails"]
            bad.append("uncaught: " + str(details.get("text"))[:150])
    return bad, mild


def main() -> int:
    quiet_handler_logging()
    report = Report()
    if not PAGE.exists():
        print(f"FAIL {PAGE.relative_to(ROOT)} does not exist, so there is nothing to open")
        return 1
    try:
        binary = find_chrome()
    except ChromeMissing as missing:
        print(f"FAIL {missing}")
        print("      This step is not optional. Without a browser, nothing in this project has "
              "been shown to run in one, and the unit tests all pass on a page whose script "
              "never executes.")
        return 1
    version = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=120)
    report.note(version.stdout.strip() or "an unnamed Chrome")

    server = Server(PAGE.parent)
    try:
        with Chrome(binary) as chrome:
            chrome.call("Page.enable")
            chrome.call("Runtime.enable")
            chrome.call("Log.enable")
            chrome.viewport(1280, 900)
            read_self_check(chrome, server.url, report, "AudioWorklet")
            drive_the_controls(chrome, report)
            check_drawing(chrome, report, "over http")
            check_layout(chrome, report)
            errors, warnings = console_messages(chrome)
            for line in errors:
                report.problems.append(f"the console said: {line}")
            for line in warnings:
                report.note(f"console warning, not a failure: {line}")
    finally:
        server.close()

    # The second engine. From a file URL the worklet module cannot be fetched, and the page is
    # supposed to notice and fall back rather than falling silent.
    with Chrome(binary) as chrome:
        chrome.call("Page.enable")
        chrome.call("Runtime.enable")
        chrome.viewport(1280, 900)
        read_self_check(chrome, "file://" + str(PAGE.resolve()), report, "ScriptProcessorNode")
        check_drawing(chrome, report, "from a file url")

    for line in report.notes:
        print(f"  {line}")
    for line in report.problems:
        print(f"FAIL {line}")
    if report.problems:
        print(f"FAIL {len(report.problems)} problem(s) in a real browser")
        return 1
    print("the page runs in a real browser on both audio engines, and its numbers agree with "
          "the tested Python")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
