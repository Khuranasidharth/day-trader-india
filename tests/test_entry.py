import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX

entry = load("trader-entry", "entry")
DAY = os.path.join(FIX, "trader-entry", "RELIANCE-2026-10-26-5m.json")


def chart():
    return entry.get_chart("RELIANCE", "5m", offline=DAY)


def at(hhmm, **kw):
    return entry.evaluate(chart(), entry.parse_now("2026-10-26 " + hhmm), **kw)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = entry.main(argv)
    return code, out.getvalue(), err.getvalue()


class Clock(unittest.TestCase):
    def test_ist_is_utc_plus_five_thirty_all_year(self):
        for month in (1, 7):
            utc = entry.parse_now("2026-%02d-15 09:15" % month)
            self.assertEqual(utc.strftime("%H:%M"), "03:45")
            self.assertEqual(entry.to_ist(utc).strftime("%H:%M"), "09:15")

    def test_nse_session_and_holidays(self):
        import datetime
        self.assertEqual(entry.session(datetime.date(2026, 10, 26)),
                         (datetime.time(9, 15), datetime.time(15, 30)))
        self.assertIsNone(entry.session(datetime.date(2026, 10, 20)))     # Dussehra
        self.assertIsNone(entry.session(datetime.date(2026, 11, 10)))     # Diwali Balipratipada
        self.assertIsNone(entry.session(datetime.date(2026, 10, 25)))     # Sunday
        self.assertEqual(entry.next_open(datetime.date(2026, 10, 19)), "2026-10-21 09:15")

    def test_symbols(self):
        self.assertEqual(entry.yahoo_symbol("reliance"), "RELIANCE.NS")
        self.assertEqual(entry.yahoo_symbol("M&M.NS"), "M&M.NS")
        self.assertIn("M%26M.NS", entry.chart_path("M&M", "1d", "5m"))


class OpeningRange(unittest.TestCase):
    def test_range_forming_before_9_30(self):
        r = at("09:25")
        self.assertEqual(r["status"], "waiting")
        self.assertEqual(r["phase"], "forming")

    def test_the_example_triggers_at_10_00(self):
        r = at("10:00")
        self.assertEqual(r["status"], "triggered")
        self.assertEqual(r["opening_range"]["high"], 1192.0)
        self.assertEqual(r["opening_range"]["low"], 1175.3)
        self.assertEqual(r["trigger"]["time"], "10:00 AM")
        self.assertEqual(r["trigger"]["bar_start"], "09:55")
        self.assertEqual(r["trigger"]["bar_index"], 8)
        self.assertEqual(r["trigger"]["price"], 1193.6)

    def test_waiting_before_the_trigger_bar_closes(self):
        r = at("09:58")
        self.assertEqual(r["status"], "waiting")
        self.assertIn("1192.00", r["reason"])

    def test_level_setup(self):
        r = at("11:00", setup="level", level=1195.0)
        self.assertEqual(r["status"], "triggered")
        self.assertGreater(r["trigger"]["price"], 1195.0)

    def test_holiday_is_no_data(self):
        r = entry.evaluate(chart(), entry.parse_now("2026-10-20 10:00"))
        self.assertEqual(r["status"], "no-data")
        self.assertIn("Dussehra", r["reason"])

    def test_expired_after_the_cutoff(self):
        r = at("15:00", setup="level", level=5000.0)
        self.assertEqual(r["status"], "expired")
        self.assertIn("14:30", r["reason"])


class Command(unittest.TestCase):
    def test_check_writes_entry_json(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "entry.json")
            code, text, _ = run(["check", "RELIANCE", "--offline", DAY, "--now", "2026-10-26 10:00",
                                 "--write", out])
            self.assertEqual(code, 0)
            self.assertIn("TRIGGERED 10:00 AM at ₹1193.60", text)
            self.assertIn("IST", text)
            doc = read(out)
            self.assertEqual(doc["symbol"], "RELIANCE")
            self.assertEqual(doc["opening_range"], {"high": 1192.0, "low": 1175.3, "minutes": 15})

    def test_watch_replays_to_the_trigger(self):
        with tempfile.TemporaryDirectory() as d:
            code, text, _ = run(["watch", "RELIANCE", "--offline", DAY, "--now", "2026-10-26 09:15",
                                 "--out", os.path.join(d, "e.json")])
        self.assertEqual(code, 0)
        self.assertIn("opening range set: high ₹1192.00, low ₹1175.30", text)
        self.assertIn("TRIGGERED", text)

    def test_short_side_refused(self):
        code, _, err = run(["check", "RELIANCE", "--side", "short", "--offline", DAY])
        self.assertEqual(code, 1)
        self.assertIn("longs only", err)


if __name__ == "__main__":
    unittest.main()
