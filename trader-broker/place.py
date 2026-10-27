#!/usr/bin/env python3
"""Sends ONE approved order to Upstox for trader-broker. Standard library only.

This is the only file in the pack that talks to a broker. It sends an order
only when all of these hold, and checks each one itself:

  1. trader-risk passed THIS exact order today (trader/state/risk.json, by fingerprint)
  2. your explicit yes for THIS order is recorded today (ticket.py approve)
  3. the order has not been placed or tried already (it never retries; a
     failed order needs a new check and a new yes)
  4. paper or live matches your config ("paper" in trader/config.json):
       paper  goes to the Upstox sandbox (no money), with UPSTOX_SANDBOX_ACCESS_TOKEN
       live   needs --live AND "paper": false AND a person at the keyboard: it
              asks you to type the order back ("BUY 43 RELIANCE") and refuses
              when nobody can type (Claude's tools cannot). Live orders are
              always sent by you, never by Claude.

    python3 place.py --index 1                    # paper: the Upstox sandbox
    python3 place.py --index 1 --dry-run          # print the request, send nothing
    python3 place.py --index 1 --live             # real money: run it yourself
    python3 place.py cancel-gtt --id GTT-C26... --live   # cancel a GTT's open legs

Tokens come from the environment only, never the chat: UPSTOX_SANDBOX_ACCESS_TOKEN
(the sandbox app in Upstox's developer console; it lasts 30 days) and
UPSTOX_ACCESS_TOKEN (live; Upstox makes you renew it every day). Since April
2026 Upstox accepts API orders only from a static IP registered on your API
app: from a home connection without one, place live orders in the Upstox app
instead (ticket.py show prints the steps).

Every result (placed with Upstox's order id, or failed with Upstox's message)
is appended to trader/state/broker.json.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ticket  # noqa: E402  (ticket.py sits next to this file)

GTT_CANCEL_URL = "https://api.upstox.com/v3/order/gtt/cancel"
TIMEOUT = 20


class PlaceError(Exception):
    pass


def _token(paper):
    name = "UPSTOX_SANDBOX_ACCESS_TOKEN" if paper else "UPSTOX_ACCESS_TOKEN"
    tok = os.environ.get(name, "").strip()
    if not tok:
        raise PlaceError(
            "%s is not set. Make the token in Upstox's developer console (%s) and export it in your own "
            "terminal or shell profile. Never paste it into the chat." % (
                name, "Apps > Sandbox > Generate" if paper else "your API app, the daily login"))
    return tok


def send(method, url, body, token, opener=None):
    """(HTTP status, parsed JSON or text). Never retries."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + token, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=TIMEOUT) as r:
            text = r.read().decode("utf-8", "replace")
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
        try:
            text = e.read().decode("utf-8", "replace")
        finally:
            e.close()
    except (urllib.error.URLError, OSError) as e:
        raise PlaceError("could not reach Upstox: %s. Nothing is known to be placed: check your Upstox "
                         "order book before trying anything again" % getattr(e, "reason", e))
    try:
        return code, json.loads(text)
    except ValueError:
        return code, text


def order_ids(doc):
    data = (doc or {}).get("data") if isinstance(doc, dict) else None
    data = data or {}
    ids = []
    for k in ("gtt_order_ids", "order_ids"):
        ids.extend(str(x) for x in (data.get(k) or []))
    for k in ("gtt_order_id", "order_id"):
        if data.get(k):
            ids.append(str(data[k]))
    return ids


def upstox_error(doc):
    if isinstance(doc, dict):
        errs = doc.get("errors") or []
        if errs and isinstance(errs[0], dict):
            e = errs[0]
            return "%s%s" % (e.get("message") or e.get("errorCode") or "error",
                             (" (%s)" % e["errorCode"]) if e.get("errorCode") and e.get("message") else "")
        if doc.get("message"):
            return str(doc["message"])
    return str(doc)[:300]


def hint(msg):
    m = msg.lower()
    if "ip" in m and ("static" in m or "whitelist" in m or "not allowed" in m or "registered" in m):
        return (" Upstox takes API orders only from the static IP registered on your API app. Place it in "
                "the Upstox app instead, or from that machine.")
    if "token" in m or "unauthor" in m or "401" in m:
        return " The access token is missing, wrong or expired (live tokens last one day)."
    return ""


def confirm_live(order, ask=input, is_tty=None):
    """The person types the order back. Refuses when there is no terminal to type into."""
    tty = sys.stdin.isatty() if is_tty is None else is_tty
    if not tty:
        raise PlaceError("a LIVE order needs you at the keyboard: run this in your own terminal. "
                         "Nothing was sent.")
    want = "%s %s %s" % (str(order.get("side", "")).upper(), ticket._str_num(order.get("qty")),
                         ticket.nse_symbol(order.get("symbol", "")))
    print("LIVE ORDER, REAL MONEY: %s" % ticket.plain(order))
    got = ask('Type "%s" to send it, anything else cancels: ' % want)
    if " ".join(str(got).upper().split()) != want:
        raise PlaceError("you typed %r, not %r. Nothing was sent." % (got, want))


def record(state_path, state, now, today, idx, fp, rec, status, extra):
    new = {"at": ticket.ist_iso(now), "date": today, "index": idx, "fingerprint": fp, "symbol": rec["symbol"],
           "side": rec["side"], "plain": rec["plain"], "status": status}
    for k in ("qty", "kind", "max_loss", "stop", "paper"):
        if rec.get(k) is not None:
            new[k] = rec[k]
    new.update(extra)
    state.setdefault("orders", []).append(new)
    ticket.write_json(state_path, state)


