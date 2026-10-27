#!/usr/bin/env python3
"""Earnings reader for trader-analyst. NSE stocks, Indian fiscal years, rupees.
Standard library only.

Pulls a company's reported numbers and lays out what changed, quarter by
quarter and year by year: revenue, gross, operating and net margins, net
income, diluted EPS, and growth against the same quarter a year earlier.

    python3 facts.py RELIANCE
    python3 facts.py RELIANCE TCS --quarters 8
    python3 facts.py RELIANCE --json
    python3 facts.py RELIANCE TCS INFY ITC --metrics trader/metrics.json

Source: Yahoo Finance's fundamentals time series (free, unofficial, no key):
  https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/RELIANCE.NS
      ?type=quarterlyTotalRevenue,quarterlyNetIncome,...&period1=...&period2=...
Yahoo has about five recent quarters and four fiscal years for NSE stocks,
and it skips quarters now and then (it can be weeks behind a results
announcement; banks often have almost no quarterly lines). The tool never
fills a gap: a missing quarter is said, growth is only computed against the
same quarter a year earlier when Yahoo has both, and the exchange filing is
always linked, because the filing is the authority:
  https://www.nseindia.com/companies-listing/corporate-filings-financial-results?symbol=RELIANCE
  (NSE blocks scripts from its pages: open it in your browser.)

Indian fiscal years end on March 31: the quarter ending 2026-06-30 is Q1
FY27, 2026-03-31 is Q4 FY26. Amounts print in rupee crore (1 crore = 10
million), EPS in rupees. Consolidated figures, as Yahoo reports them.

--metrics FILE merges one row per symbol into a JSON file (for notes or a
sheet). Offline: --offline DIR reads fundamentals-<SYMBOL>.json from DIR.

Numbers only: this tool never says whether a stock is a buy.
"""

import argparse
import datetime as _dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

URL = ("https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/%s"
       "?type=%s&period1=%d&period2=%d")
FILINGS = "https://www.nseindia.com/companies-listing/corporate-filings-financial-results?symbol=%s"
UA = "Mozilla/5.0 (compatible; day-trader-skill/2.0; +https://github.com/Jakeschincariol/day-trader-skill)"
FIELDS = ("TotalRevenue", "GrossProfit", "OperatingIncome", "NetIncome", "DilutedEPS")
CRORE = 1e7
PAUSE = 0.5


class FactsError(Exception):
    pass


def nse_symbol(sym):
    s = str(sym).strip().upper()
    return s[:-3] if s.endswith(".NS") else s


def fiscal_label(end, annual=False):
    """2026-06-30 -> 'Q1 FY27'; 2026-03-31 annual -> 'FY26'."""
    d = _dt.date.fromisoformat(end)
    fy = d.year + 1 if d.month > 3 else d.year
    if annual:
        return "FY%02d" % (fy % 100)
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(d.month)
    return ("Q%d FY%02d" % (q, fy % 100)) if q else "FY%02d %s" % (fy % 100, d.strftime("%b"))


def quarter_before(end, n=1):
    """The quarter end n quarters before (2026-06-30, 4 -> 2025-06-30)."""
    d = _dt.date.fromisoformat(end)
    m = d.month - 3 * n
    y = d.year
    while m <= 0:
        m += 12
        y -= 1
    last = {3: 31, 6: 30, 9: 30, 12: 31}.get(m)
    return _dt.date(y, m, last).isoformat() if last else None


# ---------------------------------------------------------------- fetching

def fetch(sym, now=None, offline=None):
    sym = nse_symbol(sym)
    if offline:
        path = os.path.join(offline, "fundamentals-%s.json" % sym)
        if not os.path.exists(path):
            raise FactsError("offline: no file %s" % path)
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    now = now or _dt.datetime.now(_dt.timezone.utc)
    end = int(now.timestamp()) + 86400
    start = end - 6 * 366 * 86400
    types = ",".join(["quarterly" + f for f in FIELDS] + ["annual" + f for f in FIELDS])
    url = URL % (urllib.parse.quote(sym + ".NS", safe=""), types, start, end)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise FactsError("Yahoo answered HTTP %d for %s" % (e.code, sym))
    except (urllib.error.URLError, OSError) as e:
        raise FactsError("could not reach Yahoo: %s" % getattr(e, "reason", e))


