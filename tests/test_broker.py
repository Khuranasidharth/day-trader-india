import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout, redirect_stderr

from _load import load, ROOT

ticket = load("trader-broker", "ticket")
place = load("trader-broker", "place")
check = load("trader-risk", "check")

NOW = "2026-10-26 10:01"
ORDER = {"symbol": "RELIANCE", "instrument_token": "NSE_EQ|INE002A01018", "side": "buy", "qty": 43, "product": "I",
         "order_type": "LIMIT", "price": 1193.6, "validity": "DAY", "order_class": "bracket",
         "stop_loss": 1183.6, "target": 1203.6, "why": "opening-range breakout on RELIANCE",
         "plan": {"entry": 1193.6, "stop": 1183.6, "target": 1203.6, "tick": 0.1, "max_loss": 495.17}}
PLAIN = ("BUY 43 RELIANCE, limit 1193.60, intraday, good for today / stop-loss 1183.60 / target 1203.60 / "
         "max loss about ₹495.17 if the stop fills at 1183.60, charges included (it can fill worse in a fast "
         "market)")


def run(main, argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class Yes(unittest.TestCase):
    def yes(self, reply, order=ORDER, batch=("RELIANCE", "TCS", "M&M")):
        return ticket.parse_yes(reply, order, batch)[0]

    def test_plain_yes_counts(self):
        for r in ("yes", "Yes.", "y", "yes place it", "yes RELIANCE", "yes 43", "yes 43 RELIANCE"):
            self.assertTrue(self.yes(r), r)

    def test_anything_else_does_not(self):
        for r in ("", "sure", "ok", "haan", "go", "do it", "yes to all", "yes both", "yes TCS", "yes M&M",
                  "yes 50", "yes but 40", "yes?", "no", "yes, wait"):
            self.assertFalse(self.yes(r), r)

    def test_plain_words(self):
        self.assertEqual(ticket.plain(ORDER), PLAIN)


class Requests(unittest.TestCase):
    def test_live_bracket_is_a_three_leg_gtt(self):
        req = ticket.upstox_request(ORDER, paper=False)
        self.assertEqual(req["url"], "https://api.upstox.com/v3/order/gtt/place")
        b = req["body"]
        self.assertEqual((b["type"], b["quantity"], b["product"], b["transaction_type"]), ("MULTIPLE", 43, "I", "BUY"))
        self.assertEqual([(r["strategy"], r["trigger_type"], r["trigger_price"]) for r in b["rules"]],
                         [("ENTRY", "IMMEDIATE", 1193.6), ("TARGET", "IMMEDIATE", 1203.6),
                          ("STOPLOSS", "IMMEDIATE", 1183.6)])
        self.assertNotIn("why", json.dumps(b))

    def test_paper_bracket_is_the_entry_leg_on_the_sandbox(self):
        req = ticket.upstox_request(ORDER, paper=True)
        self.assertEqual(req["url"], "https://api-sandbox.upstox.com/v3/order/place")
        self.assertEqual((req["body"]["order_type"], req["body"]["price"], req["body"]["is_amo"]), ("LIMIT", 1193.6, False))

    def test_market_sell_carries_price_protection(self):
        sell = {"symbol": "RELIANCE", "instrument_token": "NSE_EQ|INE002A01018", "side": "sell", "qty": 43,
                "product": "I", "order_type": "MARKET", "price": 0, "validity": "DAY"}
        req = ticket.upstox_request(sell, paper=False)
        self.assertEqual(req["url"], "https://api-hft.upstox.com/v3/order/place")
        self.assertEqual(req["body"]["market_protection"], -1)


class Fake(object):
    """Stands in for urllib's urlopen: records the request, answers with a canned reply."""

    def __init__(self, code=200, body=None):
        self.code, self.body, self.calls = code, body or {}, []

    def __call__(self, req, timeout=None):
        self.calls.append(req)
        data = json.dumps(self.body).encode()
        if self.code >= 400:
            raise urllib.error.HTTPError(req.full_url, self.code, "error", {}, io.BytesIO(data))
        test = self

        class Resp(object):
            status = test.code

            def read(self):
                return data

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return Resp()


class Flow(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        p = lambda n: os.path.join(self.d, n)   # noqa: E731
        self.paths = {"orders": p("orders.json"), "config": p("config.json"), "risk": p("risk.json"),
                      "state": p("broker.json")}
        with open(os.path.join(ROOT, "trader-budget", "config.example.json")) as fh:
            self.cfg = json.load(fh)
        self.write_cfg()
        with open(self.paths["orders"], "w") as fh:
            json.dump({"orders": [ORDER]}, fh)
        res = check.check([ORDER], self.cfg, None, {}, None, None, check.parse_now(NOW), None,
                          {"RELIANCE": {"instrument_key": "NSE_EQ|INE002A01018", "tick": 0.1}})
        with open(self.paths["risk"], "w") as fh:
            json.dump(res, fh)
        os.environ.pop("UPSTOX_SANDBOX_ACCESS_TOKEN", None)
        os.environ.pop("UPSTOX_ACCESS_TOKEN", None)

    def tearDown(self):
        shutil.rmtree(self.d)
        os.environ.pop("UPSTOX_SANDBOX_ACCESS_TOKEN", None)
        os.environ.pop("UPSTOX_ACCESS_TOKEN", None)

    def write_cfg(self):
        with open(self.paths["config"], "w") as fh:
            json.dump(self.cfg, fh)

    def flags(self):
        out = []
        for k, v in self.paths.items():
            out += ["--" + k, v]
        return out + ["--now", NOW]

    def args(self, **kw):
        ns = dict(index=1, live=False, dry_run=False, now=NOW, today=None, **self.paths)
        ns.update(kw)
        return type("A", (), ns)()

    def approve(self, reply="yes"):
        return run(ticket.main, ["approve", "--index", "1", "--reply", reply] + self.flags())

    def test_show_is_ready_and_prints_the_request(self):
        code, text, _ = run(ticket.main, ["show"] + self.flags())
        self.assertEqual(code, 0)
        self.assertIn("ORDER 1 of 1, PAPER (Upstox sandbox), Upstox", text)
        self.assertIn("READY: trader-risk PASS", text)
        self.assertIn("https://api-sandbox.upstox.com/v3/order/place", text)

    def test_no_yes_no_order(self):
        fake = Fake(200, {"status": "success", "data": {"order_ids": ["1"]}})
        with self.assertRaises(place.PlaceError) as e:
            place.cmd_place(self.args(), opener=fake)
        self.assertIn("no yes is recorded", str(e.exception))
        self.assertEqual(fake.calls, [])

    def test_paper_places_once_on_the_sandbox(self):
        self.assertEqual(self.approve()[0], 0)
        os.environ["UPSTOX_SANDBOX_ACCESS_TOKEN"] = "sandbox-token"
        fake = Fake(200, {"status": "success", "data": {"order_ids": ["2610260001"]}})
        with redirect_stdout(io.StringIO()) as out:
            code = place.cmd_place(self.args(), opener=fake)
        self.assertEqual(code, 0)
        req = fake.calls[0]
        self.assertEqual(req.full_url, "https://api-sandbox.upstox.com/v3/order/place")
        self.assertEqual(req.get_header("Authorization"), "Bearer sandbox-token")
        self.assertIn("PLACED on the Upstox sandbox (paper)", out.getvalue())
        with open(self.paths["state"]) as fh:
            last = json.load(fh)["orders"][-1]
        self.assertEqual((last["status"], last["broker_order_id"]), ("placed", "2610260001"))
        with self.assertRaises(place.PlaceError) as e:       # never twice on one yes
            place.cmd_place(self.args(), opener=fake)
        self.assertIn("already placed", str(e.exception))

    def test_a_failure_is_recorded_and_not_retried(self):
        self.approve()
        os.environ["UPSTOX_SANDBOX_ACCESS_TOKEN"] = "t"
        fake = Fake(400, {"status": "error", "errors": [{"errorCode": "UDAPI1", "message": "Invalid price"}]})
        with redirect_stdout(io.StringIO()) as out:
            code = place.cmd_place(self.args(), opener=fake)
        self.assertEqual(code, 1)
        self.assertIn("FAILED (HTTP 400): Invalid price", out.getvalue())
        with self.assertRaises(place.PlaceError):
            place.cmd_place(self.args(), opener=fake)
        self.assertEqual(len(fake.calls), 1)

    def test_missing_token_says_where_to_get_one(self):
        self.approve()
        with self.assertRaises(place.PlaceError) as e:
            place.cmd_place(self.args(), opener=Fake())
        self.assertIn("UPSTOX_SANDBOX_ACCESS_TOKEN is not set", str(e.exception))
        self.assertIn("Never paste it into the chat", str(e.exception))

    def test_live_needs_the_config_and_a_person_at_the_keyboard(self):
        self.approve()
        with self.assertRaises(place.PlaceError) as e:
            place.cmd_place(self.args(live=True), opener=Fake())
        self.assertIn("\"paper\": true", str(e.exception))
        self.cfg["paper"] = False
        self.write_cfg()
        with self.assertRaises(place.PlaceError) as e:       # live config, but no --live: not from here
            place.cmd_place(self.args(), opener=Fake())
        self.assertIn("sent by you", str(e.exception))
        os.environ["UPSTOX_ACCESS_TOKEN"] = "live-token"
        fake = Fake(200, {"status": "success", "data": {"gtt_order_ids": ["GTT-C26102600001"]}})
        with self.assertRaises(place.PlaceError) as e:       # no terminal: refused
            place.cmd_place(self.args(live=True), opener=fake, is_tty=False)
        self.assertIn("at the keyboard", str(e.exception))
        with self.assertRaises(place.PlaceError):            # typed something else
            with redirect_stdout(io.StringIO()):
                place.cmd_place(self.args(live=True), opener=fake, is_tty=True, ask=lambda _: "yes")
        self.assertEqual(fake.calls, [])
        with redirect_stdout(io.StringIO()):
            code = place.cmd_place(self.args(live=True), opener=fake, is_tty=True, ask=lambda _: "buy 43 reliance")
        self.assertEqual(code, 0)
        self.assertEqual(fake.calls[0].full_url, "https://api.upstox.com/v3/order/gtt/place")
        self.assertEqual(json.loads(fake.calls[0].data)["type"], "MULTIPLE")

    def test_dry_run_sends_nothing(self):
        self.approve()
        fake = Fake()
        with redirect_stdout(io.StringIO()) as out:
            code = place.cmd_place(self.args(dry_run=True), opener=fake)
        self.assertEqual(code, 0)
        self.assertEqual(fake.calls, [])
        self.assertIn("DRY RUN", out.getvalue())

    def test_flatten_ticket(self):
        inst = os.path.join(self.d, "inst.json")
        with open(inst, "w") as fh:
            json.dump({"instruments": {"RELIANCE": {"instrument_key": "NSE_EQ|INE002A01018"}}}, fh)
        code, text, _ = run(ticket.main, ["flatten", "--symbol", "RELIANCE", "--qty", "43", "--orders",
                                          self.paths["orders"], "--config", self.paths["config"],
                                          "--instruments", inst, "--plan", os.path.join(self.d, "plan.json"),
                                          "--now", "2026-10-26 15:05"])
        self.assertEqual(code, 0)
        self.assertIn("Cancel the bracket's GTT first", text)
        with open(self.paths["orders"]) as fh:
            o = json.load(fh)["orders"][0]
        self.assertEqual((o["side"], o["qty"], o["product"], o["order_type"]), ("sell", 43, "I", "MARKET"))


if __name__ == "__main__":
    unittest.main()
