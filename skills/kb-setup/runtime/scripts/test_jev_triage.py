"""Tests for the kb-ingest Jev triage (jev_triage.py).

    python3 test_jev_triage.py
"""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import jev_triage  # noqa: E402

GOOD = {
    "worth": {"type": "choice", "choice": "skip", "confidence": 0.9},
    "kind": {"type": "choice", "choice": "source", "confidence": 0.8},
    "duplicate": {"type": "noul", "noul": 0.1},
}


class TriageOne(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        raw = root / "raw"
        raw.mkdir()
        self.f = raw / "note.md"
        self.f.write_text("some content worth judging\n" * 50)

        p = mock.patch.object(jev_triage, "RAW_DIR", raw)
        p.start()
        self.addCleanup(p.stop)

    def call(self, answers, have_key=True):
        with mock.patch.object(jev_triage.jev, "ask", return_value=answers):
            return jev_triage.triage_one(self.f, {}, have_key)

    def test_happy_path(self):
        r = self.call(GOOD)
        self.assertEqual(r["worth"], "skip")
        self.assertEqual(r["kind"], "source")
        self.assertAlmostEqual(r["duplicate"], 0.1)
        self.assertFalse(r["fell_open"])

    def test_no_key_defaults_to_ingest(self):
        r = jev_triage.triage_one(self.f, {}, have_key=False)
        self.assertEqual(r["worth"], "ingest")
        self.assertTrue(r["fell_open"])

    def test_client_returning_none_defaults_to_ingest(self):
        """jev.ask returns None on no key, HTTP error, timeout or malformed body."""
        r = self.call(None)
        self.assertEqual(r["worth"], "ingest")
        self.assertTrue(r["fell_open"])

    def test_unrecognised_verdict_defaults_to_ingest(self):
        """A garbage label must never be read as permission to drop the file."""
        r = self.call({"worth": {"type": "choice", "choice": "delete_everything"}})
        self.assertEqual(r["worth"], "ingest")

    def test_missing_worth_defaults_to_ingest(self):
        r = self.call({"kind": {"type": "choice", "choice": "concept"}})
        self.assertEqual(r["worth"], "ingest")

    def test_unrecognised_kind_is_dropped_not_guessed(self):
        r = self.call({**GOOD, "kind": {"type": "choice", "choice": "nonsense"}})
        self.assertIsNone(r["kind"])

    def test_non_numeric_duplicate_is_none(self):
        r = self.call({**GOOD, "duplicate": {"type": "noul", "noul": "yes"}})
        self.assertIsNone(r["duplicate"])


class Excerpt(unittest.TestCase):
    """raw/ can be gigabytes — the excerpt must stay bounded no matter the file size."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_large_file_is_bounded(self):
        big = self.root / "big.jsonl"
        big.write_text("x" * 5_000_000)
        out = jev_triage.excerpt(big)
        self.assertLessEqual(len(out), jev_triage.HEAD_CHARS + jev_triage.TAIL_CHARS + 10)

    def test_small_file_is_returned_whole(self):
        small = self.root / "small.md"
        small.write_text("short content")
        self.assertEqual(jev_triage.excerpt(small), "short content")

    def test_unreadable_file_does_not_raise(self):
        self.assertIn("unreadable", jev_triage.excerpt(self.root / "missing.md"))

    def test_binary_garbage_does_not_raise(self):
        b = self.root / "b.bin"
        b.write_bytes(bytes(range(256)) * 20)
        self.assertIsInstance(jev_triage.excerpt(b), str)


class Inbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        raw = root / "raw"
        (raw / "assets").mkdir(parents=True)
        (raw / "assets" / "img.png").write_text("x")
        (raw / ".gitkeep").write_text("")
        (raw / ".DS_Store").write_text("x")
        (raw / "keep.md").write_text("aaa")
        (raw / "done.md").write_text("bbb")
        log = root / "log.md"
        log.write_text("ingested done.md at some point")

        for p in (
            mock.patch.object(jev_triage, "RAW_DIR", raw),
            mock.patch.object(jev_triage, "LOG_FILE", log),
        ):
            p.start()
            self.addCleanup(p.stop)

    def test_skips_assets_dotfiles_and_already_ingested(self):
        names = [p.name for p in jev_triage.inbox()]
        self.assertEqual(names, ["keep.md"])


class DupSkip(unittest.TestCase):
    """A high duplicate probability skips the file when --worth ingest is requested."""

    WORTH_INGEST_ANSWERS = {
        "worth": {"type": "choice", "choice": "ingest", "confidence": 0.9},
        "kind": {"type": "choice", "choice": "source", "confidence": 0.8},
        "duplicate": {"type": "noul", "noul": 0.95},
    }

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        raw = root / "raw"
        raw.mkdir()
        self.files = []
        for i in range(3):
            f = raw / f"note{i}.md"
            f.write_text("content\n" * 50)
            self.files.append(f)

        p = mock.patch.object(jev_triage, "RAW_DIR", raw)
        p.start()
        self.addCleanup(p.stop)

        # Pretend Jev has a key for the whole test, so triage() does not declare
        # every file fell_open and short-circuit --worth back to exit 1.
        mock.patch.object(jev_triage.jev, "typesafe_key", return_value="fake").start()
        mock.patch.object(jev_triage.jev, "api_key", return_value="fake").start()
        self.addCleanup(mock.patch.stopall)

    def _run_main(self, answers_per_file, argv_tail):
        """Stub jev.ask per file name, run main() with sys.argv set.

        `answers_per_file` is a list of answer dicts in the order they should be
        applied; any other file in the test's RAW_DIR will get a sensible default
        (worth=ingest, no duplicate) so callers can pass a subset and still see
        the rest of the inbox fall open cleanly.
        """
        default = {
            "worth": {"type": "choice", "choice": "ingest", "confidence": 0.9},
            "kind": {"type": "choice", "choice": "source", "confidence": 0.8},
            "duplicate": {"type": "noul", "noul": 0.0},
        }
        explicit = {f.name: ans for f, ans in zip(self.files, answers_per_file)}
        name_to_answers = {f.name: explicit.get(f.name, default) for f in self.files}

        def fake_ask(state, questions, tag=None, timeout=None):
            return name_to_answers.get(state.get("filename"))

        stderr = io.StringIO()
        stdout = io.StringIO()
        saved_argv = sys.argv
        sys.argv = ["jev_triage.py"] + argv_tail
        try:
            with mock.patch.object(jev_triage.jev, "ask", side_effect=fake_ask), \
                    contextlib.redirect_stdout(stdout), \
                    contextlib.redirect_stderr(stderr):
                rc = jev_triage.main()
        finally:
            sys.argv = saved_argv
        return rc, stdout.getvalue(), stderr.getvalue()

    def test_high_duplicate_dropped_from_worth_ingest(self):
        rc, out, err = self._run_main(
            [self.WORTH_INGEST_ANSWERS, self.WORTH_INGEST_ANSWERS, self.WORTH_INGEST_ANSWERS],
            ["--worth", "ingest", str(self.files[0]), str(self.files[1]), str(self.files[2])],
        )
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")  # all three dropped
        self.assertIn(f"dup-skip {self.files[0]} p=0.95", err)
        self.assertIn(f"dup-skip {self.files[1]} p=0.95", err)
        self.assertIn(f"dup-skip {self.files[2]} p=0.95", err)

    def test_below_threshold_duplicate_kept(self):
        answers_low = {**self.WORTH_INGEST_ANSWERS,
                       "duplicate": {"type": "noul", "noul": 0.85}}
        rc, out, err = self._run_main(
            [answers_low, answers_low, answers_low],
            ["--worth", "ingest", str(self.files[0]), str(self.files[1]), str(self.files[2])],
        )
        self.assertEqual(rc, 0)
        printed = [Path(line).name for line in out.strip().splitlines()]
        self.assertEqual(printed, ["note0.md", "note1.md", "note2.md"])
        self.assertNotIn("dup-skip", err)

    def test_none_duplicate_kept(self):
        answers_none = {**self.WORTH_INGEST_ANSWERS,
                        "duplicate": {"type": "noul", "noul": "yes"}}
        rc, out, err = self._run_main(
            [answers_none, answers_none, answers_none],
            ["--worth", "ingest", str(self.files[0]), str(self.files[1]), str(self.files[2])],
        )
        self.assertEqual(rc, 0)
        printed = [Path(line).name for line in out.strip().splitlines()]
        self.assertEqual(printed, ["note0.md", "note1.md", "note2.md"])
        self.assertNotIn("dup-skip", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
