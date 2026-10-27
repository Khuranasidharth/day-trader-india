import json
import os
import unittest

from _load import load, ROOT

check = load("trader-risk", "check")
with open(os.path.join(ROOT, "trader-budget", "config.example.json")) as fh:
    CFG = json.load(fh)
INSTRUMENTS = {"RELIANCE": {"instrument_key": "NSE_EQ|INE002A01018", "tick": 0.1},
               "TCS": {"instrument_key": "NSE_EQ|INE467B01029", "tick": 0.1}}
ORDER = {"symbol": "RELIANCE", "instrument_token": "NSE_EQ|INE002A01018", "side": "buy", "qty": 43, "product": "I",
         "order_type": "LIMIT", "price": 1193.6, "validity": "DAY", "order_class": "bracket",
         "stop_loss": 1183.6, "target": 1203.6,
         "plan": {"entry": 1193.6, "stop": 1183.6, "target": 1203.6, "tick": 0.1}}


def one(order=None, now="2026-10-26 10:00", cfg=None, portfolio=None, state=None, instruments=INSTRUMENTS):
    res = check.check([order or ORDER], cfg or CFG, portfolio, {}, state, None, check.parse_now(now), None,
                      instruments)
    return res["results"][0], res


def o(**kw):
    x = dict(ORDER)
    x.update(kw)
    return x


class Pass(unittest.TestCase):
    def test_the_example_passes_with_charges_counted(self):
        r, res = one()
        self.assertEqual(r["verdict"], "PASS", r["reasons"])
        self.assertEqual(r["max_loss"], 495.17)
        self.assertEqual(r["reward_risk"], 1.0)
        self.assertTrue(any("reward:risk 0.74 net" in w for w in r["warnings"]))
        self.assertEqual(res["now_ist"], "2026-10-26 10:00")

    def test_one_more_share_is_over_the_max_loss(self):
        r, _ = one(o(qty=44))
        self.assertEqual(r["verdict"], "BLOCK")
        self.assertTrue(any(x.startswith("loss:") and "plus about" in x for x in r["reasons"]))


class Format(unittest.TestCase):
    def blocked(self, order, word):
        r, _ = one(order)
        self.assertEqual(r["verdict"], "BLOCK")
        self.assertTrue(any(word in x for x in r["reasons"]), r["reasons"])

    def test_off_tick_price(self):
        self.blocked(o(stop_loss=1183.65), "tick")

    def test_fractional_qty(self):
        self.blocked(o(qty=4.5), "whole number")

    def test_wrong_instrument_for_the_symbol(self):
        self.blocked(o(instrument_token="NSE_EQ|INE467B01029"), "different stock")

    def test_unknown_product(self):
        self.blocked(o(product="MTF"), "product")

    def test_bracket_must_be_a_limit(self):
        self.blocked(o(order_type="MARKET", price=0), "LIMIT")

    def test_fno_is_off(self):
        self.blocked(o(symbol="NIFTY26OCT25000CE", instrument_token="NSE_FO|43919"), "F&O")

    def test_not_in_the_eq_series(self):
        self.blocked(o(symbol="ABAN", instrument_token="NSE_EQ|INE421A01028"), "trade-to-trade")

    def test_no_instrument_list_is_a_warning(self):
        r, res = one(instruments=None)
        self.assertEqual(r["verdict"], "PASS")
        self.assertTrue(any("instruments.json" in w for w in res["warnings"]))


class Window(unittest.TestCase):
    def test_before_9_30(self):
        r, _ = one(now="2026-10-26 09:20")
        self.assertIn("window: no new entries before 09:30 IST (it is 09:20)", r["reasons"])

    def test_after_14_30(self):
        r, _ = one(now="2026-10-26 14:45")
        self.assertTrue(any("after 14:30" in x for x in r["reasons"]))

    def test_holiday(self):
        r, _ = one(now="2026-11-10 10:00")
        self.assertTrue(any("Diwali" in x for x in r["reasons"]))

    def test_an_exit_is_never_blocked_by_the_window(self):
        sell = {"symbol": "RELIANCE", "instrument_token": "NSE_EQ|INE002A01018", "side": "sell", "qty": 43,
                "product": "I", "order_type": "MARKET", "price": 0, "validity": "DAY"}
        pf = {"cash": 50000, "positions": [{"ticker": "RELIANCE", "shares": 43}]}
        r, _ = one(sell, now="2026-10-26 15:05", portfolio=pf)
        self.assertEqual(r["kind"], "exit")
        self.assertEqual(r["verdict"], "PASS", r["reasons"])


class Day(unittest.TestCase):
    def test_daily_loss_counts_todays_entries(self):
        state = {"orders": [{"status": "placed", "date": "2026-10-26", "symbol": "TCS", "side": "buy",
                             "kind": "entry", "max_loss": 1200}]}
        r, _ = one(state=state)
        self.assertTrue(any(x.startswith("daily loss:") for x in r["reasons"]))

    def test_short_selling_is_off(self):
        r, _ = one(o(side="sell", order_class=None, stop_loss=None, target=None))
        self.assertTrue(any(x.startswith("short:") for x in r["reasons"]))


if __name__ == "__main__":
    unittest.main()
