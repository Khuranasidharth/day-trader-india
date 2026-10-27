---
name: trader-exit
description: >-
  Exit Planner for NSE stocks. Sets your stop and your target before you
  enter, so you know when to get out. Reads the entry from trader-entry (or a
  price you give), puts the stop at the opening-range midpoint by default (or
  the range low, your price, a percent, or a multiple of the ATR), rounds it
  DOWN to the stock's NSE tick size, and sets the target at 2R (or 1R, or
  your price) on the tick too, so the exchange accepts both. Refuses a stop at
  or above the entry, a target at or below it, or a stop too tight to survive
  the spread, and says why. Flat by 15:05 IST, before Upstox squares off.
  Writes trader/plan.json for the Time Machine, the Budget Manager and Price
  Alerts. Long side only. Use when the user says "where's my stop", "set my
  stop and target", "plan the exit", "when do I get out", "stop loss",
  "what's my R", "risk reward", or right after /trader-entry triggers,
  before /trader-timemachine.
argument-hint: "[--stop or-mid|or-low|price:X|pct:X|atr:K] [--target 2R|1R|price:X]"
---

# trader-exit

The Exit Planner decides how a trade ends before it starts. The stop is where
the setup has failed. The target is where you take what you came for. Both
are set BEFORE the entry, written down and handed on, so nobody has to decide
anything in the middle of a fast move. A stop is a plan, not a guarantee: a
gap or a fast market can fill past it. Day trading loses most people money,
and a neat plan does not change that.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan                          # trader/entry.json: midpoint stop, 2R target
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop or-mid --target 1R --write
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop atr:1.5           # needs the session's bars (Yahoo or --offline)
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --symbol RELIANCE --entry 1193.60 --or-high 1192.00 --or-low 1175.30
python3 "${CLAUDE_SKILL_DIR}/exit.py" show                          # the current trader/plan.json
```

Other flags: `--flat-by 15:05`, `--tick 0.05`, `--json`, `--now "2026-10-26
10:00"` (IST), `--entry PRICE` with a waiting entry.json to plan ahead,
`--setup level`, `--offline FILE` (a saved Yahoo chart JSON for an ATR stop).

## What it reads and writes

| file | what |
| --- | --- |
| `trader/entry.json` | the trigger from trader-entry: symbol, entry price, time, bar, opening range |
| `trader/instruments.json` | the stock's tick size (trader-scanner's universe, from Upstox's list) |
| `trader/config.json` | `flat_by` (15:05) and `min_reward_risk` (1.0: a note here, trader-risk enforces it) |
| Yahoo chart API | only for an `atr:K` stop: the session's bars up to the entry bar |
| `trader/plan.json` | with `--write`: entry, stop and its rule, target and its R, risk a share, reward:risk, tick, flat by |

## Stops, targets and ticks

| stop | where it goes |
| --- | --- |
| `or-mid` | the opening-range midpoint (the default for an opening-range breakout) |
| `or-low` | the opening-range low: wider, so fewer shares for the same max loss |
| `price:X` | your price |
| `pct:X` | X percent under the entry |
| `atr:K` | K times the 14-bar ATR under the entry, on the session's bars up to the entry bar |

- **The tick.** NSE accepts only prices on a stock's tick size. The tick comes
  from `trader/instruments.json`, else `--tick`, else NSE's price-band table:
  under ₹250 it is 0.01, to ₹1,000 0.05, to ₹5,000 0.10, to ₹10,000 0.50, to
  ₹20,000 1.00, above that 5.00 (NSE reviews the bands monthly, so the
  instrument list wins when it is there).
- **Rounding.** The stop rounds DOWN to the tick, away from the entry. Risk =
  entry minus stop. Target = entry + R x risk, rounded half up to the tick.
- **Refused, with the reason.** A stop at or above the entry. A target at or
  below it. A risk under 0.05% of the price. An entry.json that has not
  triggered (unless you give `--entry`). A short.
- **Flat by.** 15:05 IST by default (or `flat_by` in the config). Out by then,
  win or lose, no overnight hold. Upstox squares off intraday (product I)
  positions on its own from 3:10 PM for some stocks and 3:25 PM for the rest,
  and charges for doing it. An entry at or after the flat-by time is refused.

## Steps

1. Run it right after `/trader-entry` triggers. Before that, `--entry PRICE`
   plans ahead at the level you expect.
2. Use the default stop for an opening-range breakout unless the user names
   another. A level setup needs one: ask.
3. Run `exit.py plan --write`. Read back the entry, the stop and its rule,
   the target and its rule, the risk a share, reward:risk, the tick and flat by.
4. If it refuses, say the reason and the fix. Never loosen anything on your own.
5. Say once that the stop is a plan, not a guarantee.
6. Hand off to `/trader-timemachine` to replay the plan, then `/trader-budget`
   to size it. Offer `/trader-alerts` for the stop, the target and the
   flat-by time.

## Example: RELIANCE, Monday 26 October 2026

The entry is 1,193.60 at 10:00 AM (the 9:55 bar, bar 8) and the opening
range is 1,175.30 to 1,192.00. RELIANCE's tick is ₹0.10.
`exit.py plan --stop or-mid --target 1R --write`:

```
Exit plan: RELIANCE long, Mon 2026-10-26, opening-range breakout on 5-minute bars
  Entry         ₹1,193.60 at 10:00 AM (bar 8)
  Stop          ₹1,183.60  opening-range midpoint: (₹1,192.00 + ₹1,175.30) / 2 = ₹1183.65, rounded down to the ₹0.10 tick
  Target        ₹1,203.60  1R (one times the risk)
  Risk a share  ₹10.00 (0.84% of the entry)
  Reward:risk   1.0
  Flat by       15:05 IST, win or lose: no overnight hold
  Tick          ₹0.10 (the instrument list)
```

The default 2R target would be 1,213.60. On a 0.05 tick the stop would have
been 1,183.65; on RELIANCE's 0.10 tick it is 1,183.60, or the exchange
rejects it.

## Rules

- The stop and the target are set before the entry, never after.
- Never move a stop further from the entry once the trade is on.
- Plain numbers only: entry, stop, target, risk a share, reward:risk.
- A 1R target is not a prediction that the price gets there.
- Long side only.

## What it never does

It never places an order, never sizes a position, never widens a stop to
make a plan pass, and never calls a stop a guarantee.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`): orders go to the Upstox sandbox. Going live is the user's own decision, in their own config.
- Nothing in this pack sends an order except trader-broker, and only when all of these hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and, for a
  live order, the user sends it themselves (place.py in their own terminal, or the Upstox app). Claude never
  sends a live order.
- No F&O, margin (Upstox's intraday leverage) or short selling unless the config allows it and the user confirms.
- Upstox access tokens live in environment variables, never in the chat.
