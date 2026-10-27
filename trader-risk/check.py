#!/usr/bin/env python3
"""Pre-trade risk check for trader-risk. NSE stocks, rupees, Upstox orders.
Standard library only, no network.

Reads the proposed orders (trader/orders.json) and checks every one against
your rules (trader/config.json), your account (trader/portfolio.json),
prices (trader/prices.json), the instrument list (trader/instruments.json)
and what was placed today (trader/state/broker.json). Each order gets PASS or
BLOCK with the reasons. Orders are checked in file order as if each PASS had
filled, so buys that are fine one by one but break a limit together are caught.

    python3 check.py                                 # the trader/ files, writes trader/state/risk.json
    python3 check.py --now "2026-10-26 10:00"        # pin the clock (India time, IST)
    python3 check.py --orders trader/orders.json --json
    python3 check.py --no-write                      # check without recording the verdicts

Entries and exits. An ENTRY opens or adds to a position (a buy, or a sell
that would go short). An EXIT only reduces what you hold. Getting out must
always be possible: an exit is checked for format, asset and short sales
only; every other rule turns into a warning for it.

What blocks an order (every order):

  format        missing symbol, side or instrument_token; qty not a whole
                number of shares; product not I (intraday) or D (delivery);
                order_type not MARKET / LIMIT / SL / SL-M, or missing its
                price or trigger; validity not DAY / IOC; a bracket that is
                not a LIMIT entry with a stop_loss and a target; a price that
                is not on the stock's tick (the exchange would reject it); an
                instrument_token that is not this symbol's in the instrument list
  asset         F&O (an NSE_FO / BSE_FO token or an option-looking symbol)
                unless "allow_options": true; anything that is not an NSE
                equity; with the instrument list, a stock that is not in the
                EQ series (BE / BZ are trade-to-trade: no intraday)
  short         selling more than you hold, unless "allow_short": true

What blocks an entry (on top):

  blocked       a symbol on your "blocked" list
  size          under min_order_inr, over max_order_inr
  position      the stock would be over max_position_pct of the account
  cash          the buy would dip into your cash buffer, or need margin
                (Upstox's intraday leverage stays off unless "allow_margin": true)
  duplicate     the same symbol and side twice in this batch, or already
                placed today (trader/state/broker.json)
  daily limit   max_orders_per_day orders placed today
  stop          no stop while "require_stop": true (the bracket's stop_loss
                or the order's plan stop); a stop on the wrong side of the entry
  loss          qty x (entry - stop) + the round trip's estimated charges over
                max_loss_per_trade_inr. The entry is the limit price for a
                limit order, else the HIGHER of the plan's entry and a fresh
                price (under 15 minutes old), so a stale plan cannot
                understate the risk
  reward:risk   (target - entry) / (entry - stop) under min_reward_risk (the
                same after charges is shown, and warned about under 1)
  daily loss    the max losses at the stops of today's entries plus this one
                over max_daily_loss_inr (win or lose, each counts in full)
  trades        max_trades_per_day entries already placed today
  window        before no_entries_before or after no_entries_after (IST),
                or the market is closed (weekend, NSE holiday, outside 9:15
                to 3:30 PM)

Exit code 0 when every order passes, 1 when any order is blocked.
The verdicts go to trader/state/risk.json with a fingerprint of each order,
so trader-broker only shows an order as ready if THIS exact order passed today.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys

DEFAULTS = {
    "budget": None, "cash_buffer_pct": 10, "max_position_pct": 75, "max_order_inr": 75000,
    "min_order_inr": 500, "max_loss_per_trade_inr": 500, "max_daily_loss_inr": 1500, "max_trades_per_day": 3,
    "max_orders_per_day": 10, "min_reward_risk": 1.0, "require_stop": True,
    "no_entries_before": "09:30", "no_entries_after": "14:30", "flat_by": "15:05",
    "paper": True, "blocked": [], "allow_options": False, "allow_margin": False, "allow_short": False,
    "charges": None,
}
CHARGES = {  # intraday equity, read in October 2026; the same table as trader-budget/size.py
    "brokerage_per_order_inr": 20.0, "brokerage_pct": None, "stt_sell_pct": 0.025, "exchange_pct": 0.00297,
    "sebi_pct": 0.0001, "stamp_buy_pct": 0.003, "gst_pct": 18.0,
}
ORDER_FIELDS = ("symbol", "instrument_token", "side", "qty", "product", "order_type", "price",
                "trigger_price", "validity", "order_class", "stop_loss", "target")
PRICE_FIELDS = ("price", "trigger_price", "stop_loss", "target")
TYPES = {"MARKET", "LIMIT", "SL", "SL-M"}
VALIDITIES = {"DAY", "IOC"}
PRODUCTS = {"I": "intraday", "D": "delivery"}
FNO = (r"^[A-Z&\-]+\d{2}[A-Z]{3}(\d+(\.\d+)?)?(CE|PE|FUT)$")
SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9&\-]{0,19}$")
TOKEN = re.compile(r"^NSE_EQ\|IN[A-Z0-9]{10}$")
HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
CENT = 0.005
FRESH_MINUTES = 15
REF_WORDS = {"plan": "the plan's entry", "price": "the latest price", "limit": "the limit price",
             "stop price": "the stop price", "stale price": "an old price"}

NSE_HOLIDAYS = {  # equity segment, NSE circular of December 2025
    "2026-01-15": "Municipal Corporation Election, Maharashtra",
    "2026-01-26": "Republic Day",
    "2026-03-03": "Holi",
    "2026-03-26": "Shri Ram Navami",
    "2026-03-31": "Shri Mahavir Jayanti",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-28": "Bakri Id",
    "2026-06-26": "Muharram",
    "2026-09-14": "Ganesh Chaturthi",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-10": "Diwali Balipratipada",
    "2026-11-24": "Prakash Gurpurb Sri Guru Nanak Dev",
    "2026-12-25": "Christmas",
}
NSE_EARLY_CLOSE = {}  # NSE has no early closes; the Diwali Muhurat session is not a regular day
CALENDAR_YEARS = (2026,)
OPEN = datetime.time(9, 15)
CLOSE = datetime.time(15, 30)
EARLY = datetime.time(13, 0)


class RiskError(Exception):
    pass


# ---------------------------------------------------------------- time (IST, no tz files)

IST = datetime.timedelta(hours=5, minutes=30)


def to_ist(utc):
    """Naive UTC -> naive India time. India keeps UTC+5:30 all year: no daylight saving."""
    return utc.replace(tzinfo=None) + IST


def ist_to_utc(local):
    return local.replace(tzinfo=None) - IST


def parse_now(text):
    """ISO time -> naive UTC. A time without an offset is taken as India time (IST)."""
    if not text:
        return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)
    t = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise RiskError("--now wants a time like \"2026-10-26 10:00\" (IST) or ...Z (UTC)")
    if dt.tzinfo is None:
        return ist_to_utc(dt)
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def parse_utc(text):
    if not text:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = (dt - dt.utcoffset()).replace(tzinfo=None)
    return dt


def trading_day(d):
    """(is_trading_day, reason). Weekends and the NSE holiday list."""
    if d.weekday() >= 5:
        return False, "weekend"
    name = NSE_HOLIDAYS.get(d.isoformat())
    if name:
        return False, "NSE holiday: " + name
    return True, ""


def hhmm(value, key):
    """"09:30" -> time(9, 30); None or "" -> None (that bound is off)."""
    if value in (None, "", False):
        return None
    m = HHMM.match(str(value).strip())
    if not m:
        raise RiskError("%s must be an India time (IST) like \"09:30\", got %r" % (key, value))
    return datetime.time(int(m.group(1)), int(m.group(2)))


def window_check(now_ist, c):
    """Reasons an entry cannot be placed now (India time (IST)). Empty when the window is off."""
    before = hhmm(c.get("no_entries_before"), "no_entries_before")
    after = hhmm(c.get("no_entries_after"), "no_entries_after")
    if before is None and after is None:
        return [], []
    warns = []
    d, t = now_ist.date(), now_ist.time().replace(second=0, microsecond=0)
    if d.year not in CALENDAR_YEARS:
        warns.append("the holiday list covers %s only: check nseindia.com for %s"
                     % (" and ".join(map(str, CALENDAR_YEARS)), d.isoformat()))
    ok, why = trading_day(d)
    stamp = now_ist.strftime("%a %Y-%m-%d %H:%M")
    if not ok:
        return ["window: the market is closed today (%s, %s IST)" % (why, stamp)], warns
    close = EARLY if d.isoformat() in NSE_EARLY_CLOSE else CLOSE
    if t < OPEN or now_ist.time() >= close:
        return ["window: the market is closed (%s IST; the session is %s to %s)"
                % (stamp, OPEN.strftime("%H:%M"), close.strftime("%H:%M"))], warns
    if before is not None and t < before:
        return ["window: no new entries before %s IST (it is %s)" % (before.strftime("%H:%M"),
                                                                          t.strftime("%H:%M"))], warns
    if after is not None and t > after:
        return ["window: no new entries after %s IST (it is %s)" % (after.strftime("%H:%M"),
                                                                         t.strftime("%H:%M"))], warns
    return [], warns


# ---------------------------------------------------------------- files and helpers

def read_json(path, what, required=True):
    if not path or not os.path.exists(path):
        if required:
            raise RiskError("no %s at %s" % (what, path))
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as e:
        raise RiskError("%s is not valid JSON: %s" % (path, e))


def fingerprint(order):
    """Same function in trader-broker/ticket.py: the exact order that was checked."""
    core = {k: order[k] for k in ORDER_FIELDS if k in order and order[k] is not None}
    blob = json.dumps(core, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def money(x):
    return "₹" + "{:,.2f}".format(float(x)).replace(".00", "")


def _cent(x):
    """A price to the paisa, half up (1193.605 -> 1193.61)."""
    return int(float(x) * 100 + 0.5 + 1e-9) / 100.0


def nse_symbol(sym):
    """RELIANCE, reliance.ns or RELIANCE.NS -> RELIANCE, the NSE trading symbol."""
    s = str(sym).strip().upper()
    return s[:-3] if s.endswith(".NS") else s


def on_tick(x, tick):
    n = float(x) / float(tick)
    return abs(n - round(n)) < 1e-6


def charges(qty, buy_price, sell_price, rates):
    """Estimated charges of one intraday round trip (the same math as trader-budget)."""
    if not qty or qty <= 0:
        return 0.0
    buy, sell = qty * float(buy_price), qty * float(sell_price)

    def brokerage(value):
        flat = float(rates.get("brokerage_per_order_inr") or 0)
        pct = rates.get("brokerage_pct")
        return min(flat, value * float(pct) / 100.0) if pct else flat
    b = brokerage(buy) + brokerage(sell)
    exch = (buy + sell) * float(rates.get("exchange_pct") or 0) / 100.0
    sebi = (buy + sell) * float(rates.get("sebi_pct") or 0) / 100.0
    total = (b + sell * float(rates.get("stt_sell_pct") or 0) / 100.0 + exch + sebi
             + buy * float(rates.get("stamp_buy_pct") or 0) / 100.0
             + (b + exch + sebi) * float(rates.get("gst_pct") or 0) / 100.0)
    return round(total, 2)


def _p(x):
    return "%.2f" % float(x)


def account(cfg, portfolio, prices):
    """Starting account: cash and position values. No portfolio = a fresh
    account funded with the budget."""
    warnings = []
    if portfolio is None:
        budget = _f(cfg.get("budget"))
        if not budget:
            raise RiskError("no trader/portfolio.json and no budget in the config: "
                            "nothing to check the orders against")
        return {"cash": budget, "shares": {}, "values": {}}, warnings
    cash = _f(portfolio.get("cash"))
    if cash is None:
        raise RiskError("portfolio.json needs a \"cash\" number")
    shares, values = {}, {}
    for p in portfolio.get("positions", []):
        t = nse_symbol(p.get("ticker") or p.get("symbol") or "")
        if not t:
            continue
        n = _f(p.get("shares", p.get("qty")))
        if n is None:
            n = sum(_f(l.get("shares")) or 0 for l in p.get("lots", []))
        shares[t] = shares.get(t, 0) + n
        if prices.get(t):
            values[t] = shares[t] * prices[t]
        else:
            basis = sum(_f(l.get("cost")) or 0 for l in p.get("lots", []))
            values[t] = basis
            warnings.append("no price for %s: valued at its cost basis %s" % (t, money(basis)))
    return {"cash": cash, "shares": shares, "values": values}, warnings


def rec_day(rec):
    return str(rec.get("date") or str(rec.get("at", ""))[:10])


def rec_is_entry(rec):
    """trader-broker logs the kind trader-risk gave; older records: a buy is an entry."""
    k = rec.get("kind")
    if k:
        return k == "entry"
    return str(rec.get("side", "")).lower() == "buy"


def placed_today(state, today):
    """Orders recorded as placed today by trader-broker."""
    out = []
    for rec in (state or {}).get("orders", []):
        if rec.get("status") == "placed" and rec_day(rec) == today:
            out.append(rec)
    return out


# ---------------------------------------------------------------- the check

def check(orders, cfg, portfolio=None, prices=None, state=None, today=None, now=None, price_times=None,
          instruments=None):
    """Pure function. Returns {"results": [...], "pass": n, "block": n, "warnings": [...]}.

    now          naive UTC (default: the real clock); its IST date is "today"
    price_times  {SYM: naive UTC time of that price}; None = every price counts as fresh
    instruments  trader/instruments.json's rows {SYM: {instrument_key, tick, ...}}; None = not checked"""
    c = dict(DEFAULTS)
    c.update(cfg or {})
    prices = {nse_symbol(k): float(v) for k, v in (prices or {}).items() if _f(v)}
    rates = dict(CHARGES)
    rates.update(c.get("charges") or {})
    now_utc = now or parse_now(None)
    now_ist = to_ist(now_utc)
    today = today or now_ist.date().isoformat()
    acct, top_warn = account(c, portfolio, prices)
    blocked = {nse_symbol(b) for b in c.get("blocked") or []}
    done_today = placed_today(state, today)
    count_today = len(done_today)
    entries_today = [r for r in done_today if rec_is_entry(r)]
    loss_today = 0.0
    for r in entries_today:
        ml = _f(r.get("max_loss"))
        if ml is None:
            top_warn.append("an entry placed today (%s %s) has no max loss in the log; not counted in "
                            "the daily loss" % (r.get("side"), r.get("symbol")))
        else:
            loss_today += ml
    placed_keys = {(nse_symbol(r.get("symbol", "")), r.get("side")) for r in done_today}
    win_reasons, win_warns = window_check(now_ist, c)
    seen = set()
    results = []
    batch_entries, batch_loss = 0, 0.0
    if not c.get("paper", True):
        top_warn.append("LIVE account (\"paper\": false): these orders use real money")
    if instruments is None:
        top_warn.append("no trader/instruments.json: instrument keys, tick sizes and the EQ series are not "
                        "checked (run trader-scanner's scan.py universe)")
    top_warn.extend(win_warns)

    def fresh(sym):
        if sym not in prices:
            return None
        if price_times is None:
            return prices[sym]
        t = price_times.get(sym)
        if t is None:
            return None
        age = (now_utc - t).total_seconds()
        return prices[sym] if -60 <= age <= FRESH_MINUTES * 60 else None

    for i, o in enumerate(orders, 1):
        reasons, warns, info = [], [], []
        later = []                       # entry-only reasons, turned into warnings for an exit
        sym = nse_symbol(o.get("symbol", ""))
        side = str(o.get("side", "")).strip().lower()
        typ = str(o.get("order_type", "")).strip().upper()
        validity = str(o.get("validity", "DAY")).strip().upper()
        product = str(o.get("product", "")).strip().upper()
        token = str(o.get("instrument_token") or "").strip()
        qty = o.get("qty")
        plan = o.get("plan") if isinstance(o.get("plan"), dict) else {}
        bracket = str(o.get("order_class") or "").strip().lower() == "bracket"
        inst = (instruments or {}).get(sym) if instruments is not None else None
        tick = _f((inst or {}).get("tick")) or _f(plan.get("tick"))
        value = None

        # format
        if not sym:
            reasons.append("format: no symbol")
        if side not in ("buy", "sell"):
            reasons.append("format: side must be buy or sell, got %r" % o.get("side"))
        q = _f(qty)
        if q is None or q <= 0 or abs(q - round(q)) > 1e-9:
            reasons.append("format: qty must be a whole number of shares, got %r" % (qty,))
            q = None
        if product not in PRODUCTS:
            reasons.append("format: product must be I (intraday) or D (delivery), got %r" % o.get("product"))
        if typ not in TYPES:
            reasons.append("format: order_type must be MARKET, LIMIT, SL or SL-M, got %r" % o.get("order_type"))
        if validity not in VALIDITIES:
            reasons.append("format: validity must be DAY or IOC, got %r" % o.get("validity"))
        for k in PRICE_FIELDS:
            if o.get(k) not in (None, 0, 0.0):
                v = _f(o.get(k))
                if v is None or v <= 0:
                    reasons.append("format: %s must be a positive number, got %r" % (k, o.get(k)))
                elif tick and not on_tick(v, tick):
                    reasons.append("format: %s %s is not on %s's ₹%.2f tick: the exchange would reject it"
                                   % (k, _p(v), sym, tick))
        if typ in ("LIMIT", "SL") and not _f(o.get("price")):
            reasons.append("format: a %s order needs a price" % typ)
        if typ in ("SL", "SL-M") and not _f(o.get("trigger_price")):
            reasons.append("format: a %s order needs a trigger_price" % typ)
        if bracket:
            if typ != "LIMIT":
                reasons.append("format: a bracket's entry is a LIMIT order (Upstox fills GTT legs as limits), "
                               "got %s" % (typ or "nothing"))
            if o.get("stop_loss") is None or o.get("target") is None:
                reasons.append("format: a bracket needs both a stop_loss and a target")
        if not token:
            reasons.append("format: no instrument_token (Upstox's key, like NSE_EQ|INE002A01018): "
                           "run scan.py universe, then trader-budget again")
        elif token.split("|")[0] in ("NSE_FO", "BSE_FO", "MCX_FO", "NCD_FO", "BCD_FO"):
            if not c.get("allow_options"):
                reasons.append("asset: %s is a futures or options contract; F&O is off "
                               "(\"allow_options\": false)" % token)
            else:
                warns.append("F&O order: derivatives can lose more than you put in")
        elif not TOKEN.match(token):
            reasons.append("format: instrument_token %r is not an NSE equity key (NSE_EQ|<ISIN>)" % token)
        elif inst and inst.get("instrument_key") and inst["instrument_key"] != token:
            reasons.append("format: instrument_token %s is not %s's (%s in the instrument list): the order "
                           "would buy a different stock" % (token, sym, inst["instrument_key"]))

        # asset
        if sym and re.match(FNO, sym):
            if not c.get("allow_options"):
                reasons.append("asset: %s looks like a futures or options contract; F&O is off "
                               "(\"allow_options\": false)" % sym)
        elif sym and not SYMBOL.match(sym):
            reasons.append("asset: %s does not look like an NSE equity symbol; this pack trades NSE stocks "
                           "only" % sym)
        elif instruments is not None and sym and inst is None:
            later.append("asset: %s is not in NSE's EQ series list (trader/instruments.json): a BE / BZ stock "
                         "is trade-to-trade, delivery only, no intraday; or refresh the list (scan.py universe)"
                         % sym)
        if product == "D" and side == "buy":
            warns.append("product D is delivery: the shares stay in your demat overnight, outside the "
                         "day-trade plan")

        # the reference price: what one share costs to get in
        plan_entry = _f(plan.get("entry"))
        live = fresh(sym)
        ref, ref_from = None, None
        if typ in ("LIMIT", "SL"):
            ref, ref_from = _f(o.get("price")), "limit"
        elif typ == "SL-M":
            ref, ref_from = _f(o.get("trigger_price")), "stop price"
        if ref is None:
            cands = [(p, w) for p, w in ((plan_entry, "plan"), (live, "price")) if p]
            if cands:
                ref, ref_from = max(cands, key=lambda x: x[0])
                ref = _cent(ref)
                if live and ref_from == "price" and plan_entry and live > plan_entry + CENT:
                    info.append("%s last %s is above the plan's entry %s: the risk is measured from %s"
                                % (sym, _p(ref), _p(plan_entry), _p(ref)))
            elif sym in prices:
                ref, ref_from = prices[sym], "stale price"
        if plan_entry and live is None and sym in prices and price_times is not None and typ == "MARKET":
            warns.append("the %s price in trader/prices.json is older than %d minutes: not used"
                         % (sym, FRESH_MINUTES))
        if q and ref:
            value = q * ref

        # entry or exit
        held = acct["shares"].get(sym, 0.0)
        held_value = acct["values"].get(sym, 0.0)
        exiting = False
        if side == "sell" and held > 1e-9:
            if q is not None:
                exiting = q <= held + 1e-9
            elif value is not None:
                exiting = value <= held_value + CENT
        elif side == "buy" and held < -1e-9 and q is not None:
            exiting = q <= -held + 1e-9
        kind = "exit" if exiting else "entry"
        if kind == "entry" and value is None and q:
            later.append("price: no price for %s to size a %s-share order; add it to "
                         "trader/prices.json (trader-alerts: alerts.py quote %s --write)" % (sym, qty, sym))

        # blocked list and size
        if sym in blocked:
            later.append("blocked: %s is on your blocked list" % sym)
        if value is not None:
            if value < float(c.get("min_order_inr") or 0) - CENT:
                later.append("size: %s is under your %s minimum order"
                             % (money(value), money(c["min_order_inr"])))
            if c.get("max_order_inr") and value > float(c["max_order_inr"]) + CENT:
                later.append("size: %s is over your %s max order"
                             % (money(value), money(c["max_order_inr"])))

        # account effects, simulated in order
        cash = acct["cash"]
        total = cash + sum(acct["values"].values())
        buffer_inr = total * float(c.get("cash_buffer_pct") or 0) / 100.0
        if value is not None and side == "buy" and kind == "entry":
            after_cash = cash - value
            if after_cash < -CENT and not c.get("allow_margin"):
                later.append("cash: needs %s but only %s cash; that would be margin (Upstox's intraday "
                             "leverage, borrowed money)" % (money(value), money(cash)))
            elif after_cash < buffer_inr - CENT:
                later.append("cash: leaves %s cash, under your %s%% buffer of %s"
                             % (money(max(after_cash, 0)), _pct(c["cash_buffer_pct"]), money(buffer_inr)))
            pos_after = held_value + value
            limit = total * float(c.get("max_position_pct") or 100) / 100.0
            if total > 0 and pos_after > limit + CENT:
                later.append("position: %s would be %s, %.1f%% of the %s account, over your %s%% cap"
                             % (sym, money(pos_after), 100.0 * pos_after / total, money(total),
                                _pct(c["max_position_pct"])))
        if side == "sell" and sym and kind == "entry":
            if q is not None:
                over = q > held + 1e-9
            elif value is not None:
                over = value > held_value + CENT
            else:
                over = held <= 0
            if over and not c.get("allow_short"):
                reasons.append("short: selling more %s than you hold (%s shares); short selling is off. "
                               "If you bought it, record the fill first (ticket.py fill)" % (sym, _num(held)))

        # day-trade checks: stop, loss, reward:risk, daily loss, trades, window
        max_loss = risk_ps = rr = stop = target = None
        if kind == "entry" and side in ("buy", "sell"):
            long = side == "buy"
            leg_stop, plan_stop = _f(o.get("stop_loss")), _f(plan.get("stop"))
            stop = leg_stop if leg_stop else plan_stop
            target = _f(o.get("target")) or _f(plan.get("target"))
            if leg_stop and plan_stop and abs(leg_stop - plan_stop) > CENT:
                warns.append("the bracket stop %s differs from the plan's stop %s: the bracket's is the one "
                             "the broker uses" % (_p(leg_stop), _p(plan_stop)))
            if stop and not leg_stop:
                warns.append("the stop %s is in the plan only, not at the broker: set a stop alert "
                             "(trader-alerts: alerts.py add --from-plan)" % _p(stop))
            if not stop:
                if c.get("require_stop", True):
                    later.append("stop: no stop. Every entry needs one (\"require_stop\": true): a bracket "
                                 "stop_loss, from trader-exit and trader-budget")
                else:
                    warns.append("no stop: the max loss is not capped, so it is not counted in the daily loss")
            elif ref:
                if (long and stop >= ref - CENT) or (not long and stop <= ref + CENT):
                    later.append("stop: the stop %s must be %s the entry %s for a %s"
                                 % (_p(stop), "below" if long else "above", _p(ref), side))
                else:
                    risk_c = int(round(abs(ref - stop) * 100))
                    risk_ps = risk_c / 100.0
                    shares = q or 0
                    at_stop = round(shares * risk_ps, 2)
                    ch_stop = charges(shares, ref, stop, rates) if long else charges(shares, stop, ref, rates)
                    max_loss = round(at_stop + ch_stop, 2)
                    cap = _f(c.get("max_loss_per_trade_inr"))
                    if cap and max_loss > cap + CENT:
                        later.append("loss: %s shares x %s risk a share = %s at the stop, plus about %s in charges "
                                     "= %s, over your %s max loss per trade"
                                     % (_num(shares), _p(risk_ps), money(at_stop), money(ch_stop), money(max_loss),
                                        money(cap)))
                    min_rr = _f(c.get("min_reward_risk"))
                    if target:
                        if (long and target <= ref + CENT) or (not long and target >= ref - CENT):
                            later.append("target: the target %s must be %s the entry %s"
                                         % (_p(target), "above" if long else "below", _p(ref)))
                        else:
                            rr = round(int(round(abs(target - ref) * 100)) / float(risk_c), 2)
                            if min_rr and rr < min_rr - 1e-9:
                                later.append("reward:risk: %.2f (target %s, entry %s, stop %s) is under your "
                                             "minimum %s" % (rr, _p(target), _p(ref), _p(stop), _num(min_rr)))
                            elif shares:
                                gain = shares * abs(target - ref) - charges(shares, ref, target, rates)
                                net = gain / max_loss if max_loss else None
                                if net is not None and net < 1 - 1e-9:
                                    warns.append("after charges a win at the target is about %s and a loss at the "
                                                 "stop about %s: reward:risk %.2f net. Charges are a big share of "
                                                 "a trade this size" % (money(gain), money(max_loss), net))
                    elif min_rr:
                        later.append("reward:risk: no target to measure it against (min_reward_risk %s)"
                                     % _num(min_rr))
            daily = _f(c.get("max_daily_loss_inr"))
            if daily and max_loss is not None:
                used = loss_today + batch_loss
                if used + max_loss > daily + CENT:
                    later.append("daily loss: %s already at risk today plus %s for this one = %s, over your %s "
                                 "daily loss limit" % (money(used), money(max_loss), money(used + max_loss),
                                                       money(daily)))
            cap_t = int(c.get("max_trades_per_day") or 0)
            if cap_t and len(entries_today) + batch_entries >= cap_t:
                later.append("trades: %d entries placed today plus %d passed earlier in this batch, your limit "
                             "is %d a day" % (len(entries_today), batch_entries, cap_t))
            later.extend(win_reasons)
            if stop and ref and risk_ps:
                info.append("entry %s (%s), stop %s, target %s: risk %s a share"
                            % (_p(ref), REF_WORDS.get(ref_from, ref_from), _p(stop),
                               _p(target) if target else "none", _p(risk_ps)))
                info.append("max loss %s with charges%s, reward:risk %s%s"
                            % (money(max_loss), (" (limit %s)" % money(c["max_loss_per_trade_inr"]))
                               if _f(c.get("max_loss_per_trade_inr")) else "",
                               ("%.2f" % rr) if rr is not None else "n/a",
                               (" (min %s)" % _num(c["min_reward_risk"])) if _f(c.get("min_reward_risk")) else ""))
            if daily or cap_t:
                info.append("today before this: %d of %s trades, %s of %s daily loss"
                            % (len(entries_today) + batch_entries, cap_t or "unlimited",
                               money(loss_today + batch_loss), money(daily) if daily else "no limit on"))

        # duplicates and the daily order limit
        key = (sym, side)
        if key in seen:
            later.append("duplicate: a second %s %s in this batch" % (side, sym))
        if key in placed_keys:
            later.append("duplicate: a %s %s was already placed today" % (side, sym))
        passed_so_far = sum(1 for r in results if r["verdict"] == "PASS")
        cap_n = int(c.get("max_orders_per_day") or 0)
        if cap_n and count_today + passed_so_far >= cap_n:
            later.append("daily limit: %d placed today plus %d passed earlier in this batch, "
                         "your limit is %d a day" % (count_today, passed_so_far, cap_n))
        seen.add(key)

        if kind == "entry":
            reasons.extend(later)
        else:
            warns.extend("exit, not blocked: " + x for x in later)

        verdict = "BLOCK" if reasons else "PASS"
        if verdict == "PASS":
            if kind == "entry" and side in ("buy", "sell"):
                batch_entries += 1
                batch_loss += max_loss or 0.0
            if side == "buy":
                if value is not None:
                    acct["cash"] -= value
                    acct["values"][sym] = acct["values"].get(sym, 0.0) + value
                if q is not None:
                    acct["shares"][sym] = held + q
            elif side == "sell":
                if value is not None:
                    acct["cash"] += value
                    acct["values"][sym] = max(acct["values"].get(sym, 0.0) - value, 0.0)
                if q is not None:
                    acct["shares"][sym] = held - q
        results.append({
            "index": i, "symbol": sym, "side": side, "kind": kind,
            "amount": "%s shares" % qty, "product": product,
            "value_inr": round(value, 2) if value is not None else None,
            "entry_ref": round(ref, 2) if ref else None, "entry_ref_from": ref_from,
            "stop": stop, "target": target, "risk_per_share": risk_ps, "max_loss": max_loss,
            "reward_risk": rr, "fingerprint": fingerprint(o), "verdict": verdict,
            "reasons": reasons, "warnings": warns, "info": info,
        })

    return {
        "date": today,
        "now_ist": now_ist.strftime("%Y-%m-%d %H:%M"),
        "paper": bool(c.get("paper", True)),
        "results": results,
        "pass": sum(1 for r in results if r["verdict"] == "PASS"),
        "block": sum(1 for r in results if r["verdict"] == "BLOCK"),
        "warnings": top_warn,
        "cash_after": round(acct["cash"], 2),
        "today": {"orders_placed": count_today, "entries_placed": len(entries_today),
                  "loss_at_risk": round(loss_today, 2)},
    }


