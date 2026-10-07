"""Lexical H1 evidence recovery; these tests do not model an HTML5 DOM."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from site_meta_audit import MetaParser


class HeadingCaptureContractTests(unittest.TestCase):
    def parse(self, html):
        parser = MetaParser()
        parser.feed(html)
        parser.finish()
        return parser

    def test_valid_headings_inline_entities_and_unicode(self):
        parser = self.parse("<h1> First <em>heading</em> &amp; &#x4E2D; </h1>"
                            "<p>Outside</p><h1>Second&nbsp;heading</h1>")
        self.assertEqual(parser.h1, ["First heading & 中", "Second heading"])

    def test_stray_closers_do_not_duplicate_or_create_headings(self):
        parser = self.parse("</h1><h1>Only</h1>Outside</h1></h1>")
        self.assertEqual(parser.h1, ["Only"])
        self.assertEqual(parser._current_h1, [])
        self.assertFalse(parser._in_h1)

    def test_new_h1_preserves_preceding_unclosed_heading(self):
        parser = self.parse("<h1>First <em>inline</em><h1>Second</h1></h1>")
        self.assertEqual(parser.h1, ["First inline", "Second"])

    def test_other_heading_starts_end_h1_without_capturing_their_text(self):
        for level in range(2, 7):
            with self.subTest(level=level):
                parser = self.parse(f"<h1>Recover<h{level}>Other</h{level}>Tail</h1>")
                self.assertEqual(parser.h1, ["Recover"])

    def test_mismatched_heading_closers_preserve_active_h1_once(self):
        for level in range(2, 7):
            with self.subTest(level=level):
                parser = self.parse(f"<h1>Recover</h{level}>Tail</h1></h{level}>")
                self.assertEqual(parser.h1, ["Recover"])

    def test_eof_preserves_heading_once_and_clears_state(self):
        parser = self.parse("<h1>Unclosed <strong>heading</strong>")
        parser.finish()
        self.assertEqual(parser.h1, ["Unclosed heading"])
        self.assertEqual(parser._current_h1, [])
        self.assertFalse(parser._in_h1)

    def test_empty_headings_never_reuse_previous_buffer(self):
        parser = self.parse("<h1>First</h1><h1> \n </h1></h1><h1><h2>Other</h2><h1>")
        self.assertEqual(parser.h1, ["First"])

    def test_template_heading_tokens_do_not_end_active_heading(self):
        parser = self.parse("<h1>Before<template><h1>Hidden</h1>"
                            "<template><h2>Hidden too</h2></template></template>After</h1>")
        self.assertEqual(parser.h1, ["BeforeAfter"])

    def test_raw_text_heading_tokens_do_not_end_active_heading(self):
        for tag in ("script", "style"):
            with self.subTest(tag=tag):
                parser = self.parse(f"<h1>Before<{tag}><h2>Hidden</h2></h1></{tag}>After</h1>")
                self.assertEqual(parser.h1, ["BeforeAfter"])

    def test_svg_title_does_not_replace_document_title_or_heading(self):
        parser = self.parse("<title>Document</title><svg><title>Icon</title></svg><h1>Heading</h1>")
        self.assertEqual(parser.title, "Document")
        self.assertEqual(parser.h1, ["Heading"])

    def test_chunk_boundaries_preserve_same_recovery(self):
        parser = MetaParser()
        for chunk in ("<h", "1>First &am", "p; text<h", "1>Second</h", "2>Tail</h1>"):
            parser.feed(chunk)
        parser.finish()
        self.assertEqual(parser.h1, ["First & text", "Second"])


if __name__ == "__main__":
    unittest.main()