def parse(text, sym):
    """Yahoo's time series -> {"quarterly": {field: {end: value}}, "annual": {...}}."""
    try:
        res = json.loads(text)["timeseries"]["result"]
    except (ValueError, KeyError, TypeError):
        raise FactsError("Yahoo returned something unexpected for %s" % sym)
    out = {"quarterly": {f: {} for f in FIELDS}, "annual": {f: {} for f in FIELDS}}
    for r in res or []:
        t = ((r.get("meta") or {}).get("type") or [""])[0]
        for period in ("quarterly", "annual"):
            if t.startswith(period):
                f = t[len(period):]
                if f in FIELDS:
                    for x in r.get(t) or []:
                        if x and x.get("asOfDate") and (x.get("reportedValue") or {}).get("raw") is not None:
                            out[period][f][x["asOfDate"]] = float(x["reportedValue"]["raw"])
    if not any(out["quarterly"][f] or out["annual"][f] for f in FIELDS):
        raise FactsError("Yahoo has no reported numbers for %s (check the NSE symbol)" % sym)
    return out


# ---------------------------------------------------------------- the analysis

def _growth(cur, prev):
    if cur is None or prev is None or prev == 0:
        return None
    return round((cur / prev - 1) * 100 * (1 if prev > 0 else -1), 1)


def _margin(part, whole):
    if part is None or not whole:
        return None
    return round(part / whole * 100, 1)


def rows_for(series, ends, annual=False):
    rows = []
    for end in ends:
        g = {f: series[f].get(end) for f in FIELDS}
        prev_end = (str(int(end[:4]) - 1) + end[4:]) if annual else quarter_before(end, 4)
        p = {f: series[f].get(prev_end) for f in FIELDS}
        rows.append({
            "end": end, "fiscal": fiscal_label(end, annual), "revenue": g["TotalRevenue"],
            "revenue_yoy": _growth(g["TotalRevenue"], p["TotalRevenue"]),
            "gross_margin": _margin(g["GrossProfit"], g["TotalRevenue"]),
            "operating_margin": _margin(g["OperatingIncome"], g["TotalRevenue"]),
            "net_margin": _margin(g["NetIncome"], g["TotalRevenue"]),
            "net_income": g["NetIncome"], "net_income_yoy": _growth(g["NetIncome"], p["NetIncome"]),
            "eps_diluted": g["DilutedEPS"], "eps_yoy": _growth(g["DilutedEPS"], p["DilutedEPS"]),
            "operating_income": g["OperatingIncome"],
        })
    return rows


def gaps(ends):
    """Quarter ends missing between the oldest and the newest Yahoo has."""
    if not ends:
        return []
    have, out = set(ends), []
    e = max(ends)
    while e and e > min(ends):
        e = quarter_before(e)
        if e and e not in have and e > min(ends):
            out.append(e)
    return sorted(out)


STALE_DAYS = 150   # a quarter this old means at least one newer result is out


def analyse(data, quarters=6, name=None, sym="", today=None):
    q, a = data["quarterly"], data["annual"]
    q_ends = sorted({e for f in FIELDS for e in q[f]}, reverse=True)
    a_ends = sorted({e for f in FIELDS for e in a[f]}, reverse=True)
    result = {"symbol": sym, "name": name, "quarters": rows_for(q, q_ends[:quarters]),
              "years": rows_for(a, a_ends[:4], annual=True), "missing_quarters": gaps(q_ends),
              "filings": FILINGS % sym}
    today = today or _dt.date.today()
    result["stale"] = bool(q_ends) and (today - _dt.date.fromisoformat(q_ends[0])).days > STALE_DAYS
    eps = [r["eps_yoy"] for r in result["quarters"] + result["years"] if r["eps_yoy"] is not None]
    result["eps_jump"] = any(abs(x) >= 40 for x in eps)
    four = q_ends[:4]
    ttm = {}
    if len(four) == 4 and four[-1] == quarter_before(four[0], 3):
        for key, f in (("revenue", "TotalRevenue"), ("net_income", "NetIncome"), ("eps_diluted", "DilutedEPS")):
            vals = [q[f].get(e) for e in four]
            if all(v is not None for v in vals):
                ttm[key] = round(sum(vals), 2)
        ttm["through"] = four[0]
    result["ttm"] = ttm
    return result