def _pct(x):
    x = float(x)
    return str(int(x)) if x == int(x) else ("%.2f" % x)


def _num(x):
    x = float(x)
    return str(int(x)) if x == int(x) else ("%.4f" % x).rstrip("0")


def report(res):
    lines = []
    for w in res["warnings"]:
        lines.append("WARNING: " + w)
    if res["warnings"]:
        lines.append("")
    for r in res["results"]:
        lines.append("%-5s #%d %s %s %s, %s" % (r["verdict"], r["index"], r["side"], r["symbol"], r["amount"],
                                                r["kind"]))
        for x in r.get("info", []):
            lines.append("          " + x)
        for x in r["reasons"]:
            lines.append("        - " + x)
        for x in r["warnings"]:
            lines.append("        ~ " + x)
    lines.append("")
    lines.append("%d passed, %d blocked at %s IST. Cash after the passed orders: %s (%s account)."
                 % (res["pass"], res["block"], res["now_ist"], money(res["cash_after"]),
                    "paper" if res["paper"] else "LIVE"))
    if res["block"]:
        lines.append("Blocked orders do not go to the broker. Fix the order or your rules, then check again.")
    else:
        lines.append("Every order passed. trader-broker still asks you yes or no for each one.")
    lines.append("Education and tooling, not financial advice.")
    return "\n".join(lines)


