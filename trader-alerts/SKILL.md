---
name: trader-alerts
description: >-
  Price Alerts and the NSE clock. Rings when a price, a stop or the opening
  bell hits. Turns the trade plan into three alerts in one go (the stop, the
  target and "flat by 3:05" before Upstox squares off), plus above / below /
  stop / target levels, percent moves from the previous close, any time of
  day, and the NSE opening bell at 9:15 IST, each ringing once so you are not
  spammed. Knows NSE hours (9:15 to 3:30 PM IST) and NSE's 2026 holidays,
  fetches free delayed quotes for NSE symbols from Yahoo one at a time, and
  writes trader/prices.json for sizing and the risk check. On paper it is
  what watches the stop and the target. Use when the user says "alert me
  when", "tell me if RELIANCE hits", "watch my stop", "watch my trade",
  "remind me to close by 3", "is the market open", "is today a holiday", "when
  does NSE open", "get me a price", or right after /trader-exit writes a plan.
argument-hint: "[symbol] [price]"
---

# trader-alerts

Price Alerts watches the numbers so the user does not have to stare at a
chart. An alert is information, never an order: when a stop alert rings,
nothing is sold by this skill. With a live bracket the GTT's stop-loss and
target legs sit at Upstox and do the work; on paper the sandbox holds only
the entry, so these alerts are what watch the stop and the target, and they
tell the user what happened and when it is time to be flat.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/alerts.py" clock                          # NSE open or closed, next open
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --from-plan                # stop, target, flat-by from trader/plan.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --opening-bell
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol RELIANCE --stop 1183.60
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol RELIANCE --target 1203.60
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --at 15:05 --label "flat by 3:05"
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol INFY --pct 3
python3 "${CLAUDE_SKILL_DIR}/alerts.py" check                          # exit 0 = something rang
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote RELIANCE --write         # -> trader/prices.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote --holdings --write       # portfolio + plan symbols
python3 "${CLAUDE_SKILL_DIR}/alerts.py" list
python3 "${CLAUDE_SKILL_DIR}/alerts.py" reset reliance-plan-stop
```

`--now "2026-10-26 15:05"` pins the clock (IST); `--offline DIR` reads saved
quote files (`yahoo-<SYMBOL>.json`) instead of the network.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/plan.json` | the trade from trader-exit, for `add --from-plan` |
| `trader/alerts.json` | the rules (`alerts.example.json` in this folder) |
| `trader/state/alerts.json` | which rules rang and when, so each rings once |
| `trader/prices.json` | the latest quotes, merged in, for trader-budget and trader-risk |
| `trader/portfolio.json` | the symbols held, for `quote --holdings` |

## Rule types

| type | rings when | rings again |
| --- | --- | --- |
| `above` / `target` | price at or above `price` | after `reset`, or on its own if `"rearm": true` and the price fell back |
| `below` / `stop` | price at or below `price` | same |
| `pct_move` | moved `pct` percent from the previous close (or `ref`), optional `direction` up or down | once per day at most |
| `time` | the IST clock passed `at` ("15:05") on a trading day | once per trading day |
| `opening_bell` | the NSE is open (9:15 IST) | once per trading day |

A rule with `"date"` is watched on that IST date only; `--from-plan` rules
carry the plan's date, so yesterday's stop never rings today.

## Quotes

- Yahoo's chart endpoint for `RELIANCE.NS`, one request per symbol, half a
  second apart; on a 429 it waits and tries once more, then tries `query1`.
- Free quotes are unofficial and delayed. They are fine for alerts and for
  checking a size, not for timing an order. Upstox's price is the one that
  fills. Each price in `trader/prices.json` keeps its quote time, and
  trader-risk only uses one under 15 minutes old.
- If Yahoo is down, read the price from Upstox (the app, or the read-only
  upstox-mcp plugin) and write it into `trader/prices.json` as
  `{"as_of": "...Z", "prices": {"RELIANCE": 1201.80}}`.

## The NSE clock

The equity session runs 9:15 AM to 3:30 PM IST, Monday to Friday (a pre-open
auction runs 9:00 to 9:08). India keeps UTC+5:30 all year: no daylight
saving. Closed on these 2026 trading holidays, from NSE's December 2025
circular: Jan 15 (Maharashtra municipal elections), Jan 26, Mar 3 (Holi),
Mar 26 (Ram Navami), Mar 31 (Mahavir Jayanti), Apr 3 (Good Friday), Apr 14
(Ambedkar Jayanti), May 1 (Maharashtra Day), May 28 (Bakri Id), Jun 26
(Muharram), Sep 14 (Ganesh Chaturthi), Oct 2 (Gandhi Jayanti), Oct 20
(Dussehra), Nov 10 (Diwali Balipratipada), Nov 24 (Guru Nanak Jayanti),
Dec 25. The Diwali Muhurat session (Sunday 8 November 2026) is a special
one-hour session announced by circular; the tools treat that Sunday as
closed. For 2027 the clock says the holiday list is unknown until NSE's
circular is added.

## Steps

1. Right after trader-exit writes the plan, run `add --from-plan`. Confirm
   the three alerts back to the user: the stop, the target and the flat-by time.
2. Run `check` while the trade is open: every few minutes from a Claude
   scheduled task or `/loop`. A check reads the latest delayed quote; a price
   can pass a level between two checks.
3. Tell the user what rang in one line each. A stop or target alert on a
   live bracket means the GTT leg has probably filled: check the position in
   Upstox and record the fill with trader-broker. On paper, it is the signal
   that the paper trade is over: record it with `ticket.py fill`. "Flat by"
   means close anything still open: cancel the GTT, trader-broker `flatten`,
   then trader-risk, then the user's yes. Never act for them.

## Example: RELIANCE, Monday 26 October 2026

Entry 1,193.60 at 10:00 AM, stop 1,183.60, target 1,203.60, flat by 15:05.
`add --from-plan` writes `reliance-plan-stop`, `reliance-plan-target` and
`reliance-flat-by` for that day. A `check` at noon reads 1,201.80, between
the stop and the target: nothing rings. At 3:06 PM:

```
NSE OPEN (2026-10-26 15:06 IST, regular session).
ALERT Flat by close: it is 15:06 IST (set for 15:05), the market closes at 15:30. If RELIANCE is still
open, close it: trader-broker flatten --symbol RELIANCE builds the sell ticket, then trader-risk and your yes.
```

It rings once.

## Rules

- An alert is a fact about a price or the clock. Say it as a fact.
- Never present a quote as live. Free quotes are delayed and unofficial.
- Confirm every new rule back to the user: symbol, type, level, day.

## What it never does

It never places, cancels or changes an order, never claims a quote is
live, and never predicts where a price is going.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`): orders go to the Upstox sandbox. Going live is the user's own decision, in their own config.
- Nothing in this pack sends an order except trader-broker, and only when all of these hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and, for a
  live order, the user sends it themselves (place.py in their own terminal, or the Upstox app). Claude never
  sends a live order.
- No F&O, margin (Upstox's intraday leverage) or short selling unless the config allows it and the user confirms.
- Upstox access tokens live in environment variables, never in the chat.
