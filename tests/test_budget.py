import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, ROOT

size = load("trader-budget", "size")
with open(os.path.join(ROOT, "trader-budget", "config.example.json")) as fh:
    CFG = json.load(fh)
PLAN = {"symbol": "RELIANCE", "side": "buy", "date": "2026-10-26", "setup": "orb", "entry": 1193.6,
        "entry_time": "10:00 AM", "stop": 1183.6, "target": 1203.6, "tick": 0.1, "flat_by": "15:05",
        "stop_label": "opening-range midpoint", "target_label": "1R (one times the risk)"}
INST = {"instrument_key": "NSE_EQ|INE002A01018", "tick": 0.1, "cas": True}


def sized(**kw):
    args = dict(today="2026-10-26", instrument=INST)
    args.update(kw)
    return size.size_trade(dict(PLAN), CFG, **args)


class Charges(unittest.TestCase):
    def test_round_trip_charges_for_the_example(self):
        c = size.charges(43, 1193.6, 1183.6, size.CHARGES)
        self.assertEqual(c["brokerage"], 40.0)
        self.assertEqual(c["stt"], 12.72)          # 0.025% of the sell side, 50,894.80
        self.assertEqual(c["stamp"], 1.54)         # 0.003% of the buy side, 51,324.80
        self.assertEqual(c["total"], 65.17)

    def test_your_plan_overrides_the_rates(self):
        rates = dict(size.CHARGES, brokerage_per_order_inr=20, brokerage_pct=0.05)
        c = size.charges(10, 100.0, 99.0, rates)
        self.assertEqual(c["brokerage"], 0.99)    # 0.05% of 1,000 and of 990, under the flat 20

    def test_shares_for_loss_counts_the_charges(self):
        self.assertEqual(size.shares_for_loss(500, 1193.6, 1183.6, size.CHARGES, 10 ** 6), 43)


class Example(unittest.TestCase):
    def test_43_shares_bound_by_max_loss(self):
        s = sized()
        self.assertEqual(s["qty"], 43)
        self.assertEqual(s["bound_by"], "max loss")
        self.assertEqual(s["cost"], 51324.8)
        self.assertEqual(s["max_loss"], 495.17)
        self.assertEqual(s["gain_at_target"], 364.59)
        self.assertIsNone(s["refusal"])

    def test_the_order(self):
        o = size.bracket_order(sized())
        self.assertEqual(o["instrument_token"], "NSE_EQ|INE002A01018")
        self.assertEqual((o["qty"], o["product"], o["order_type"], o["price"]), (43, "I", "LIMIT", 1193.6))
        self.assertEqual((o["stop_loss"], o["target"]), (1183.6, 1203.6))
        self.assertEqual(o["order_class"], "bracket")

    def test_prices_land_on_the_tick(self):
        s = size.size_trade(dict(PLAN, stop=1183.65, target=1203.55), CFG, today="2026-10-26", instrument=INST)
        self.assertEqual((s["stop"], s["target"]), (1183.6, 1203.6))


class Refusals(unittest.TestCase):
    def test_stop_too_far_for_the_max_loss(self):
        s = size.size_trade(dict(PLAN, stop=600.0, target=1800.0), CFG, today="2026-10-26", instrument=INST)
        self.assertEqual(s["qty"], 0)
        self.assertIn("max loss per trade", s["refusal"])

    def test_no_instrument_key(self):
        s = sized(instrument={})
        self.assertIn("scan.py universe", s["refusal"])
        self.assertIsNone(size.bracket_order(s))

    def test_plan_for_another_day(self):
        with self.assertRaises(size.SizeError):
            sized(today="2026-10-27")

    def test_price_ran_past_the_limit_is_a_note_not_a_bigger_size(self):
        s = sized(price=1199.0)
        self.assertEqual(s["entry"], 1193.6)
        self.assertEqual(s["price_above"], 1199.0)


class Command(unittest.TestCase):
    def test_write_orders(self):
        with tempfile.TemporaryDirectory() as d:
            plan, inst, out = (os.path.join(d, n) for n in ("plan.json", "inst.json", "orders.json"))
            with open(plan, "w") as fh:
                json.dump(PLAN, fh)
            with open(inst, "w") as fh:
                json.dump({"instruments": {"RELIANCE": INST}}, fh)
            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(io.StringIO()):
                code = size.main(["--plan", plan, "--config", os.path.join(ROOT, "trader-budget", "config.example.json"),
                                  "--instruments", inst, "--portfolio", os.path.join(d, "none.json"),
                                  "--prices", "", "--now", "2026-10-26 10:00", "--write", out])
            self.assertEqual(code, 0)
            with open(out) as fh:
                doc = json.load(fh)
        self.assertTrue(doc["paper"])
        self.assertEqual(doc["orders"][0]["qty"], 43)
        text = buf.getvalue()
        self.assertIn("plus about ₹65.17 in charges = ₹495.17", text)
        self.assertIn("an Upstox GTT with three legs, product I", text)

    def test_weights_mode_is_whole_shares_delivery(self):
        rows = size.parse_weights({"RELIANCE": 60, "TCS": 40})
        r = size.size(rows, dict(CFG, max_position_pct=100), 100000, {"RELIANCE": 1201.8, "TCS": 2535.0})
        orders = size.orders_from(r, "", {"RELIANCE": INST})
        self.assertTrue(all(isinstance(o["qty"], int) and o["product"] == "D" for o in orders))
        self.assertEqual(orders[0]["instrument_token"], "NSE_EQ|INE002A01018")


if __name__ == "__main__":
    unittest.main()
