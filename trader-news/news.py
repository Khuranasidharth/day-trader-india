#!/usr/bin/env python3
"""News monitor for trader-news. NSE stocks, India time (IST). Standard library only.

Watches headlines for the stocks you watch or hold and prints only what is
new since the last check, newest first, with how far each stock has moved
today and a flag on anything that touches your symbols.

    python3 news.py                                  # watchlist + plan + portfolio symbols
    python3 news.py --tickers RELIANCE TCS M&M
    python3 news.py --tickers RELIANCE --all --hours 72  # everything in the last 3 days, seen or not
    python3 news.py --no-moves                       # skip the price line per symbol

Your symbols, when --tickers is not given: every hit in trader/watchlist.json
(trader-scanner), the symbol in trader/plan.json (trader-exit) and the
positions in trader/portfolio.json.

Sources, one request each per symbol:
  - Google News (India edition) RSS, searched by company name and NSE symbol:
    https://news.google.com/rss/search?q="Reliance Industries" OR "NSE:RELIANCE" when:2d&hl=en-IN&gl=IN&ceid=IN:en
    The company name comes from trader/instruments.json (trader-scanner's
    universe), else from --name SYMBOL="Company Name", else the symbol alone.
    Yahoo's headline feed is empty for NSE stocks, so it is not used.
  - The move: Yahoo Finance's chart endpoint (unofficial, can lag), the last
    price against yesterday's close:
    https://query2.finance.yahoo.com/v8/finance/chart/RELIANCE.NS?range=1d&interval=5m

Exchange filings (results, board meetings, insider trades, pledges) are on
NSE's corporate announcements page. NSE blocks scripts from it, so the tool
prints the link per symbol: open it in your browser.

Times print in India time (IST). State: trader/state/news.json remembers what
you have seen (30 days), so an item shows once. Offline: --offline DIR reads
gnews-<SYMBOL>.xml and chart-<SYMBOL>.json from DIR. The tests use it.

Headlines are leads, not facts: open the story before acting, and treat
nothing here as advice.
"""

import argparse
import datetime as _dt
import email.utils
import gzip
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

GNEWS = "https://news.google.com/rss/search?q=%s&hl=en-IN&gl=IN&ceid=IN:en"
CHART = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=5m"
NSE_FILINGS = "https://www.nseindia.com/companies-listing/corporate-filings-announcements?symbol=%s"
UA = "Mozilla/5.0 (compatible; day-trader-skill/2.0; +https://github.com/Jakeschincariol/day-trader-skill)"
KEEP_DAYS = 30
MOVE_PCT = 3.0  # a stock this far from yesterday's close is flagged as moving
NAME_TAIL = re.compile(r"[\s,.]+(limited|ltd\.?|ltd|india|corporation|corp\.?|company|co\.?)$", re.I)
KEYWORDS = [
    ("earnings", r"\bearnings\b|\bresults\b|\bQ[1-4]\b|\bnet profit\b|\bPAT\b|\bEBITDA\b|\bguidance\b|\bboard meeting\b"),
    ("analyst", r"\bupgrade[sd]?\b|\bdowngrade[sd]?\b|target price|price target|\bsets\b.{0,40}\btarget\b|\boutperform\b|\bunderperform\b|\bbuy call\b|\b(buy|sell|hold) rating\b"),
    ("legal", r"\blawsuit\b|\bprobe\b|\binvestigation\b|\bNCLT\b|\bcourt\b|\bED raids?\b|\bshow[- ]cause\b|\bpenalt"),
    ("deal", r"\bacqui(?:re|res|red|sition)\b|\bmerger\b|\bdemerger\b|\bstake\b|\bblock deal\b|\bbulk deal\b|\bdeal\b|\border win\b|\bbags order\b"),
    ("capital", r"\bdividend\b|\bbuyback\b|\bbonus\b|\bstock split\b|\bQIP\b|\brights issue\b|\bOFS\b|\bIPO\b|\bfund ?rais"),
    ("people", r"\bCEO\b|\bCFO\b|\bMD\b|\bchairman\b|\bresign|\bsteps down\b|\bappoint"),
    ("risk", r"\bpledge\b|\bdefault\b|\binsolvency\b|\bdelist|\bdowngrade by\b|\bfraud\b|\bhack|\bbreach\b|\boutage\b"),
    ("halt", r"\bupper circuit\b|\blower circuit\b|\bcircuit\b|\bsuspend|\bASM\b|\bGSM\b"),
    ("regulatory", r"\bSEBI\b|\bRBI\b|\bCCI\b|\bUSFDA\b|\bFDA\b|\bapproval\b|\blicen[cs]e\b|\bministry\b"),
    ("macro", r"\bRBI policy\b|\brepo rate\b|\binflation\b|\bCPI\b|\bGDP\b|\bBudget\b|\bFII\b|\bFPI\b|\bSensex\b|\bNifty\b|\btariffs?\b|\bcrude\b|\brupee\b"),
]


