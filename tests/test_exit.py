import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from decimal import Decimal

from _load import load

ex = load("trader-exit", "exit")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = ex.main(argv)
    return code, out.getvalue(), err.getvalue()


EXAMPLE = ["plan", "--symbol", "RELIANCE", "--entry", "1193.60", "--or-high", "1192.00", "--or-low", "1175.30",
           "--date", "2026-10-26", "--time", "10:00 AM", "--now", "2026-10-26 10:00", "--instruments", ""]


class Ticks(unittest.TestCase):
    def test_nse_price_bands(self):
        for price, tick in ((120, "0.01"), (249.99, "0.01"), (250, "0.05"), (999, "0.05"), (1193.6, "0.10"),
                            (4999, "0.10"), (5000, "0.50"), (12000, "1.00"), (25000, "5.00")):
            self.assertEqual(ex.band_tick(price), Decimal(tick), price)

    def test_stop_rounds_down_to_the_tick(self):
        self.assertEqual(ex.floor_tick(Decimal("1183.65"), Decimal("0.10")), Decimal("1183.60"))
        self.assertEqual(ex.floor_tick(Decimal("298.17"), Decimal("0.05")), Decimal("298.15"))
        self.assertEqual(ex.to_tick(Decimal("1203.55"), Decimal("0.10")), Decimal("1203.60"))

    def test_instrument_list_wins_over_the_table(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "i.json")
            with open(p, "w") as fh:
                json.dump({"instruments": {"RELIANCE": {"tick": 0.05}}}, fh)
            self.assertEqual(ex.tick_for("RELIANCE", 1193.6, None, p), (Decimal("0.05"), "the instrument list"))
        self.assertEqual(ex.tick_for("RELIANCE", 1193.6, None, "")[0], Decimal("0.10"))
        self.assertEqual(ex.tick_for("RELIANCE", 1193.6, 0.05, "")[1], "--tick")


class Plan(unittest.TestCase):
    def test_the_example(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "plan.json")
            code, text, _ = run(EXAMPLE + ["--target", "1R", "--write", out])
            self.assertEqual(code, 0)
            p = read(out)
        self.assertEqual((p["entry"], p["stop"], p["target"]), (1193.6, 1183.6, 1203.6))
        self.assertEqual(p["risk_per_share"], 10.0)
        self.assertEqual(p["flat_by"], "15:05")
        self.assertEqual(p["tick"], 0.1)
        self.assertIn("rounded down to the ₹0.10 tick", text)
        self.assertIn("Flat by       15:05 IST", text)

    def test_default_target_is_2r(self):
        code, text, _ = run(EXAMPLE + ["--json"])
        self.assertEqual(json.loads(text)["target"], 1213.6)

    def test_refuses_a_stop_above_the_entry(self):
        code, _, err = run(EXAMPLE + ["--stop", "price:1200"])
        self.assertEqual(code, 1)
        self.assertIn("at or above the entry", err)

    def test_refuses_an_entry_after_flat_by(self):
        argv = list(EXAMPLE)
        argv[argv.index("10:00 AM")] = "3:10 PM"
        code, _, err = run(argv)
        self.assertEqual(code, 1)
        self.assertIn("flat-by", err)


if __name__ == "__main__":
    unittest.main()