def cmd_place(a, opener=None, ask=input, is_tty=None):
    orders, cfg, risk, state, today, now = ticket._load(a)
    order = ticket._pick(orders, a.index)
    fp = ticket.fingerprint(order)
    rv, why = ticket.risk_verdict(risk, fp, today)
    if rv is None:
        raise PlaceError("not sent: %s" % why)
    if rv.get("verdict") != "PASS":
        raise PlaceError("not sent: trader-risk blocked this order: %s" % "; ".join(rv.get("reasons", [])))
    rec = ticket.latest(state, fp, today)
    if not rec:
        raise PlaceError("not sent: no yes is recorded today for order %d (ticket.py approve --index %d --reply "
                         "\"<the user's reply>\")" % (a.index, a.index))
    if rec.get("status") != "approved":
        raise PlaceError("not sent: order %d is already %s today (%s). A new try needs a new check and a new "
                         "yes." % (a.index, rec.get("status"), rec.get("at")))
    paper_cfg = bool(cfg.get("paper", True))
    if a.live and paper_cfg:
        raise PlaceError("not sent: --live, but trader/config.json says \"paper\": true. Going live is your "
                         "decision: set \"paper\": false yourself first.")
    if not a.live and not paper_cfg:
        raise PlaceError("not sent: trader/config.json says \"paper\": false (live). Live orders are sent by you: "
                         "run place.py --index %d --live in your own terminal, or use the Upstox app." % a.index)
    if not order.get("instrument_token"):
        raise PlaceError("not sent: the order has no instrument_token")
    paper = not a.live
    req = ticket.upstox_request(order, paper)
    if a.dry_run:
        print("DRY RUN, nothing sent. %s %s (%s):" % (req["method"], req["url"], req["note"]))
        print(json.dumps(req["body"], indent=2))
        return 0
    if not paper:
        confirm_live(order, ask, is_tty)
    token = _token(paper)
    code, doc = send(req["method"], req["url"], req["body"], token, opener)
    ok = 200 <= code < 300 and isinstance(doc, dict) and doc.get("status") == "success"
    if ok:
        ids = order_ids(doc)
        record(a.state, state, now, today, a.index, fp, rec, "placed",
               {"broker_order_id": ",".join(ids) or None, "paper": paper, "url": req["url"]})
        print("PLACED on %s: %s. Upstox order id %s." % ("the Upstox sandbox (paper)" if paper else "Upstox, LIVE",
                                                          ticket.plain(order), ", ".join(ids) or "(none returned)"))
        if paper and ticket.is_bracket(order):
            print("Paper: the sandbox took the entry leg only. Watch the stop and the target with trader-alerts "
                  "(alerts.py add --from-plan).")
        print("When it fills, record it: ticket.py fill --symbol %s --side %s --qty Q --price P"
              % (rec["symbol"], rec["side"]))
        return 0
    msg = upstox_error(doc)
    record(a.state, state, now, today, a.index, fp, rec, "failed",
           {"note": "HTTP %d: %s" % (code, msg), "paper": paper, "url": req["url"]})
    print("FAILED (HTTP %d): %s.%s Recorded as failed; it is not retried." % (code, msg, hint(msg)))
    return 1


def cmd_cancel_gtt(a, opener=None, ask=input, is_tty=None):
    gid = (a.id or "").strip()
    if not gid.upper().startswith("GTT-"):
        raise PlaceError("--id wants a GTT order id like GTT-C26..., from the order's result in "
                         "trader/state/broker.json or Upstox's GTT list")
    if not a.live:
        raise PlaceError("GTT orders do not exist in the sandbox: cancel-gtt is for a live GTT (--live), or "
                         "cancel it in the Upstox app (Orders > GTT)")
    tty = sys.stdin.isatty() if is_tty is None else is_tty
    if not tty:
        raise PlaceError("cancelling a live GTT needs you at the keyboard: run this in your own terminal")
    got = ask('Type "CANCEL %s" to cancel it: ' % gid)
    if " ".join(str(got).upper().split()) != "CANCEL " + gid.upper():
        raise PlaceError("you typed %r. Nothing was sent." % got)
    code, doc = send("DELETE", GTT_CANCEL_URL, {"gtt_order_id": gid}, _token(False), opener)
    if 200 <= code < 300 and isinstance(doc, dict) and doc.get("status") == "success":
        print("Cancelled %s." % gid)
        return 0
    msg = upstox_error(doc)
    print("FAILED (HTTP %d): %s.%s Check Orders > GTT in the Upstox app." % (code, msg, hint(msg)))
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Send ONE approved order to Upstox (trader-broker).")
    sub = ap.add_subparsers(dest="cmd")
    ap.add_argument("--index", type=int, help="the order number from ticket.py show")
    ap.add_argument("--live", action="store_true", help="real money (you run it; it asks you to type the order)")
    ap.add_argument("--dry-run", action="store_true", help="print the request, send nothing")
    ap.add_argument("--orders", default="trader/orders.json")
    ap.add_argument("--config", default="trader/config.json")
    ap.add_argument("--risk", default="trader/state/risk.json")
    ap.add_argument("--state", default="trader/state/broker.json")
    ap.add_argument("--now", help="pretend it is this India time (IST), e.g. \"2026-10-26 10:00\"")
    ap.add_argument("--today", help="YYYY-MM-DD (default: today in India)")
    p = sub.add_parser("cancel-gtt", help="cancel a live GTT's open legs")
    p.add_argument("--id", required=True)
    p.add_argument("--live", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "cancel-gtt":
            return cmd_cancel_gtt(a)
        if a.index is None:
            ap.print_help()
            return 1
        return cmd_place(a)
    except (PlaceError, ticket.TicketError) as e:
        print("place.py: %s" % e, file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nplace.py: stopped. Nothing was sent.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
