---
name: trader-budget
description: >-
  Budget Manager for NSE intraday trades, in rupees. Sizes every position to
  your budget and your max loss per trade, with Indian charges counted:
  brokerage, STT, NSE transaction charges, SEBI fees, stamp duty and GST.
  Reads the trade plan from trader-exit (entry, stop, target), finds the
  whole shares that fit inside four limits (max loss per trade including
  charges, position cap, max order, cash after your buffer), says which
  limit decided it, and writes ONE bracket order (a limit entry, stop-loss
  and target, product I, with the stock's Upstox instrument key) to
  trader/orders.json. A stop too far away for your max loss is a plain
  refusal, not a smaller order. Nothing is placed. Use when the user says
  "how many shares", "size this trade", "how much should I buy", "I have
  ₹1 lakh", "I only want to risk ₹500 a trade", "what are the charges", "set
  my rules", "keep 10% in cash", or after /trader-exit writes a plan.
argument-hint: "[budget in rupees]"
---

# trader-budget

The Budget Manager turns a plan ("buy RELIANCE at 1,193.60, stop 1,183.60")
into an exact order ("buy 43 shares"), inside rules the user sets once. The
stop decides the size: the further away the stop, the fewer shares. The
charges come off too: on a small intraday trade in India they are a real
share of what you can lose. It writes a proposal only. trader-risk checks it
and trader-broker asks the user yes or no. Day trading loses most people
money. Sizing to a max loss keeps each loss small; it does not make a trade win.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py"                        # trader/plan.json + trader/config.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --write                # write trader/orders.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --limit 1194.00 --write   # a different limit price
python3 "${CLAUDE_SKILL_DIR}/size.py" --weights RELIANCE=30,TCS=25 --config split.json --prices trader/prices.json
```

`--now "2026-10-26 10:00"` pins the clock (IST). A plan for another day is
refused: make a new one with trader-exit.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/config.json` | the rules (start from `config.example.json` in this folder) |
| `trader/plan.json` | the trade: entry, stop, target, tick, setup, flat-by time (trader-exit writes it) |
| `trader/instruments.json` | the stock's Upstox instrument key and tick (trader-scanner's `scan.py universe`) |
| `trader/prices.json` | optional: a fresh price above the limit is noted (trader-alerts writes it) |
| `trader/portfolio.json` | optional: its cash caps the size (trader-broker keeps it) |
| `trader/orders.json` | the one proposed bracket order it writes with `--write` |

## Step 1: set the rules once

If `trader/config.json` does not exist, copy `config.example.json` into
`trader/config.json` and ask the user for each value in plain words:

- **budget**: how many rupees this is for. Only money they can afford to lose.
- **cash_buffer_pct**: how much always stays in cash (default 10).
- **max_loss_per_trade_inr**: the most one trade may lose at the stop,
  charges included (default ₹500).
- **max_position_pct**, **max_order_inr**, **min_order_inr**: the biggest
  position (75% of the budget), the biggest order (₹75,000), the smallest (₹500).
- The day limits trader-risk enforces: **max_daily_loss_inr** (₹1,500),
  **max_trades_per_day** (3), **min_reward_risk** (1.0), **require_stop**
  (true), **no_entries_before** / **no_entries_after** ("09:30" / "14:30")
  and **flat_by** ("15:05"), all IST.
- **charges**: their Upstox plan's brokerage (flat ₹20 an order by default;
  if the plan says "x% or ₹20, whichever is lower", set `brokerage_pct` to x)
  and the statutory rates (STT 0.025% on the intraday sell side, NSE 0.00297%,
  SEBI 0.0001%, stamp duty 0.003% on the buy side, GST 18%; read in October
  2026). Their contract notes are the truth: adjust from them.
- **product**: "I" (intraday). **blocked**: symbols they never want to trade.
- Keep **paper** true until they have watched it work on the Upstox sandbox.

