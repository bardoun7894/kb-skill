"""Tests for the lint duplicate check (lint.check_duplicates) — the "resolve" step.

    python3 test_lint_duplicates.py
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import lint  # noqa: E402


def art(summary):
    return {"path": Path("x.md"), "summary": summary, "updated": "", "status": None, "links": set()}


ARTS = {
    "concepts/kb-toolchain-migration-pattern": art("Migrating the KB toolchain from the SDK to pi CLI"),
    "concepts/kb-toolchain-migration-to-pi-cli": art("KB toolchain migration from claude SDK to pi CLI"),
    "concepts/obs-brand-kit": art("Stream layout skinned to the portfolio green"),
    "sources/kb-toolchain-migration-notes": art("Raw notes on the KB toolchain migration to pi CLI"),
}
PAIR = ("concepts/kb-toolchain-migration-pattern", "concepts/kb-toolchain-migration-to-pi-cli")


class CandidatePairs(unittest.TestCase):
    def test_similar_titles_pair_and_unrelated_do_not(self):
        pairs = lint.duplicate_candidates(ARTS)
        self.assertIn(PAIR, pairs)
        self.assertFalse(any("obs-brand-kit" in p[0] or "obs-brand-kit" in p[1] for p in pairs))

    def test_redirects_and_superseded_are_skipped(self):
        arts = dict(ARTS)
        arts["concepts/kb-toolchain-pi-backend"] = art(
            "Redirect — canonical article is kb-toolchain-migration-to-pi-cli")
        arts["concepts/kb-toolchain-migration-old"] = {
            **art("KB toolchain migration from claude SDK to pi CLI"), "status": "superseded"}
        pairs = lint.duplicate_candidates(arts)
        self.assertFalse(any("pi-backend" in x or "migration-old" in x for p in pairs for x in p))

    def test_source_never_pairs_with_compiled_article(self):
        pairs = lint.duplicate_candidates(ARTS)
        self.assertFalse(any(p[0].startswith("sources/") != p[1].startswith("sources/") for p in pairs))


class CheckDuplicates(unittest.TestCase):
    def run_check(self, answers):
        with mock.patch.object(lint.kb_supersede, "load_articles", return_value=ARTS), \
             mock.patch.object(lint.jev, "ask", return_value=answers) as ask:
            return lint.check_duplicates(), ask

    def test_confident_duplicate_is_a_warning(self):
        issues, ask = self.run_check({"p0": {"type": "noul", "noul": 0.92}})
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "warning")
        self.assertEqual(issues[0]["check"], "duplicate")
        self.assertIn(PAIR[1], issues[0]["detail"])

    def test_low_probability_is_dropped(self):
        issues, _ = self.run_check({"p0": {"type": "noul", "noul": 0.2}})
        self.assertEqual(issues, [])

    def test_jev_unavailable_reports_unverified_not_pass(self):
        issues, _ = self.run_check(None)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "suggestion")
        self.assertIn("unverified", issues[0]["detail"])


if __name__ == "__main__":
    unittest.main()
