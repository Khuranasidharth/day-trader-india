import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX

deals = load("trader-deals", "deals")
OFF = os.path.join(FIX, "trader-deals")
# a made-up block deal, in the layout of NSE's block.csv (the real file was empty that day)
BLOCK = ("Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price\n"
         "26-OCT-2026,RELIANCE,Reliance Industries Ltd,EXAMPLE FUND,BUY,250000,1195.40\n")


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = deals.main(argv)
    return code, out.getvalue(), err.getvalue()


def bulk():
    with open(os.path.join(OFF, "bulk.csv"), encoding="utf-8") as fh:
        return deals.parse(fh.read(), "bulk")


class Parse(unittest.TestCase):
    def test_real_bulk_file(self):
        d = bulk()
        self.assertEqual(len(d), 89)
        a = d[0]
        self.assertEqual((a["date"], a["symbol"], a["side"], a["qty"], a["price"]),
                         ("2026-10-26", "APOLLO", "buy", 2465951, 410.93))
        self.assertEqual(a["client"], "QE SECURITIES LLP")

    def test_no_records_is_an_empty_day(self):
        with open(os.path.join(OFF, "block.csv"), encoding="utf-8") as fh:
            self.assertEqual(deals.parse(fh.read(), "block"), [])

    def test_block_layout(self):
        d = deals.parse(BLOCK, "block")
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["value"], 298850000.0)

    def test_net_per_client(self):
        s = deals.by_stock(bulk())["APOLLO"]
        jump = s["clients"]["JUMP TRADING FINANCIAL INDIA PRIVATE LIMITED"]
        self.assertTrue(jump["both_sides"])
        self.assertEqual(jump["net"], 0)


class Commands(unittest.TestCase):
    def test_today_then_new_then_nothing_new(self):
        with tempfile.TemporaryDirectory() as d:
            st = os.path.join(d, "deals.json")
            base = ["--offline", OFF, "--state", st, "--now", "2026-10-26T13:00:00",
                    "--watchlist", os.path.join(d, "w.json"), "--plan", os.path.join(d, "p.json"),
                    "--portfolio", os.path.join(d, "f.json")]
            code, text, _ = run(["today", "--min-crore", "50"] + base)
            self.assertEqual(code, 0)
            self.assertIn("NSE bulk and block deals on 2026-10-26", text)
            self.assertIn("both sides", text)
            code, text, _ = run(["new"] + base)
            self.assertEqual(code, 1)          # "today" already recorded every deal
            code, text, _ = run(["history", "--symbol", "APOLLO"] + base)
            self.assertEqual(code, 0)
            self.assertIn("APOLLO (Apollo Micro Systems Ltd): 4 bulk deals", text)

    def test_flags_a_watched_stock(self):
        with tempfile.TemporaryDirectory() as d:
            wl = os.path.join(d, "w.json")
            with open(wl, "w") as fh:
                json.dump({"hits": [{"symbol": "APOLLO"}]}, fh)
            code, text, _ = run(["today", "--symbol", "APOLLO", "--offline", OFF, "--dry-run", "--watchlist", wl,
                                 "--state", os.path.join(d, "s.json")])
        self.assertIn("<- you watch or hold it", text)


if __name__ == "__main__":
    unittest.main()
