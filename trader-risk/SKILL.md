---
name: trader-risk
description: >-
  Risk Manager for NSE intraday trades. Checks every trade against your
  limits and stops anything over them, before it can reach Upstox. For a day
  trade: a stop is required, the loss at the stop plus the round trip's
  charges must fit your max loss per trade, reward:risk must meet your
  minimum (and the same after charges is shown), the day's total risk must
  fit your daily loss limit, no more than your trades per day, and no new
  entries outside your window (09:30 to 14:30 IST) or on an NSE holiday. It
  also checks the order itself: the Upstox instrument key is this stock's,
  every price is on the stock's tick, the qty is whole shares, the product
  is I or D, the stock is in the EQ series (not trade-to-trade), no F&O,
  margin or short selling. Getting out is never blocked by a day limit.
  Prints PASS or BLOCK with the reason and records the verdicts so
  trader-broker only shows an order that passed. Use when the user says
  "check my order", "is this safe", "risk check", "does this break my
  rules", "can I take this trade", "how much have I risked today", or before
  /trader-broker, always.
argument-hint: "[path to orders.json]"
---

# trader-risk

The Risk Manager is the gate between a proposal and the broker. Every order
written by trader-budget or trader-broker's flatten passes through it. A
BLOCK is final for that order: it does not go to the user for a yes, and it
does not go to Upstox. Most people who day trade lose money. These limits
keep each loss and each day's losses small. They do not make a trade win.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/check.py"                           # trader/ files; writes trader/state/risk.json
python3 "${CLAUDE_SKILL_DIR}/check.py" --json
python3 "${CLAUDE_SKILL_DIR}/check.py" --no-write                # look without recording
python3 "${CLAUDE_SKILL_DIR}/check.py" --now "2026-10-26 10:00"  # pin the clock (IST)
```

## What it reads and writes

| file | what |
| --- | --- |
| `trader/orders.json` | the proposed orders (trader-budget, or trader-broker's flatten) |
| `trader/config.json` | the limits and the charge rates (trader-budget ships `config.example.json`) |
| `trader/instruments.json` | each stock's Upstox key and tick, and the EQ-series list (trader-scanner) |
| `trader/portfolio.json` | cash and holdings; if missing, a fresh account funded with the budget |
| `trader/prices.json` | a fresh price raises the entry it measures risk from; also values holdings |
| `trader/state/broker.json` | what was placed today: duplicates, trades per day, daily loss |
| `trader/state/risk.json` | the verdicts it writes, with a fingerprint of each exact order |

## Entries and exits

An **entry** opens or adds to a position. An **exit** only reduces what you
already hold. Getting out must always be possible, so an exit is checked for
format, asset and short sales only; every other rule turns into a warning.

## The checks

| check | blocks when |
| --- | --- |
| format | no symbol, side or instrument_token; qty not whole shares; product not I or D; order_type not MARKET / LIMIT / SL / SL-M or missing its price or trigger; validity not DAY / IOC; a bracket that is not a LIMIT entry with a stop_loss and a target; a price off the stock's tick; an instrument_token that is not this symbol's |
| asset | F&O (an NSE_FO token or an option-looking symbol) while `allow_options` is false; anything that is not an NSE equity; a stock not in the EQ series (BE / BZ are trade-to-trade, no intraday) |
| short | a sell of more than you hold (`allow_short` false) |
| blocked | (entries) the symbol is on the `blocked` list |
| size | (entries) under `min_order_inr` or over `max_order_inr` |
| position | (entries) the stock would be over `max_position_pct` of the account |
| cash | (entries) the buy would leave less than the cash buffer, or need margin |
| stop | (entries) no stop while `require_stop` is true; a stop on the wrong side |
| loss | (entries) qty x (entry minus stop) + the estimated charges over `max_loss_per_trade_inr` |
| reward:risk | (entries) (target minus entry) / (entry minus stop) under `min_reward_risk` |
| daily loss | (entries) the max losses of today's entries, plus this one, over `max_daily_loss_inr` |
| trades | (entries) `max_trades_per_day` entries already placed today |
| window | (entries) before `no_entries_before` or after `no_entries_after`, or the market is closed |
| duplicate | (entries) the same symbol and side twice in one batch, or already placed today |
| daily limit | (entries) `max_orders_per_day` orders already placed today |

How the numbers work:

- **The entry it measures from**: the limit price for a limit order (every
  bracket is one). For a market order, the HIGHER of the plan's entry and a
  fresh price from `trader/prices.json` (under 15 minutes old).
- **The charges** use the same table as trader-budget (`charges` in the
  config). When a win at the target after charges is worth less than a loss
  at the stop, it warns with the net reward:risk.
- **Daily loss** counts the full max loss of every entry placed today.
- **The window** is IST, worked out in the tool, never from the computer's
  clock zone. The NSE session is 9:15 to 3:30 PM; NSE's 2026 holidays are
  closed (for 2027, add NSE's circular when it is out).

Warnings do not block, but say them to the user: a LIVE account, a price
too old to use, no instrument list, delivery (product D) on a day trade,
the net reward:risk after charges.

## Steps

1. If the price may have moved since the plan, refresh it first
   (trader-alerts: `alerts.py quote RELIANCE --write`).
2. Run `check.py`. Exit code 0 means every order passed, 1 means at least one
   was blocked.
3. Tell the user the result order by order: the max loss with charges,
   reward:risk (and net), and how much of today's limits it uses. For a
   BLOCK, give the reason and the fix. Never change a limit yourself.
4. If the order changes in any way, run the check again. trader-broker
   matches each order to its verdict by fingerprint.

## Example: RELIANCE, Monday 26 October 2026

The bracket from trader-budget at 10:00 AM on a fresh ₹1,00,000 paper account:

```
PASS  #1 buy RELIANCE 43 shares, entry
          entry 1193.60 (the limit price), stop 1183.60, target 1203.60: risk 10.00 a share
          max loss ₹495.17 with charges (limit ₹500), reward:risk 1.00 (min 1)
          today before this: 0 of 3 trades, ₹0 of ₹1,500 daily loss
        ~ after charges a win at the target is about ₹364.59 and a loss at the stop about ₹495.17: reward:risk 0.74 net. ...
```

One more share and it is blocked (44 x 10.00 = ₹440 plus ₹65.58 = ₹505.58,
over ₹500). A stop of 1,183.65 is blocked too: it is not on RELIANCE's ₹0.10
tick, and the exchange would reject it. At 9:20 it is blocked by the window.
The 3:05 PM sell that closes the position passes: it is an exit.

## Rules

- A PASS only means the order is allowed to be shown to the user. It is not a yes.
- Every number comes from the config, the order, the instrument list, the portfolio, the prices or the broker log.
- Free Yahoo prices are unofficial and can lag; Upstox's price is the one that fills.

## What it never does

It never places an order, never edits an order to make it pass, never
loosens a limit, never blocks a sell that only gets the user out, and never
treats a PASS as the user's yes.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`): orders go to the Upstox sandbox. Going live is the user's own decision, in their own config.
- Nothing in this pack sends an order except trader-broker, and only when all of these hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and, for a
  live order, the user sends it themselves (place.py in their own terminal, or the Upstox app). Claude never
  sends a live order.
- No F&O, margin (Upstox's intraday leverage) or short selling unless the config allows it and the user confirms.
- Upstox access tokens live in environment variables, never in the chat.
