import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX

al = load("trader-alerts", "alerts")
OFF = os.path.join(FIX, "trader-alerts")
PLAN = {"symbol": "RELIANCE", "date": "2026-10-26", "entry": 1193.6, "stop": 1183.6, "target": 1203.6,
        "flat_by": "15:05", "stop_label": "opening-range midpoint", "target_label": "1R"}


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = al.main(argv)
    return code, out.getvalue(), err.getvalue()


class Clock(unittest.TestCase):
    def test_open_closed_holiday(self):
        st = al.market_status(al.parse_now("2026-10-26 10:00"))
        self.assertTrue(st["open"])
        self.assertEqual((st["opens"], st["closes"]), ("09:15", "15:30"))
        st = al.market_status(al.parse_now("2026-10-26 15:31"))
        self.assertFalse(st["open"])
        self.assertEqual(st["next_open"], "2026-10-27 09:15")
        st = al.market_status(al.parse_now("2026-11-10 11:00"))
        self.assertIn("Diwali", st["reason"])

    def test_clock_command(self):
        code, text, _ = run(["clock", "--now", "2026-10-20 11:00"])
        self.assertIn("NSE holiday: Dussehra", text)
        self.assertIn("Next open: 2026-10-21 09:15 IST.", text)


class Quotes(unittest.TestCase):
    def test_offline_quotes_for_nse_symbols(self):
        q, errors = al.get_quotes(["RELIANCE", "m&m"], offline=OFF)
        self.assertEqual(errors, [])
        self.assertEqual(q["RELIANCE"]["price"], 1201.8)
        self.assertEqual(q["RELIANCE"]["prev_close"], 1190.0)
        self.assertEqual(q["M&M"]["currency"], "INR")

    def test_yahoo_url(self):
        self.assertIn("/v8/finance/chart/M%26M.NS?", al.yahoo_url("M&M"))


class Rules(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.rules = os.path.join(self.d, "alerts.json")
        self.state = os.path.join(self.d, "state.json")
        self.plan = os.path.join(self.d, "plan.json")
        with open(self.plan, "w") as fh:
            json.dump(PLAN, fh)

    def test_from_plan_then_flat_by_rings_once(self):
        code, text, _ = run(["add", "--from-plan", "--plan", self.plan, "--rules", self.rules])
        self.assertEqual(code, 0)
        self.assertIn("reliance-plan-stop", text)
        base = ["check", "--rules", self.rules, "--state", self.state, "--offline", OFF,
                "--prices-out", os.path.join(self.d, "p.json")]
        code, text, _ = run(base + ["--now", "2026-10-26 12:00"])
        self.assertEqual(code, 1)
        self.assertIn("Nothing hit", text)
        code, text, _ = run(base + ["--now", "2026-10-26 15:06"])
        self.assertEqual(code, 0)
        self.assertIn("it is 15:06 IST (set for 15:05)", text)
        code, text, _ = run(base + ["--now", "2026-10-26 15:10"])
        self.assertEqual(code, 1)

    def test_target_rings_when_the_price_is_there(self):
        run(["add", "--symbol", "RELIANCE", "--target", "1200", "--rules", self.rules])
        code, text, _ = run(["check", "--rules", self.rules, "--state", self.state, "--offline", OFF,
                             "--prices-out", os.path.join(self.d, "p.json"), "--now", "2026-10-26 12:00"])
        self.assertEqual(code, 0)
        self.assertIn("RELIANCE", text)


if __name__ == "__main__":
    unittest.main()
