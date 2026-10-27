#!/usr/bin/env python3
"""Bulk and block deals tracker for trader-deals. NSE, rupees. Standard library only.

NSE publishes every bulk deal and block deal of the day in two files after
the close. This tool reads them, says who bought and sold what, nets each
client's buys against its sells, flags deals in the stocks you watch or
hold, and remembers what it has shown so each deal alerts once.

    python3 deals.py today                         # the latest day's deals, biggest first
    python3 deals.py today --min-crore 10          # only deals of 10 crore or more
    python3 deals.py today --symbol RELIANCE       # one stock
    python3 deals.py today --client "morgan stanley"
    python3 deals.py new                           # only deals not shown before (exit 1 = none)
    python3 deals.py history --symbol APOLLO       # every deal kept in the state file (90 days)

What the two files are:
  bulk deals   a client's trades in one stock on one day that add up to more
               than 0.5 % of the company's listed shares, through the normal
               market. https://archives.nseindia.com/content/equities/bulk.csv
  block deals  large trades done in the exchange's separate block-deal
               windows. https://archives.nseindia.com/content/equities/block.csv
Both files hold the latest trading day only, so the history here is what this
tool has seen; run it each evening (a scheduled task) to keep it complete.

Reading them honestly:
  - It is public and after the fact: the trade is done before anyone reads it.
  - Many bulk deals are high-frequency and market-making firms that buy and
    sell the same stock the same day. The net (buys minus sells) per client
    is what changed hands; a client with both sides is marked "both sides".
  - A name is not a reason. A fund buying is a reason to look at a chart,
    not a setup.

State: trader/state/deals.json. Offline: --offline DIR reads bulk.csv and
block.csv from DIR.
"""

import argparse
import csv
import datetime as _dt
import hashlib
import io
import json
import os
import sys
import urllib.error
import urllib.request

URLS = {"bulk": "https://archives.nseindia.com/content/equities/bulk.csv",
        "block": "https://archives.nseindia.com/content/equities/block.csv"}
UA = "Mozilla/5.0 (compatible; day-trader-skill/2.0; +https://github.com/Jakeschincariol/day-trader-skill)"
CRORE = 1e7
KEEP_DAYS = 90


class DealsError(Exception):
    pass


def nse_symbol(sym):
    s = str(sym).strip().upper()
    return s[:-3] if s.endswith(".NS") else s


def load_json(path):
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


# ---------------------------------------------------------------- reading