class NewsError(Exception):
    pass


# ---------------------------------------------------------------- time

IST = _dt.timedelta(hours=5, minutes=30)


def to_ist(utc):
    """Aware or naive UTC -> naive India time. India keeps UTC+5:30 all year: no daylight saving."""
    if utc.tzinfo is not None:
        utc = utc.astimezone(_dt.timezone.utc)
    return utc.replace(tzinfo=None) + IST


# ---------------------------------------------------------------- inputs

def load_json(path):
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def nse_symbol(sym):
    """RELIANCE, reliance.ns or RELIANCE.NS -> RELIANCE, the NSE trading symbol."""
    s = str(sym).strip().upper()
    return s[:-3] if s.endswith(".NS") else s


def short_name(name):
    """'Reliance Industries Limited' -> 'Reliance Industries' (what headlines say)."""
    n = " ".join(str(name or "").split())
    for _ in range(3):
        m = NAME_TAIL.search(n)
        if not m or len(n[:m.start()]) < 3:
            break
        n = n[:m.start()]
    return n.strip()


def watch_from_files(portfolio="trader/portfolio.json", watchlist="trader/watchlist.json",
                     plan="trader/plan.json", instruments="trader/instruments.json"):
    """{symbol: company name or None}: the scanner's hits, the planned trade and your holdings."""
    out = {}
    wl = load_json(watchlist) or {}
    for h in wl.get("hits", []):
        sym = h.get("symbol") or h.get("ticker")
        if sym:
            out[nse_symbol(sym)] = h.get("name")
    pl = load_json(plan) or {}
    if pl.get("symbol"):
        out.setdefault(nse_symbol(pl["symbol"]), pl.get("name"))
    pf = load_json(portfolio) or {}
    for p in pf.get("positions", []):
        sym = p.get("ticker") or p.get("symbol")
        if sym:
            out[nse_symbol(sym)] = p.get("name") or out.get(nse_symbol(sym))
    return with_names(out, instruments)


def with_names(watch, instruments="trader/instruments.json"):
    inst = ((load_json(instruments) or {}).get("instruments") or {})
    return {s: (n or (inst.get(s) or {}).get("name")) for s, n in watch.items()}


# ---------------------------------------------------------------- fetching

class Fetcher(object):
    def __init__(self, offline=None, pause=0.5):
        self.offline = offline
        self.pause = pause
        self._last = 0.0

    def get(self, url, name):
        if self.offline:
            path = os.path.join(self.offline, name)
            if not os.path.isfile(path):
                raise NewsError("offline: no file %s" % path)
            with open(path, "rb") as fh:
                return fh.read()
        gap = time.time() - self._last
        if gap < self.pause:
            time.sleep(self.pause - gap)
        self._last = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as exc:
            raise NewsError("HTTP %s for %s" % (exc.code, url.split("?")[0]))
        except urllib.error.URLError as exc:
            raise NewsError("could not reach %s: %s" % (url.split("/")[2], exc.reason))


def yahoo_symbol(sym):
    return urllib.parse.quote(nse_symbol(sym) + ".NS", safe="")


def gnews_query(sym, name, hours=48):
    days = max(1, int(round(hours / 24.0)))
    terms = ['"NSE:%s"' % sym]
    if name and short_name(name):
        terms.insert(0, '"%s"' % short_name(name))
    elif len(sym) >= 4:
        terms.insert(0, '"%s"' % sym)
    return "%s when:%dd" % (" OR ".join(terms), days)


def gnews_url(sym, name, hours=48):
    return GNEWS % urllib.parse.quote(gnews_query(sym, name, hours))


# ---------------------------------------------------------------- parsing

def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _text(el, name):
    for c in el.iter():
        if _local(c.tag) == name:
            return (c.text or "").strip()
    return ""


def parse_time(value):
    """RFC 822 (RSS) or ISO 8601 (Atom) -> aware UTC datetime, or None."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        d = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        d = None
    if d is None:
        try:
            d = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d.astimezone(_dt.timezone.utc)


def parse_gnews(data, ticker):
    """Google News RSS -> items. Titles end in " - Publisher"; the publisher is also in <source>."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NewsError("news feed for %s is not valid XML: %s" % (ticker, exc))
    out = []
    for it in root.iter("item"):
        title = _text(it, "title")
        publisher = _text(it, "source")
        if publisher and title.endswith(" - " + publisher):
            title = title[:-(len(publisher) + 3)]
        link = _text(it, "link")
        guid = _text(it, "guid") or link
        summary = re.sub(r"<[^>]+>", " ", _text(it, "description"))
        out.append({"id": "gnews:" + guid, "source": publisher or "Google News", "kind": "headline",
                    "ticker": ticker, "title": title, "summary": " ".join(summary.split()),
                    "link": link, "time": parse_time(_text(it, "pubDate"))})
    return out