def changes(result):
    out = []
    rows = [r for r in result["quarters"] if r["revenue"] is not None or r["net_income"] is not None]
    if rows:
        cur = rows[0]
        bits = []
        if cur["revenue"] is not None:
            bits.append("revenue %s%s" % (_cr(cur["revenue"]), (" (%s against %s)" % (
                _pct(cur["revenue_yoy"]), fiscal_label(quarter_before(cur["end"], 4))))
                if cur["revenue_yoy"] is not None else " (no year-earlier quarter from Yahoo)"))
        if cur["net_income"] is not None:
            bits.append("net profit %s%s" % (_cr(cur["net_income"]), (" (%s)" % _pct(cur["net_income_yoy"]))
                                              if cur["net_income_yoy"] is not None else ""))
        if cur["eps_diluted"] is not None:
            bits.append("diluted EPS ₹%.2f%s" % (cur["eps_diluted"], (" (%s)" % _pct(cur["eps_yoy"]))
                                                  if cur["eps_yoy"] is not None else ""))
        out.append("%s (quarter ended %s): %s." % (cur["fiscal"], cur["end"], ", ".join(bits)))
        prev = rows[1] if len(rows) > 1 and rows[1]["end"] == quarter_before(cur["end"]) else None
        if prev and cur["operating_margin"] is not None and prev["operating_margin"] is not None:
            out.append("Operating margin %.1f%%, %+.1f points on %s." % (
                cur["operating_margin"], cur["operating_margin"] - prev["operating_margin"], prev["fiscal"]))
        if (cur["net_income"] is not None and cur["operating_income"] is not None
                and cur["net_income"] > cur["operating_income"]):
            out.append("Net profit is above operating profit: other income or one-off gains are inside it.")
    else:
        out.append("Yahoo has no recent quarters for %s: read the results filing." % result["symbol"])
    yrs = result["years"]
    if yrs and yrs[0]["revenue"] is not None:
        y = yrs[0]
        out.append("%s (year ended %s): revenue %s%s, net profit %s%s." % (
            y["fiscal"], y["end"], _cr(y["revenue"]), (" (%s)" % _pct(y["revenue_yoy"])) if y["revenue_yoy"] is not None else "",
            _cr(y["net_income"]), (" (%s)" % _pct(y["net_income_yoy"])) if y["net_income_yoy"] is not None else ""))
    if result.get("stale") and rows:
        out.append("Yahoo's newest quarter, %s, ended %s: newer results are out. Read them in the filings."
                   % (rows[0]["fiscal"], rows[0]["end"]))
    if result.get("eps_jump"):
        out.append("An EPS change of 40% or more: check for a bonus issue or a split, which Yahoo does not "
                   "always adjust for, before reading it as a fall or a jump in earnings.")
    if result["missing_quarters"]:
        out.append("Yahoo is missing %s: read those in the filings, never guess them." % ", ".join(
            "%s (%s)" % (fiscal_label(e), e) for e in result["missing_quarters"]))
    return out


# ---------------------------------------------------------------- output

def _cr(v):
    if v is None:
        return "-"
    return "₹%s cr" % indian(v / CRORE)


def indian(x):
    """1234567.8 -> '12,34,568' (Indian grouping, whole numbers)."""
    n = int(round(abs(x)))
    s = str(n)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-" if x < 0 else "") + s


def _pct(v):
    return "-" if v is None else "%+.1f%%" % v


def _pm(v):
    return "-" if v is None else "%.1f%%" % v


def table(rows, head):
    out = ["%-11s %-8s %12s %8s %7s %7s %7s %12s %8s %7s" % (
        head, "fiscal", "revenue cr", "rev yoy", "gross", "oper", "net", "profit cr", "EPS dil", "EPS yoy")]
    for r in rows:
        out.append("%-11s %-8s %12s %8s %7s %7s %7s %12s %8s %7s" % (
            r["end"], r["fiscal"], indian(r["revenue"] / CRORE) if r["revenue"] is not None else "-",
            _pct(r["revenue_yoy"]), _pm(r["gross_margin"]), _pm(r["operating_margin"]), _pm(r["net_margin"]),
            indian(r["net_income"] / CRORE) if r["net_income"] is not None else "-",
            "-" if r["eps_diluted"] is None else "%.2f" % r["eps_diluted"], _pct(r["eps_yoy"])))
    return out


