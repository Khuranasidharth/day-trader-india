import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX

facts = load("trader-analyst", "facts")
OFF = os.path.join(FIX, "trader-analyst")


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = facts.main(argv)
    return code, out.getvalue(), err.getvalue()


def result(sym):
    with open(os.path.join(OFF, "fundamentals-%s.json" % sym), encoding="utf-8") as fh:
        data = facts.parse(fh.read(), sym)
    import datetime
    return facts.analyse(data, 6, None, sym, datetime.date(2026, 10, 26))


class Fiscal(unittest.TestCase):
    def test_indian_fiscal_labels(self):
        self.assertEqual(facts.fiscal_label("2026-06-30"), "Q1 FY27")
        self.assertEqual(facts.fiscal_label("2026-09-30"), "Q2 FY27")
        self.assertEqual(facts.fiscal_label("2025-12-31"), "Q3 FY26")
        self.assertEqual(facts.fiscal_label("2026-03-31"), "Q4 FY26")
        self.assertEqual(facts.fiscal_label("2026-03-31", annual=True), "FY26")

    def test_indian_grouping(self):
        self.assertEqual(facts.indian(309468), "3,09,468")
        self.assertEqual(facts.indian(1057219), "10,57,219")
        self.assertEqual(facts.indian(73188), "73,188")
        self.assertEqual(facts.indian(512), "512")


class Reliance(unittest.TestCase):
    def test_latest_quarter_and_growth(self):
        r = result("RELIANCE")
        q = r["quarters"][0]
        self.assertEqual((q["end"], q["fiscal"]), ("2026-06-30", "Q1 FY27"))
        self.assertEqual(q["revenue_yoy"], 27.0)          # against Q1 FY26
        self.assertEqual(q["eps_diluted"], 15.48)
        self.assertEqual(r["missing_quarters"], ["2025-09-30"])
        self.assertEqual(r["ttm"], {})                     # four quarters in a row are not there
        self.assertFalse(r["stale"])

    def test_report_says_the_gap_and_links_the_filing(self):
        code, text, _ = run(["RELIANCE", "--offline", OFF, "--now", "2026-10-26", "--instruments", ""])
        self.assertEqual(code, 0)
        self.assertIn("₹3,09,468 cr (+27.0% against Q1 FY26)", text)
        self.assertIn("Yahoo is missing Q2 FY26 (2025-09-30)", text)
        self.assertIn("corporate-filings-financial-results?symbol=RELIANCE", text)


class Others(unittest.TestCase):
    def test_tcs_ttm_runs_through_q2_fy27(self):
        r = result("TCS")
        self.assertEqual(r["quarters"][0]["fiscal"], "Q2 FY27")
        self.assertEqual(r["ttm"]["through"], "2026-09-30")

    def test_a_bank_with_an_old_quarter_is_flagged(self):
        r = result("HDFCBANK")
        self.assertTrue(r["stale"])
        self.assertTrue(r["eps_jump"])
        lines = " ".join(facts.changes(r))
        self.assertIn("newer results are out", lines)
        self.assertIn("bonus issue or a split", lines)

    def test_metrics_file(self):
        with tempfile.TemporaryDirectory() as d:
            m = os.path.join(d, "metrics.json")
            run(["RELIANCE", "TCS", "--offline", OFF, "--now", "2026-10-26", "--metrics", m, "--instruments", ""])
            with open(m, encoding="utf-8") as fh:
                doc = json.load(fh)
        self.assertEqual([c["symbol"] for c in doc["companies"]], ["RELIANCE", "TCS"])
        self.assertEqual(doc["companies"][0]["fiscal"], "Q1 FY27")


if __name__ == "__main__":
    unittest.main()
