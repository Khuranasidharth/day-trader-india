import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX

news = load("trader-news", "news")
OFF = os.path.join(FIX, "trader-news")
NOW = "2026-10-26T16:30:00+00:00"     # 10:00 PM IST, after the newest headline in the fixture


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = news.main(argv)
    return code, out.getvalue(), err.getvalue()


def items():
    with open(os.path.join(OFF, "gnews-RELIANCE.xml"), "rb") as fh:
        return news.parse_gnews(fh.read(), "RELIANCE")


class Parse(unittest.TestCase):
    def test_google_news_items(self):
        its = items()
        self.assertEqual(len(its), 45)
        first = [i for i in its if i["title"].startswith("Religare sets")][0]
        self.assertEqual(first["source"], "ad-hoc-news.de")
        self.assertFalse(first["title"].endswith("ad-hoc-news.de"))   # " - Publisher" is cut off the title
        self.assertEqual(news.to_ist(first["time"]).strftime("%Y-%m-%d %H:%M"), "2026-10-26 19:56")

    def test_tags_for_indian_headlines(self):
        its = news.tag(items(), {"RELIANCE": "Reliance Industries Limited"})
        religare = [i for i in its if i["title"].startswith("Religare sets")][0]
        self.assertIn("analyst", religare["tags"])
        ipo = [i for i in its if "Jio Platforms IPO" in i["title"]]
        self.assertTrue(ipo and all("capital" in i["tags"] for i in ipo))
        self.assertIn("RELIANCE", religare["touches"])

    def test_query_uses_the_company_name(self):
        self.assertEqual(news.short_name("Reliance Industries Limited"), "Reliance Industries")
        self.assertEqual(news.short_name("Mahindra & Mahindra Limited"), "Mahindra & Mahindra")
        q = news.gnews_query("RELIANCE", "Reliance Industries Limited", 48)
        self.assertEqual(q, '"Reliance Industries" OR "NSE:RELIANCE" when:2d')
        self.assertIn("hl=en-IN&gl=IN", news.gnews_url("RELIANCE", None))

    def test_move_line(self):
        with open(os.path.join(OFF, "chart-RELIANCE.json"), "rb") as fh:
            m = news.parse_chart(fh.read(), "RELIANCE")
        self.assertEqual((m["price"], m["prev_close"], m["pct"]), (1201.8, 1190.0, 0.99))


class Check(unittest.TestCase):
    def test_new_then_nothing_new(self):
        with tempfile.TemporaryDirectory() as d:
            st = os.path.join(d, "news.json")
            base = ["--tickers", "RELIANCE", "--offline", OFF, "--now", NOW, "--state", st, "--hours", "48",
                    "--instruments", ""]
            code, text, _ = run(base)
            self.assertEqual(code, 0)
            self.assertIn("RELIANCE   1,201.80 +0.99% vs yesterday's close 1,190.00", text)
            self.assertNotIn("MOVING", text)
            self.assertIn("corporate-filings-announcements?symbol=RELIANCE", text)
            self.assertIn("IST", text)
            code, text, _ = run(base)
            self.assertEqual(code, 1)
            self.assertIn("Nothing new.", text)

    def test_no_symbols(self):
        with tempfile.TemporaryDirectory() as d:
            code, _, err = run(["--watchlist", os.path.join(d, "x.json"), "--plan", os.path.join(d, "p.json"),
                                "--portfolio", os.path.join(d, "f.json"), "--offline", OFF])
        self.assertEqual(code, 2)
        self.assertIn("no symbols", err)


if __name__ == "__main__":
    unittest.main()