## Step 2: size the trade

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py" --write
```

Whole shares only. The size is the largest number of shares that fits all
four limits:

| limit | shares |
| --- | --- |
| max loss | shares x (entry minus stop) + the round trip's charges <= `max_loss_per_trade_inr` |
| position cap | budget x `max_position_pct` / entry |
| max order | `max_order_inr` / entry |
| cash | (budget minus the cash buffer) / entry, never more than the cash in `trader/portfolio.json` |

The entry is a LIMIT at the plan's entry (or `--limit`). Upstox fills a GTT
leg as a limit, so the order never pays more than that. If the price has run
above it since the plan, the order may not fill: the tool says so, and that
is fine; a chased entry is a bigger risk at the same stop.

It refuses, and writes no order, when: the size is zero shares, the order is
under the minimum, reward:risk is under `min_reward_risk`, the stop is not
below the entry, the target is not above it, the plan is for another day,
the symbol is blocked, the plan is a short, or there is no Upstox instrument
key (run `scan.py universe` once). Say the reason in one line.

## Step 3: show the user

Show the four limits, which one decided the size, the shares, the rupees,
the max loss at the stop with the charges itemised, and what a win at the
target leaves after charges. Say plainly that a stop is an order, not a
promise. Then hand over to `/trader-risk`.

## Example: RELIANCE, Monday 26 October 2026

Entry 1,193.60 at 10:00 AM, stop 1,183.60 (the opening-range midpoint on the
₹0.10 tick), target 1,203.60 (1R). Risk ₹10.00 a share. The example config:
₹1,00,000 budget, 10% cash buffer, ₹500 max loss.

| limit | the math | shares |
| --- | --- | --- |
| max loss | 43 x ₹10.00 = ₹430, plus ₹65.17 charges = ₹495.17 <= ₹500 | **43 (decides it)** |
| position cap | 75% of ₹1,00,000 = ₹75,000 / 1,193.60 | 62 |
| max order | ₹75,000 / 1,193.60 | 62 |
| cash | ₹1,00,000 minus ₹10,000 = ₹90,000 / 1,193.60 | 75 |

43 shares = ₹51,324.80. The charges at the stop: brokerage ₹40, STT ₹12.72,
NSE ₹3.04, SEBI ₹0.10, stamp duty ₹1.54, GST ₹7.76. At the target a win is
₹430 minus ₹65.41 = ₹364.59. So a 1R plan is 0.74 to 1 after charges: say
that. It writes:

```json
{"symbol": "RELIANCE", "instrument_token": "NSE_EQ|INE002A01018", "side": "buy", "qty": 43,
 "product": "I", "order_type": "LIMIT", "price": 1193.6, "validity": "DAY",
 "order_class": "bracket", "stop_loss": 1183.6, "target": 1203.6, "why": "...", "plan": {...}}
```

`why` and `plan` are notes for trader-risk and trader-broker; they are never
sent to Upstox.

## Weights mode (kept from v1)

`--weights RELIANCE=30,TCS=25` or `--targets FILE` (`targets.example.json`)
splits a budget across a list by weight, whole shares, as delivery (product
D) market buys: the cash buffer comes off the top, weights are renormalised
to 100, anything over `max_position_pct` is capped and shared out, slices
under the minimum order are dropped. It needs prices (`--prices
trader/prices.json`). These buys have no stop: trader-risk blocks them while
`require_stop` is true. Use a separate config (`--config`) for a long-term split.

## Rules

- Proposals only. This skill never sends anything to a broker.
- Never size money the user has not said is for this. Ask for the budget and the max loss.
- Every number comes from the config, the plan, the instrument list or the prices.
- No projections: never say what a trade will make.

## What it never does

It never places, approves or schedules an order, never raises a limit on its
own, never shrinks a stop to fit more shares, and never sizes F&O, margin
(intraday leverage) or short positions.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`): orders go to the Upstox sandbox. Going live is the user's own decision, in their own config.
- Nothing in this pack sends an order except trader-broker, and only when all of these hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and, for a
  live order, the user sends it themselves (place.py in their own terminal, or the Upstox app). Claude never
  sends a live order.
- No F&O, margin (Upstox's intraday leverage) or short selling unless the config allows it and the user confirms.
- Upstox access tokens live in environment variables, never in the chat.