def parse_chart(data, ticker):
    """Yahoo chart JSON -> {"ticker", "price", "prev_close", "pct", "time"} or raise."""
    try:
        doc = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
        meta = doc["chart"]["result"][0]["meta"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise NewsError("chart for %s is not usable" % ticker)
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if not price or not prev:
        raise NewsError("chart for %s has no price" % ticker)
    when = meta.get("regularMarketTime")
    return {"ticker": ticker, "price": round(float(price), 2), "prev_close": round(float(prev), 2),
            "pct": round((float(price) / float(prev) - 1) * 100, 2),
            "time": _dt.datetime.fromtimestamp(when, _dt.timezone.utc) if when else None}


def collect_moves(fetcher, watch, errors=None):
    errors = [] if errors is None else errors
    out = []
    for t in sorted(watch):
        name = "chart-%s.json" % t
        try:
            try:
                data = fetcher.get(CHART % ("query2", yahoo_symbol(t)), name)
            except NewsError as exc:
                if fetcher.offline or not re.search(r"HTTP (429|5\d\d)", str(exc)):
                    raise
                data = fetcher.get(CHART % ("query1", yahoo_symbol(t)), name)
            out.append(parse_chart(data, t))
        except NewsError as exc:
            if not (fetcher.offline and "no file" in str(exc)):
                errors.append("price for %s: %s" % (t, exc))
    return out


def mention_patterns(watch):
    pats = {}
    for t, name in watch.items():
        alts = [r"\(%s\)" % re.escape(t), r"\b(?:NSE|BSE)\s*:\s*%s\b" % re.escape(t)]
        if len(t) >= 4 and t.isalpha():
            alts.append(r"\b%s\b" % re.escape(t))
        short = short_name(name)
        if short and len(short) >= 4:
            alts.append(r"\b%s\b" % re.escape(short).replace(r"\ ", r"[\s-]"))
        pats[t] = re.compile("|".join(alts))
    return pats


def tag(items, watch):
    """Which of your tickers each item touches, and why it matters."""
    pats = mention_patterns(watch)
    for it in items:
        hay = "%s %s" % (it["title"], it.get("summary") or "")
        touches = {it["ticker"]} if it["ticker"] in watch else set()
        for t, rx in pats.items():
            if rx.search(hay):
                touches.add(t)
        it["touches"] = sorted(touches)
        it["tags"] = [label for label, rx in KEYWORDS if re.search(rx, hay, re.I)]
    return items


def dedupe(items):
    """One item per story: same id, or same link, or same title the same day."""
    seen, out = {}, []
    for it in items:
        keys = [it["id"], it["link"],
                "%s|%s" % (re.sub(r"\W+", " ", it["title"].lower()).strip(),
                           it["time"].date() if it["time"] else "")]
        hit = next((seen[k] for k in keys if k and k in seen), None)
        if hit is not None:
            for t in it.get("touches", []):
                if t not in hit["touches"]:
                    hit["touches"].append(t)
            hit["touches"].sort()
            continue
        for k in keys:
            if k:
                seen[k] = it
        out.append(it)
    return out


def fingerprint(it):
    return hashlib.sha1(it["id"].encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- the check

def collect(fetcher, watch, hours=48, errors=None):
    errors = [] if errors is None else errors
    items = []
    for t in sorted(watch):
        try:
            items += parse_gnews(fetcher.get(gnews_url(t, watch[t], hours), "gnews-%s.xml" % t), t)
        except NewsError as exc:
            errors.append("headlines for %s: %s" % (t, exc))
    return items


def select(items, state, now, hours=48, show_all=False):
    """Items within the window; only unseen ones unless show_all."""
    seen = state.setdefault("seen", {})
    cutoff = now - _dt.timedelta(hours=hours)
    ahead = now + _dt.timedelta(minutes=10)  # a pinned --now: nothing from after it
    out = []
    for it in items:
        if it["time"] is not None and (it["time"] < cutoff or it["time"] > ahead):
            continue
        fp = fingerprint(it)
        it["new"] = fp not in seen
        if it["new"] or show_all:
            out.append(it)
    out.sort(key=lambda i: (i["time"] or now), reverse=True)
    return out


def remember(items, state, now):
    seen = state.setdefault("seen", {})
    stamp = now.isoformat()
    for it in items:
        seen.setdefault(fingerprint(it), stamp)
    cutoff = (now - _dt.timedelta(days=KEEP_DAYS)).isoformat()
    state["seen"] = {k: v for k, v in seen.items() if v >= cutoff}
    state["last_check"] = stamp


def render_moves(moves, move_pct=MOVE_PCT):
    out = []
    for m in moves:
        flag = "MOVING" if abs(m["pct"]) >= move_pct else ""
        when = (" at %s IST" % to_ist(m["time"]).strftime("%H:%M")) if m.get("time") else ""
        out.append("%-10s %s %+.2f%% vs yesterday's close %s%s  %s" % (
            m["ticker"], "{:,.2f}".format(m["price"]), m["pct"], "{:,.2f}".format(m["prev_close"]),
            when, flag))
    return out


def render(items, errors, now, moves=None, move_pct=MOVE_PCT, watch=()):
    out = render_moves(moves or [], move_pct)
    if out:
        out.append("")
    if not items:
        out.append("Nothing new.")
    for it in items:
        when = to_ist(it["time"]).strftime("%Y-%m-%d %H:%M IST") if it["time"] else "time unknown"
        mark = "!" if set(it["tags"]) & {"earnings", "halt", "risk", "legal", "regulatory"} else " "
        who = ",".join(it["touches"]) or it["ticker"]
        out.append("%s %s  %-11s %-18s %s" % (mark, when, who, it["source"][:18], it["title"]))
        extra = []
        if it["tags"]:
            extra.append("tags: " + ", ".join(it["tags"]))
        extra.append(it["link"])
        out.append("      " + "  ".join(extra))
    for e in errors:
        out.append("note: %s" % e)
    for t in sorted(watch):
        out.append("Exchange filings for %s (results, board meetings, insider trades): %s" % (t, NSE_FILINGS % t))
    out.append("Checked %s. Headlines are leads, not facts; open the story before acting. "
               "Not financial advice." % to_ist(now).strftime("%Y-%m-%d %H:%M IST"))
    return "\n".join(out) + "\n"


def _json_ready(items):
    out = []
    for it in items:
        d = dict(it)
        d["time"] = it["time"].isoformat() if it["time"] else None
        out.append(d)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tickers", nargs="*", help="NSE symbols; default: watchlist + plan + portfolio")
    ap.add_argument("--name", action="append", default=[], metavar='SYM="Company"',
                    help="the company name to search for (default: from trader/instruments.json)")
    ap.add_argument("--instruments", default="trader/instruments.json")
    ap.add_argument("--portfolio", default="trader/portfolio.json")
    ap.add_argument("--watchlist", default="trader/watchlist.json")
    ap.add_argument("--plan", default="trader/plan.json")
    ap.add_argument("--state", default="trader/state/news.json")
    ap.add_argument("--hours", type=float, default=48, help="ignore items older than this")
    ap.add_argument("--all", action="store_true", help="show seen items too")
    ap.add_argument("--no-moves", action="store_true", help="skip the price line per ticker")
    ap.add_argument("--move-pct", type=float, default=MOVE_PCT, help="flag a move this big (percent)")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--now", help="ISO time, for reproducible runs")
    ap.add_argument("--dry-run", action="store_true", help="do not update the state file")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.tickers:
        watch = with_names({nse_symbol(t): None for t in args.tickers}, args.instruments)
    else:
        watch = watch_from_files(args.portfolio, args.watchlist, args.plan, args.instruments)
    for pair in args.name:
        if "=" not in pair:
            print("news: --name wants SYMBOL=\"Company Name\"", file=sys.stderr)
            return 2
        k, v = pair.split("=", 1)
        if nse_symbol(k) in watch:
            watch[nse_symbol(k)] = v.strip().strip('"')
    if not watch:
        print("news: no symbols. Pass --tickers, or run /trader-scanner first (it writes "
              "trader/watchlist.json).", file=sys.stderr)
        return 2
    now = parse_time(args.now) if args.now else _dt.datetime.now(_dt.timezone.utc)
    state = load_json(args.state) or {}
    errors = []
    fetcher = Fetcher(offline=args.offline)
    items = collect(fetcher, watch, args.hours, errors)
    items = dedupe(tag(items, watch))
    shown = select(items, state, now, hours=args.hours, show_all=args.all)
    moves = [] if args.no_moves else collect_moves(fetcher, watch, errors)
    if args.json:
        mv = [dict(m, time=m["time"].isoformat() if m.get("time") else None,
                   moving=abs(m["pct"]) >= args.move_pct) for m in moves]
        print(json.dumps({"checked": now.isoformat(), "moves": mv, "items": _json_ready(shown),
                          "notes": errors}, indent=2))
    else:
        sys.stdout.write(render(shown, errors, now, moves, args.move_pct, watch))
    if not args.dry_run:
        remember(items, state, now)
        folder = os.path.dirname(args.state)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(args.state, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
            fh.write("\n")
    return 0 if any(i["new"] for i in shown) else 1


if __name__ == "__main__":
    sys.exit(main())
