import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX

scan = load("trader-scanner", "scan")
D = os.path.join(FIX, "trader-scanner")
WALL = os.path.join(D, "wall5m-2026-10-26.json.gz")
SPARK = os.path.join(D, "daily-spark-2026-10-26.json")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = scan.main(argv)
    return code, out.getvalue(), err.getvalue()


class Symbols(unittest.TestCase):
    def test_yahoo_spelling(self):
        self.assertEqual(scan.to_yahoo("M&M"), "M&M.NS")
        self.assertEqual(scan.nse_symbol("bajaj-auto.ns"), "BAJAJ-AUTO")
        self.assertIn("M%26M.NS,BAJAJ-AUTO.NS", scan.spark_path(["M&M", "BAJAJ-AUTO"], "1d", "5m"))


class Universe(unittest.TestCase):
    def test_eq_series_only_with_upstox_ticks_and_keys(self):
        with tempfile.TemporaryDirectory() as d:
            u, i = os.path.join(d, "u.txt"), os.path.join(d, "i.json")
            code, text, _ = run(["universe", "--offline", os.path.join(D, "universe"), "--out", u,
                                 "--instruments", i])
            self.assertEqual(code, 0)
            with open(u, encoding="utf-8") as fh:
                syms = [ln.split("|")[0] for ln in fh.read().splitlines()]
            inst = read(i)["instruments"]
        self.assertEqual(len(syms), 30)
        self.assertIn("M&M", syms)
        self.assertIn("BAJAJ-AUTO", syms)
        self.assertIn("4 series BE (trade-to-trade, no intraday)", text)
        self.assertEqual(inst["RELIANCE"]["instrument_key"], "NSE_EQ|INE002A01018")
        self.assertEqual(inst["RELIANCE"]["tick"], 0.1)
        self.assertNotIn("NIFTYBEES", inst)                    # ETFs are not on NSE's equity list

    def test_without_upstox_the_key_comes_from_the_isin(self):
        with open(os.path.join(D, "universe", "EQUITY_L.csv"), encoding="utf-8") as fh:
            kept, inst, _ = scan.build_universe(fh.read(), None)
        self.assertEqual(inst["TCS"]["instrument_key"], "NSE_EQ|INE467B01029")
        self.assertIsNone(inst["TCS"]["tick"])

    def test_band_tick(self):
        self.assertEqual(scan.band_tick(188.59), 0.01)
        self.assertEqual(scan.band_tick(923.4), 0.05)
        self.assertEqual(scan.band_tick(11026.0), 1.00)


class Orb(unittest.TestCase):
    def test_10_00_replay(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "w.json")
            code, text, _ = run(["orb", "--offline", WALL, "--now", "2026-10-26 10:00", "--out", out])
            self.assertEqual(code, 0)
            doc = read(out)
        self.assertEqual(doc["scanned"], 30)
        self.assertEqual(len(doc["hits"]), 19)
        rel = [h for h in doc["hits"] if h["symbol"] == "RELIANCE"][0]
        self.assertEqual((rel["at"], rel["price"], rel["or_high"], rel["or_low"]), ("10:00 AM", 1193.6, 1192.0, 1175.3))
        self.assertEqual(doc["hits"][0]["symbol"], "TATASTEEL")      # 9:35 AM, the earliest
        self.assertIn("15-minute range (9:15 AM to 9:30 AM)", text)
        self.assertIn("₹1,193.60", text)

    def test_too_early(self):
        code, _, err = run(["orb", "--offline", WALL, "--now", "2026-10-26 09:32", "--no-write"])
        self.assertEqual(code, 1)
        self.assertIn("9:15 AM to 9:30 AM", err)

    def test_holiday(self):
        code, _, err = run(["orb", "--offline", WALL, "--now", "2026-10-20 10:00", "--no-write"])
        self.assertEqual(code, 1)
        self.assertIn("Dussehra", err)


class Daily(unittest.TestCase):
    def test_setups_after_the_close(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "w.json")
            code, text, _ = run(["daily", "--offline", SPARK, "--now", "2026-10-26 18:00", "--out", out])
            doc = read(out)
        self.assertEqual(code, 0)
        self.assertEqual(doc["as_of"], "2026-10-26 close")
        tags = {h["symbol"]: h["setups"] for h in doc["hits"]}
        self.assertEqual(tags["TCS"], ["breakout_20d", "bull_flag"])
        self.assertIn("oversold", tags["NTPC"])
        self.assertIn("₹50+ and 500,000+ shares", text)

    def test_todays_bar_waits_for_the_close(self):
        code, text, _ = run(["daily", "--offline", SPARK, "--now", "2026-10-26 12:00", "--no-write"])
        self.assertIn("closes through 2026-10-23", text)


if __name__ == "__main__":
    unittest.main()