def fetch(kind, offline=None):
    if offline:
        path = os.path.join(offline, "%s.csv" % kind)
        if not os.path.exists(path):
            raise DealsError("offline: no %s" % path)
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    req = urllib.request.Request(URLS[kind], headers={"User-Agent": UA, "Accept": "text/csv,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise DealsError("archives.nseindia.com answered HTTP %d for %s.csv" % (e.code, kind))
    except (urllib.error.URLError, OSError) as e:
        raise DealsError("could not reach archives.nseindia.com: %s" % getattr(e, "reason", e))


def _num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except ValueError:
        return None


def parse(text, kind):
    """NSE's bulk.csv / block.csv -> deals. "NO RECORDS" is an empty day, not an error."""
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    if not rows or not rows[0] or "symbol" not in [h.strip().lower() for h in rows[0]]:
        raise DealsError("%s.csv is not the layout this tool knows" % kind)
    hdr = [h.strip().lower() for h in rows[0]]

    def col(*names):
        for n in names:
            for i, h in enumerate(hdr):
                if h.startswith(n):
                    return i
        raise DealsError("%s.csv has no %s column" % (kind, names[0]))
    ci = {"date": col("date"), "symbol": col("symbol"), "name": col("security name"),
          "client": col("client name"), "side": col("buy/sell", "buy / sell"),
          "qty": col("quantity"), "price": col("trade price", "price")}
    out = []
    for r in rows[1:]:
        if not r or not any(x.strip() for x in r) or r[0].strip().upper().startswith("NO RECORDS"):
            continue
        if len(r) <= max(ci.values()):
            continue
        try:
            day = _dt.datetime.strptime(r[ci["date"]].strip().title(), "%d-%b-%Y").date().isoformat()
        except ValueError:
            continue
        qty, price = _num(r[ci["qty"]]), _num(r[ci["price"]])
        if qty is None or price is None:
            continue
        d = {"kind": kind, "date": day, "symbol": nse_symbol(r[ci["symbol"]]),
             "name": " ".join(r[ci["name"]].split()), "client": " ".join(r[ci["client"]].split()),
             "side": r[ci["side"]].strip().lower(), "qty": int(qty), "price": round(price, 2),
             "value": round(qty * price, 2)}
        d["id"] = hashlib.sha1(("|".join(str(d[k]) for k in ("kind", "date", "symbol", "client", "side",
                                                             "qty", "price"))).encode()).hexdigest()[:16]
        out.append(d)
    return out


def watched(portfolio="trader/portfolio.json", watchlist="trader/watchlist.json", plan="trader/plan.json"):
    out = set()
    for h in (load_json(watchlist) or {}).get("hits", []):
        if h.get("symbol"):
            out.add(nse_symbol(h["symbol"]))
    pl = load_json(plan) or {}
    if pl.get("symbol"):
        out.add(nse_symbol(pl["symbol"]))
    for p in (load_json(portfolio) or {}).get("positions", []):
        if p.get("ticker") or p.get("symbol"):
            out.add(nse_symbol(p.get("ticker") or p.get("symbol")))
    return out


# ---------------------------------------------------------------- the summary

def select(deals, symbol=None, client=None, min_crore=0.0):
    out = []
    for d in deals:
        if symbol and d["symbol"] != nse_symbol(symbol):
            continue
        if client and client.lower() not in d["client"].lower():
            continue
        if d["value"] < min_crore * CRORE - 1e-6:
            continue
        out.append(d)
    return out


def by_stock(deals):
    """{symbol: {"name", "deals", "clients": {client: {"buy", "sell", "net", "value_net"}}}}."""
    out = {}
    for d in deals:
        s = out.setdefault(d["symbol"], {"name": d["name"], "deals": [], "clients": {}, "value": 0.0})
        s["deals"].append(d)
        s["value"] += d["value"]
        c = s["clients"].setdefault(d["client"], {"buy": 0, "sell": 0, "buy_value": 0.0, "sell_value": 0.0})
        c[d["side"]] = c.get(d["side"], 0) + d["qty"]
        c[d["side"] + "_value"] = c.get(d["side"] + "_value", 0.0) + d["value"]
    for s in out.values():
        for c in s["clients"].values():
            c["net"] = c["buy"] - c["sell"]
            c["both_sides"] = c["buy"] > 0 and c["sell"] > 0
    return out


def cr(v):
    return "₹%.2f cr" % (v / CRORE)


def indian(n):
    """1657804 -> '16,57,804' (Indian grouping)."""
    s = str(abs(int(n)))
    if len(s) > 3:
        head, tail, parts = s[:-3], s[-3:], []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join(([head] if head else []) + parts + [tail])
    return ("-" if n < 0 else "") + s


def render(deals, watch, title):
    lines = [title]
    if not deals:
        lines.append("No deals.")
        return lines
    stocks = by_stock(deals)
    for sym in sorted(stocks, key=lambda k: -stocks[k]["value"]):
        s = stocks[sym]
        flag = "  <- you watch or hold it" if sym in watch else ""
        kinds = sorted({d["kind"] for d in s["deals"]})
        lines.append("")
        lines.append("%s (%s): %d %s deal%s, %s traded%s" % (
            sym, s["name"], len(s["deals"]), "/".join(kinds), "" if len(s["deals"]) == 1 else "s",
            cr(s["value"]), flag))
        for name in sorted(s["clients"], key=lambda n: -(s["clients"][n]["buy_value"] + s["clients"][n]["sell_value"])):
            c = s["clients"][name]
            parts = []
            if c["buy"]:
                parts.append("bought %s (%s)" % (indian(c["buy"]), cr(c["buy_value"])))
            if c["sell"]:
                parts.append("sold %s (%s)" % (indian(c["sell"]), cr(c["sell_value"])))
            net = (", net %s%s shares, both sides" % ("+" if c["net"] >= 0 else "", indian(c["net"]))) \
                if c["both_sides"] else ""
            lines.append("  %-48s %s%s" % (name[:48], ", ".join(parts), net))
    both = sum(1 for s in stocks.values() for c in s["clients"].values() if c["both_sides"])
    if both:
        lines.append("")
        lines.append("%d client(s) bought and sold the same stock today: that is trading, not a position. "
                     "The net is what changed hands." % both)
    return lines


# ---------------------------------------------------------------- state

def remember(state, deals, now):
    seen = state.setdefault("deals", {})
    for d in deals:
        if d["id"] not in seen:
            seen[d["id"]] = dict(d, seen_at=now.isoformat())
    cutoff = (now.date() - _dt.timedelta(days=KEEP_DAYS)).isoformat()
    state["deals"] = {k: v for k, v in seen.items() if v.get("date", "") >= cutoff}
    state["last_check"] = now.isoformat()


def save(path, state):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1)
        fh.write("\n")
    os.replace(tmp, path)


def latest(offline=None, errors=None):
    deals = []
    for kind in ("bulk", "block"):
        try:
            deals += parse(fetch(kind, offline), kind)
        except DealsError as e:
            if errors is None:
                raise
            errors.append(str(e))
    return deals


# ---------------------------------------------------------------- commands

def main(argv=None):
    ap = argparse.ArgumentParser(description="NSE bulk and block deals (trader-deals).")
    sub = ap.add_subparsers(dest="cmd")
    for name, help_ in (("today", "the latest day's deals"), ("new", "only deals not shown before"),
                        ("history", "deals kept in the state file")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--symbol")
        p.add_argument("--client", help="part of a client's name, any case")
        p.add_argument("--min-crore", type=float, default=0.0, help="leave out deals under this many crore")
        p.add_argument("--state", default="trader/state/deals.json")
        p.add_argument("--portfolio", default="trader/portfolio.json")
        p.add_argument("--watchlist", default="trader/watchlist.json")
        p.add_argument("--plan", default="trader/plan.json")
        p.add_argument("--offline", metavar="DIR")
        p.add_argument("--now", help="ISO time, for reproducible runs")
        p.add_argument("--json", action="store_true")
        p.add_argument("--dry-run", action="store_true", help="do not update the state file")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    now = (_dt.datetime.fromisoformat(a.now) if a.now else _dt.datetime.now(_dt.timezone.utc)).replace(tzinfo=None)
    watch = watched(a.portfolio, a.watchlist, a.plan)
    state = load_json(a.state) or {}
    errors = []
    try:
        if a.cmd == "history":
            deals = sorted(state.get("deals", {}).values(), key=lambda d: (d["date"], -d["value"]), reverse=True)
            fresh = select(deals, a.symbol, a.client, a.min_crore)
            title = "Deals kept in %s%s: %d." % (a.state, (" for " + nse_symbol(a.symbol)) if a.symbol else "",
                                                 len(fresh))
        else:
            deals = latest(a.offline, errors)
            if not deals and errors:
                raise DealsError("; ".join(errors))
            seen = state.get("deals", {})
            picked = select(deals, a.symbol, a.client, a.min_crore)
            fresh = [d for d in picked if a.cmd == "today" or d["id"] not in seen]
            day = max((d["date"] for d in deals), default=None)
            title = "NSE %s deals%s%s: %d (%s)." % (
                "new" if a.cmd == "new" else "bulk and block", (" on " + day) if day else "",
                (" for " + nse_symbol(a.symbol)) if a.symbol else "", len(fresh),
                "%d bulk, %d block" % (sum(1 for d in fresh if d["kind"] == "bulk"),
                                       sum(1 for d in fresh if d["kind"] == "block")))
            if not a.dry_run:
                remember(state, deals, now)
                save(a.state, state)
    except DealsError as e:
        print("deals.py: %s" % e, file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps({"deals": fresh, "watched": sorted(watch & {d["symbol"] for d in fresh}),
                          "notes": errors}, indent=2))
    else:
        for line in render(fresh, watch, title):
            print(line)
        for e in errors:
            print("note: " + e)
        print("Public, after the fact: these trades are done. A deal is a reason to look at a chart, not a setup. "
              "Not financial advice.")
    return 0 if fresh else 1


if __name__ == "__main__":
    sys.exit(main())
