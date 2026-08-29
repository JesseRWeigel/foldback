"""What can be said about the page without opening a browser.

This file is deliberately modest about what it proves. It reads `page/index.html` and
`docs/index.html` as text and checks the things that are true of the text: that there is exactly
one copy of the arithmetic, that nothing is fetched from anywhere, that the generated region is
where the build script expects it. It cannot tell you the page runs, because a single unbalanced
parenthesis stops an inline script from ever executing while every test in this file still passes.
That is what `scripts/browser_check.py` is for, and it is a step in `scripts/verify.sh` rather
than an optional extra.
"""

from __future__ import annotations

import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "page" / "index.html"
PUBLISHED = ROOT / "docs" / "index.html"


class OneFileAndNothingElse(unittest.TestCase):

    def test_both_pages_exist_and_are_a_reasonable_size(self):
        for path in (SOURCE, PUBLISHED):
            self.assertTrue(path.exists(), f"{path} is missing")
            self.assertGreater(len(path.read_text(encoding="utf-8")), 20000)

    def test_nothing_is_fetched_from_anywhere(self):
        """No CDN, no web font, no external audio, no image. One file and Web Audio."""
        for path in (SOURCE, PUBLISHED):
            text = path.read_text(encoding="utf-8")
            for attribute in ("src", "srcset", "poster", "data-src"):
                for match in re.finditer(rf'\b{attribute}\s*=\s*"([^"]*)"', text):
                    self.assertFalse(match.group(1).strip(),
                                     f"{path.name} fetches {match.group(1)}")
            for match in re.finditer(r'<link[^>]*\bhref\s*=\s*"([^"]*)"', text):
                self.fail(f"{path.name} has a link element pointing at {match.group(1)}")
            self.assertNotIn("@import", text)
            self.assertNotIn("fonts.googleapis", text)
            self.assertNotIn("cdn.", text)
            for word in ("fetch(", "XMLHttpRequest", "WebSocket", "importScripts"):
                self.assertNotIn(word, text, f"{path.name} uses {word}")

    def test_the_only_outbound_links_are_anchors_to_the_repository(self):
        for path in (SOURCE, PUBLISHED):
            text = path.read_text(encoding="utf-8")
            urls = set(re.findall(r'href\s*=\s*"(https?://[^"]*)"', text))
            self.assertTrue(urls, f"{path.name} has no source link at all")
            for url in urls:
                self.assertTrue(url.startswith("https://github.com/JesseRWeigel/foldback"),
                                f"{path.name} links out to {url}")

    def test_the_arithmetic_appears_exactly_once(self):
        """The worklet source is this element's own text, so a second copy could drift silently."""
        for path in (SOURCE, PUBLISHED):
            text = path.read_text(encoding="utf-8")
            self.assertEqual(text.count("// === FOLDBACK CORE BEGIN ==="), 1)
            self.assertEqual(text.count("// === FOLDBACK CORE END ==="), 1)
            self.assertEqual(text.count("function aliasOf("), 1)
            self.assertEqual(text.count("Math.abs(f - Math.round(f / fs) * fs)"), 1)

    def test_the_generated_region_is_where_the_build_script_expects_it(self):
        for path in (SOURCE, PUBLISHED):
            text = path.read_text(encoding="utf-8")
            self.assertEqual(text.count("<!-- BEGIN GENERATED REFERENCE -->"), 1)
            self.assertEqual(text.count("<!-- END GENERATED REFERENCE -->"), 1)
            self.assertLess(text.index("<!-- BEGIN GENERATED REFERENCE -->"),
                            text.index("<!-- END GENERATED REFERENCE -->"))

    def test_the_published_page_carries_real_numbers_and_the_source_carries_none(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("<!-- BEGIN GENERATED REFERENCE -->\n{}\n", source)

        published = PUBLISHED.read_text(encoding="utf-8")
        body = published.split("<!-- BEGIN GENERATED REFERENCE -->", 1)[1]
        body = body.split("<!-- END GENERATED REFERENCE -->", 1)[0]
        block = json.loads(body)
        self.assertEqual(set(block["alias"]), {"44100", "48000"})
        self.assertGreaterEqual(len(block["attenuation"]), 6)
        for row in block["attenuation"]:
            self.assertLess(row["db"], -9.0)

    def test_the_two_files_differ_only_inside_the_generated_region(self):
        def outside(text):
            head, rest = text.split("<!-- BEGIN GENERATED REFERENCE -->", 1)
            return head + rest.split("<!-- END GENERATED REFERENCE -->", 1)[1]
        self.assertEqual(outside(SOURCE.read_text(encoding="utf-8")),
                         outside(PUBLISHED.read_text(encoding="utf-8")))


class WhatThePageSaysAboutItself(unittest.TestCase):

    def test_it_reads_the_sample_rate_rather_than_assuming_one(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertIn("liveContext.sampleRate", text)
        self.assertIn('el("rate").textContent', text)

    def test_it_has_a_fallback_for_a_browser_with_no_working_audio_context(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertIn("would not open an audio context", text)

    def test_it_offers_every_order_the_python_can_build(self):
        text = SOURCE.read_text(encoding="utf-8")
        for order in (2, 4, 6, 8):
            self.assertIn(f'<option value="{order}"', text)

    def test_it_does_not_hedge_against_sideways_scroll(self):
        """`overflow-x: hidden` on the body hides the bug and blanks the probe that finds it."""
        text = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("overflow-x: hidden", text)
        self.assertNotIn("overflow-x:hidden", text)
        self.assertIn("overflow-x: auto", text, "wide tables should scroll in their own box")

    def test_the_self_check_writes_its_result_somewhere_a_harness_can_read_it(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertIn('id="selfcheck-json"', text)
        self.assertIn("JSON.stringify(result)", text)


class WritingStyle(unittest.TestCase):

    def test_nothing_in_this_repository_uses_an_em_dash(self):
        """The character is built from its code point rather than written down.

        A search for a literal em dash inside a file that contains a literal em dash finds itself,
        and the wrong repair is to exclude this file, which would disarm the check exactly where
        it is tested. So the needle is `chr(0x2014)` and this file stays clean like every other.
        """
        needle = chr(0x2014)
        self.assertEqual(len(needle), 1)
        offenders = []
        for path in sorted(ROOT.rglob("*")):
            if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if path.suffix not in (".py", ".html", ".md", ".sh", ".js", ".yml", ".yaml"):
                continue
            if needle in path.read_text(encoding="utf-8", errors="replace"):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [], "em dashes are not this project's house style")

    def test_and_that_search_would_find_one_if_there_were_one(self):
        """A positive control, because a search that reads nothing reports the same clean."""
        needle = chr(0x2014)
        planted = "a sentence with an em dash " + needle + " in the middle of it"
        self.assertIn(needle, planted)
        self.assertNotIn(needle, planted.replace(needle, ""))

    def test_no_source_file_carries_a_nul_byte(self):
        """A NUL makes git and grep treat a file as binary, and the secret scan then skips it."""
        offenders = []
        for path in sorted(ROOT.rglob("*")):
            if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if b"\0" in path.read_bytes():
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [], "write a NUL as the escape \\0 rather than as the byte")


if __name__ == "__main__":
    unittest.main()
