---
name: trader-scanner
description: >-
  Chart Scanner for India's NSE. Scans thousands of NSE charts for setups:
  opening-range breakouts, flags, oversold bounces. Builds the list of NSE
  stocks in the EQ series (the ones you can buy intraday) from NSE's own
  equity list, adds each stock's tick size and Upstox instrument key from
  Upstox's public instrument list, runs a pre-market scan of daily closes
  (20-day closing-high breakout, bull flag, reclaimed the 20-day average,
  oversold, oversold bounce) and an intraday opening-range breakout scan on
  5-minute bars from 9:15 IST, then writes trader/watchlist.json for
  trader-news and trader-entry. Free Yahoo data, bar by bar. Use when the
  user says "scan the market", "scan NSE", "find me setups", "what is
  breaking out", "opening range breakouts", "scan for bull flags",
  "oversold stocks", "pre-market scan", "build my watchlist", "what should I
  look at today", or at the start of a trading day before /trader-news.
argument-hint: "[universe | daily | orb] [--at HH:MM]"
---

# trader-scanner

The Chart Scanner is the first step of a day trade. It reads thousands of
free charts and lists the ones that match a rule. That is all it does. A scan
is a list of charts that match a rule, not a list of stocks to buy, and a
setup on a chart is not a prediction. Most people who day trade lose money
(SEBI's own studies of intraday traders say so); the scanner does not change
that. It only saves you from flipping through 2,000 charts by hand.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe                       # -> trader/universe.txt + trader/instruments.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily                          # before 9:15 or after 3:30 -> trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily --symbols RELIANCE,TCS,M&M  # or --watchlist FILE, --limit 200
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb                            # after 9:35 AM IST -> trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --at 10:00                 # cut the clock at 10:00 AM IST
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --watchlist trader/watchlist.json --json
```

Symbols are NSE trading symbols: RELIANCE, M&M, BAJAJ-AUTO. The tool asks
Yahoo for RELIANCE.NS and writes plain symbols back. Quote a symbol with `&`
in the shell (`--symbols 'M&M'`).

Flags: `--min-price 50` and `--min-volume` (daily 500,000 shares, orb 0),
`--or-minutes 15`, `--max-confirm 200` (orb stage 2), `--now "2026-10-26
10:00"` (IST) to pin the clock, `--offline PATH` to read saved Yahoo files,
`--no-write`, `--show N`, `--json`. Exit code 0 when the scan found
something, 1 when it found nothing or could not run (the reason is one plain
line).

## What it reads and writes

| file | what |
| --- | --- |
| `trader/universe.txt` | written by `universe`: one `SYMBOL\|Name` a line, read by `daily` and `orb` |
| `trader/instruments.json` | written by `universe`: per symbol its ISIN, Upstox instrument key (`NSE_EQ\|INE002A01018`), tick size in rupees and whether Upstox squares it off at 3:10 PM (CAS) or 3:25 PM. trader-exit, trader-budget, trader-risk and trader-broker read it |
| `trader/watchlist.json` | written by `daily` and `orb`: `mode`, `as_of`, `universe`, `scanned`, `failed`, `hits[]` |
| `trader/config.json` | read by `orb`: `no_entries_after` (default 14:30) |

## The universe

`universe` reads two public files:

1. NSE's equity list, `EQUITY_L.csv` from archives.nseindia.com. It keeps the
   EQ series only (about 2,360 stocks). BE and BZ are trade-to-trade:
   delivery only, no intraday, so they are out. ETFs are not on this list.
2. Upstox's instrument list, `NSE.json.gz` from assets.upstox.com: the tick
   size (Upstox writes it in paise: 10.0 is a 0.10 rupee tick), the
   instrument key Upstox orders need, and the CAS flag. If it does not load,
   the key is `NSE_EQ|<ISIN>` and the tick comes from NSE's price-band table.

Run it once a week or so, and again when a stock you want is missing.

## The daily scan (before the open or after the close)

Yahoo's spark endpoint returns closes for 20 symbols a request, so about
2,360 symbols take about 120 requests. Liquidity from the spark meta: last
price at least `--min-price` and last session's volume at least
`--min-volume`. During the session the volume is the day's so far, and
today's daily bar is left out until 3:30 PM.

| setup | the rule on closes |
| --- | --- |
| `breakout_20d` | the last close is above every close of the 20 sessions before it |
| `bull_flag` | up more than 10 % over the 10 sessions before the last 5, then the last 5 closes inside a 5 % range |
| `reclaim_ma20` | the close before was under its 20-day average, the last close is above it |
| `oversold` | RSI 14 (Wilder) under 30 |
| `oversold_bounce` | RSI 14 was under 30 yesterday and today closed up |

Hits are listed most traded first (price times volume).

## The opening-range breakout scan (during the session)

The opening range is the first `--or-minutes` (15) of the session: the 9:15,
9:20 and 9:25 five-minute bars. A hit is the first completed 5-minute bar to
CLOSE above the range high, at that bar's close time.

1. Stage 1, every symbol: spark closes of today's 5-minute bars, 20 a
   request. A chart goes on only if a completed bar after the range closed at
   or above the highest close of the range (a necessary condition).
2. Stage 2, each candidate: the v8 chart with real highs and lows. Range
   high = the highest high of the range bars. At most `--max-confirm` (200)
   charts, the most traded first; it prints PARTIAL with the count it skipped.

A chart is usable only when every 5-minute bar from 9:15 to the cutoff is
there: a missing bar is a halt, a stock stuck at its circuit limit, or no
trades. Before 9:35 AM, on a weekend or NSE holiday, after the close, or
after `no_entries_after` (an expired setup) it prints one plain line and
writes nothing.

## Steps

1. Once a week or so: `scan.py universe`.
2. Before the open: `scan.py daily`. Tell the user the counts (fetched,
   liquid, scanned, hits) and the top few by setup.
3. After 9:35 AM IST (10:00 is a common time): `scan.py orb`. Tell the user how
   many usable charts broke their range and when, and that a later hit is
   closer to the price now.
4. The user picks one chart. Hand it on: `/trader-news SYMBOL` (what is moving
   it), then `/trader-entry SYMBOL` (the entry bar by bar). Never pick for them.

## Example: RELIANCE, Monday 26 October 2026

The 10:00 AM scan over 30 NIFTY 50 stocks (real Yahoo charts, saved in
`tests/fixtures/trader-scanner/wall5m-2026-10-26.json.gz`):

```
python3 scan.py orb --offline wall5m-2026-10-26.json.gz --now "2026-10-26 10:00"
Fetched 30 of 30 charts; 30 usable; 27 candidates, 27 confirmed with real highs and lows.
19 of 30 charts closed above their opening-range high by 10:00 AM:
   9:35 AM  TATASTEEL       ₹167.30  range 165.80 to 167.25  +0.03% over
  ...
  10:00 AM  RELIANCE      ₹1,193.60  range 1,175.30 to 1,192.00  +0.13% over
```

A strong morning: most large caps broke out, which says more about the day
than about any one stock. The user picks RELIANCE and Claude hands it to
`/trader-news RELIANCE`, then `/trader-entry RELIANCE`.

## Rules

- Say what was scanned: how many symbols, how many charts came back, how many
  were usable, and the time of the data.
- Say "matched a rule", never "a buy", "a winner" or "a good trade".
- Never print a P&L, a return or a profit figure.
- A hit is stale once the price has moved on. Re-run before acting on it.

## What it never does

It never places, sizes or checks an order, never says which stock to buy,
never calls data real time, and never promises that a setup works.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`): orders go to the Upstox sandbox. Going live is the user's own decision, in their own config.
- Nothing in this pack sends an order except trader-broker, and only when all of these hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and, for a
  live order, the user sends it themselves (place.py in their own terminal, or the Upstox app). Claude never
  sends a live order.
- No F&O, margin (Upstox's intraday leverage) or short selling unless the config allows it and the user confirms.
- Upstox access tokens live in environment variables, never in the chat.