def load_prices(pdoc):
    """prices.json -> ({SYM: price}, {SYM: price time as naive UTC or None}).

    The price time is the quote's own time (detail.time), else when it was fetched
    (detail.fetched), else the file's as_of."""
    if not isinstance(pdoc, dict):
        return {}, {}
    prices = pdoc.get("prices", pdoc)
    if not isinstance(prices, dict):
        return {}, {}
    out, times = {}, {}
    as_of = parse_utc(pdoc.get("as_of"))
    detail = pdoc.get("detail") or {}
    for s, p in prices.items():
        if _f(p) is None:
            continue
        s = nse_symbol(s)
        out[s] = float(p)
        d = detail.get(s) or {}
        times[s] = parse_utc(d.get("time")) or parse_utc(d.get("fetched")) or as_of
    return out, times


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check proposed orders against your limits (trader-risk).")
    ap.add_argument("--orders", default="trader/orders.json")
    ap.add_argument("--config", default="trader/config.json")
    ap.add_argument("--portfolio", default="trader/portfolio.json",
                    help="your account; if missing, a fresh account funded with the budget")
    ap.add_argument("--prices", default="trader/prices.json")
    ap.add_argument("--state", default="trader/state/broker.json", help="what trader-broker placed today")
    ap.add_argument("--instruments", default="trader/instruments.json", help="trader-scanner's instrument list")
    ap.add_argument("--now", help="pretend it is this India time (IST), e.g. \"2026-10-26 10:00\"")
    ap.add_argument("--today", help="YYYY-MM-DD (default: today in India)")
    ap.add_argument("--out", default="trader/state/risk.json", help="where the verdicts are recorded")
    ap.add_argument("--no-write", action="store_true", help="do not record the verdicts")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        now = parse_now(a.now)
        if a.today and not re.match(r"^\d{4}-\d{2}-\d{2}$", a.today):
            raise RiskError("--today wants a date like 2026-10-26")
        doc = read_json(a.orders, "orders file (run trader-budget first)")
        orders = doc.get("orders", doc) if isinstance(doc, dict) else doc
        if not isinstance(orders, list) or not orders:
            raise RiskError("no orders in %s" % a.orders)
        cfg = read_json(a.config, "config", required=False) or {}
        portfolio = read_json(a.portfolio, "portfolio", required=False)
        pdoc = read_json(a.prices, "prices", required=False) or {}
        prices, times = load_prices(pdoc)
        state = read_json(a.state, "broker state", required=False)
        idoc = read_json(a.instruments, "instrument list", required=False)
        instruments = (idoc.get("instruments") or {}) if isinstance(idoc, dict) else None
        res = check(orders, cfg, portfolio, prices, state, a.today, now, times, instruments)
        if pdoc.get("as_of"):
            res["prices_as_of"] = pdoc["as_of"]
        if not a.no_write:
            d = os.path.dirname(a.out)
            if d:
                os.makedirs(d, exist_ok=True)
            rec = dict(res)
            rec["checked_at"] = datetime.datetime.now(datetime.timezone.utc).replace(
                microsecond=0, tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")
            rec["orders_file"] = a.orders
            tmp = a.out + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(rec, fh, indent=2)
                fh.write("\n")
            os.replace(tmp, a.out)
    except RiskError as e:
        print("check.py: %s" % e, file=sys.stderr)
        return 1
    print(json.dumps(res, indent=2) if a.json else report(res))
    return 1 if res["block"] else 0


if __name__ == "__main__":
    sys.exit(main())