def render(result):
    head = "%s%s. Rupee crore except EPS (rupees). Source: Yahoo Finance fundamentals (unofficial)." % (
        result["symbol"], (" (%s)" % result["name"]) if result.get("name") else "")
    out = [head, ""]
    if result["quarters"]:
        out += table(result["quarters"], "quarter end")
    if result["years"]:
        out += [""] + table(result["years"], "year end")
    t = result["ttm"]
    if t:
        out += ["", "Last 4 quarters (to %s): revenue %s, net profit %s, diluted EPS %s." % (
            t["through"], _cr(t.get("revenue")), _cr(t.get("net_income")),
            "₹%.2f" % t["eps_diluted"] if t.get("eps_diluted") is not None else "-")]
    out += ["", "What changed:"] + ["  - " + x for x in changes(result)]
    out += ["", "The filing is the authority: %s" % result["filings"],
            "Yahoo can lag a results announcement; if the latest board-meeting results are newer than the "
            "table, read the filing."]
    return "\n".join(out) + "\n"


def metrics_row(result):
    cur = result["quarters"][0] if result["quarters"] else {}
    t = result["ttm"]
    return {"symbol": result["symbol"], "name": result.get("name"), "period_end": cur.get("end"),
            "fiscal": cur.get("fiscal"), "revenue_ttm": t.get("revenue"), "net_income_ttm": t.get("net_income"),
            "eps_ttm": t.get("eps_diluted"), "revenue_growth_yoy": cur.get("revenue_yoy"),
            "eps_growth_yoy": cur.get("eps_yoy"), "net_income_growth_yoy": cur.get("net_income_yoy"),
            "gross_margin": cur.get("gross_margin"), "operating_margin": cur.get("operating_margin"),
            "net_margin": cur.get("net_margin"), "missing_quarters": result["missing_quarters"],
            "stale": result.get("stale"),
            "source": "Yahoo Finance fundamentals (unofficial)"}


def names(path="trader/instruments.json"):
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return {k: v.get("name") for k, v in (json.load(fh).get("instruments") or {}).items()}
        except (ValueError, AttributeError):
            return {}
    return {}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Earnings reader (trader-analyst): what the numbers say changed.")
    ap.add_argument("symbols", nargs="+", help="NSE symbols, like RELIANCE TCS")
    ap.add_argument("--quarters", type=int, default=6)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--metrics", metavar="FILE", help="merge one row per symbol into this JSON file")
    ap.add_argument("--instruments", default="trader/instruments.json", help="for company names")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--now", help="ISO date, for reproducible runs")
    a = ap.parse_args(argv)
    now = None
    if a.now:
        now = _dt.datetime.fromisoformat(a.now).replace(tzinfo=_dt.timezone.utc)
    known = names(a.instruments)
    results, code = [], 0
    for i, s in enumerate(a.symbols):
        sym = nse_symbol(s)
        try:
            if i and not a.offline:
                time.sleep(PAUSE)
            res = analyse(parse(fetch(sym, now, a.offline), sym), a.quarters, known.get(sym), sym,
                          now.date() if now else None)
            results.append(res)
            if not a.json:
                print(render(res))
        except FactsError as e:
            print("facts.py: %s" % e, file=sys.stderr)
            code = 1
    if a.json:
        print(json.dumps(results, indent=2))
    if a.metrics and results:
        doc = {}
        if os.path.exists(a.metrics):
            try:
                with open(a.metrics, encoding="utf-8") as fh:
                    doc = json.load(fh)
            except ValueError:
                doc = {}
        rows = {r.get("symbol"): r for r in doc.get("companies", [])}
        for res in results:
            rows[res["symbol"]] = metrics_row(res)
        doc = {"as_of": (now or _dt.datetime.now(_dt.timezone.utc)).date().isoformat(),
               "companies": [rows[k] for k in sorted(rows)]}
        d = os.path.dirname(a.metrics)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(a.metrics, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
            fh.write("\n")
        if not a.json:
            print("Merged %d row(s) into %s." % (len(results), a.metrics))
    return code


if __name__ == "__main__":
    sys.exit(main())
