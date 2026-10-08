"""Jev gates in pick_model and flush.py. Run from this directory:

    python3 -m unittest test_jev_gate </dev/null
"""

import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import jev  # noqa: E402
import utils  # noqa: E402

with mock.patch("logging.basicConfig"):  # don't create flush.log next to the scripts
    import flush  # noqa: E402


def http_answer(answer):
    body = json.dumps({"answers": {"q": answer}}).encode()
    return mock.patch("urllib.request.urlopen", return_value=mock.MagicMock(
        __enter__=lambda s: io.BytesIO(body), __exit__=lambda *a: False))


class Base(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"})
        self.env.start()
        os.environ.pop("KB_FORCE_MODEL", None)
        os.environ.pop("JEV_DISABLED", None)

    def tearDown(self):
        self.env.stop()


class JevClient(Base):
    def test_sends_user_agent_and_questions(self):
        with http_answer({"type": "noul", "noul": 0.4}) as up:
            self.assertEqual(jev.noul("s", "x"), 0.4)
        req = up.call_args[0][0]
        self.assertEqual(req.get_header("User-agent"), "kb-skill-jev/1.0")
        self.assertEqual(up.call_args[1]["timeout"], 8.0)

    def test_error_returns_none(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
            self.assertIsNone(jev.noul("s", "x"))

    def test_disabled_makes_no_request(self):
        os.environ["JEV_DISABLED"] = "1"
        with mock.patch("urllib.request.urlopen") as up:
            self.assertIsNone(jev.noul("s", "x"))
        up.assert_not_called()

    def test_no_key_returns_none(self):
        os.environ.pop("OPENROUTER_API_KEY")
        with mock.patch("os.path.expanduser", return_value="/nonexistent/auth.json"), \
                mock.patch("urllib.request.urlopen") as up:
            self.assertIsNone(jev.noul("s", "x"))
        up.assert_not_called()


class PickModel(Base):
    def test_confident_jev_picks_tier(self):
        with http_answer({"choice": "opus", "confidence": 0.9}):
            self.assertEqual(utils.pick_model("query-short", 100, question="audit all"), utils.OPUS)

    def test_low_confidence_falls_back_to_size_rule(self):
        with http_answer({"choice": "opus", "confidence": 0.6}):
            self.assertEqual(utils.pick_model("query-short", 100, question="q"), utils.HAIKU)

    def test_escape_falls_back(self):
        with http_answer({"choice": "unclear", "confidence": 0.99}):
            self.assertEqual(utils.pick_model("query-deep", 100, question="q"), utils.SONNET)

    def test_forced_model_skips_jev(self):
        os.environ["KB_FORCE_MODEL"] = "m"
        with mock.patch("urllib.request.urlopen") as up:
            self.assertEqual(utils.pick_model("query-short", 100, question="q"), "m")
        up.assert_not_called()

    def test_no_question_or_compile_skips_jev(self):
        with mock.patch("urllib.request.urlopen") as up:
            self.assertEqual(utils.pick_model("query-short", 100), utils.HAIKU)
            self.assertEqual(utils.pick_model("compile-one", 100, question="q"), utils.SONNET)
        up.assert_not_called()


class FlushGate(Base):
    def test_low_noul_skips(self):
        with http_answer({"type": "noul", "noul": 0.05}):
            self.assertEqual(flush.jev_nothing_to_keep("hi"), 0.05)

    def test_high_noul_does_not_skip(self):
        with http_answer({"type": "noul", "noul": 0.15}):
            self.assertIsNone(flush.jev_nothing_to_keep("we decided X"))

    def test_error_does_not_skip(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
            self.assertIsNone(flush.jev_nothing_to_keep("hi"))

    def test_oversized_context_makes_no_request(self):
        with mock.patch("urllib.request.urlopen") as up:
            self.assertIsNone(flush.jev_nothing_to_keep("x" * 100_001))
        up.assert_not_called()


if __name__ == "__main__":
    unittest.main()
