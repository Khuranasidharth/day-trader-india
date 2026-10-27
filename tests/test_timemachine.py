import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX

tm = load("trader-timemachine", "timemachine")
DATA = os.path.join(FIX, "trader-timemachine", "RELIANCE-60d5m.json.gz")
FLAGS = ["--offline", DATA, "--symbol", "RELIANCE", "--date", "2026-10-26", "--entry", "1193.60",
         "--stop", "1183.60", "--target", "1203.60", "--entry-time", "10:00 AM", "--tick", "0.10",
         "--now", "2026-10-26 10:00"]


def read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = tm.main(argv)
    return code, out.getvalue(), err.getvalue()


class Session(unittest.TestCase):
    def test_72_bars_from_9_15(self):
        self.assertEqual(tm.SESSION_BARS, 72)
        self.assertEqual(tm.clock12(tm.OPEN_MIN), "9:15 AM")
        self.assertEqual(tm.clock12(tm.CLOSE_MIN), "3:15 PM")

    def test_tick_rounding(self):
        self.assertEqual(tm.tick_away(1183.65, True, 0.10), 1183.6)
        self.assertEqual(tm.tick_near(1203.55, 0.10), 1203.6)


class Example(unittest.TestCase):
    def test_the_example_numbers(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "tm.json")
            code, text, _ = run(["run", "--until", "15:05", "--write", out] + FLAGS)
            self.assertEqual(code, 0)
            doc = read(out)
        mc, h = doc["mc"], doc["history"]
        self.assertEqual((mc["p_target"], mc["p_stop"], mc["p_neither"]), (0.2264, 0.2987, 0.4749))
        self.assertEqual(mc["pool_sessions"], 58)
        self.assertEqual(doc["plan"]["entry_bar"], 8)
        self.assertEqual(h["rule"]["stop_rule"], "or_mid")
        self.assertEqual((h["triggered"], h["target"], h["stop"], h["close"]), (26, 13, 10, 3))
        self.assertTrue(doc["verdict"].startswith("Leans toward the stop"))
        self.assertIn("seed 19", text)

    def test_same_seed_same_numbers(self):
        a = json.loads(run(["run", "--json"] + FLAGS)[1])["mc"]
        b = json.loads(run(["run", "--json"] + FLAGS)[1])["mc"]
        self.assertEqual(a["p_target"], b["p_target"])
        self.assertEqual(a["median_close"], b["median_close"])

    def test_until_after_the_data_is_refused(self):
        code, _, err = run(["run", "--until", "15:25"] + FLAGS)
        self.assertEqual(code, 1)
        self.assertIn("no later than 3:15 PM", err)

    def test_nse_symbols_with_ampersand_are_accepted(self):
        p = tm.normalize_plan({"symbol": "M&M", "date": "2026-10-26", "entry": 2860.2, "stop": 2835.7,
                               "target": 2884.7, "entry_time": "10:00 AM"})
        self.assertEqual(p["symbol"], "M&M")


if __name__ == "__main__":
    unittest.main()
