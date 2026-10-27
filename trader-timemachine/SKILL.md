---
name: trader-timemachine
description: >-
  Time Machine for NSE day trades. Replays every possible outcome of a trade
  before you risk a rupee: 10,000 simulated sessions plus every past time the
  setup fired. Takes the plan from trader-exit (entry, stop, target), rebuilds
  the rest of the day 10,000 times from the stock's own 5-minute bars over the
  last 60 days, and re-runs the same rule on every past session. Prints the
  odds of target first, stop first, or neither by your flat-by time, where
  the price sits then, the average R, the history, and one honest verdict,
  then hands off to /trader-budget. Use when the user says "run the time
  machine", "replay this trade", "what are the odds", "simulate this trade",
  "monte carlo", "backtest this setup", "how often does this hit the target",
  "is this a coin flip", or after /trader-exit writes a plan, before
  /trader-budget.
argument-hint: "[path to plan.json, or SYMBOL]"
---

# trader-timemachine

The Time Machine sits between the plan and the money. trader-exit has set
the entry, the stop and the target. Before anything is sized or sent, this
skill asks one question: if today plays out like the stock's own last 60
days, how often does this plan hit the target first, the stop first, or
neither? It answers with 10,000 replays and with the real record of the same
rule on every past session. It is a simulation built from the stock's own
recent bars, not a prediction. Day trading loses most people money, and a
good-looking replay does not change that.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --until 15:05            # trader/plan.json, 10,000 replays, seed 19
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --until 15:05 --write    # also save trader/timemachine.json
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --json
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --symbol RELIANCE --date 2026-10-26 \
    --entry 1193.60 --stop 1183.60 --target 1203.60 --entry-time "10:00 AM" --tick 0.10
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" chart --from           # ASCII fan chart of the saved run
```

Other flags: `--replays N`, `--seed N` (default 19), `--window N` (default 2
bars), `--offline FILE` (a saved Yahoo chart JSON, `.json` or `.json.gz`),
`--now "2026-10-26 10:00"` (IST) to pin the clock.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/plan.json` | the plan from trader-exit: symbol, date, entry, entry_time / entry_bar, stop, stop_rule, target, tick, opening range |
| Yahoo chart API | one request: 60 days of 5-minute bars for SYMBOL.NS, free and unofficial, can lag |
| `trader/timemachine.json` | with `--write`: `{plan, mc, history}` plus the verdict |

## How it works

1. **The pool.** It keeps only FULL sessions before the plan's date: the 72
   five-minute bars from 9:15 to 3:15 PM IST. The NSE trades until 3:30, but
   Yahoo leaves the 3:15 to 3:30 bars of past NSE sessions empty, so a replay
   ends at 3:15 at the latest. That costs nothing here: the plan is flat by
   3:05. Every bar becomes four ratios to the bar before it.
2. **One replay.** Start at the entry price. For each bar left in the day,
   pick a past bar from the same time of day (plus or minus 2 bars) at
   random, and scale it to the current price. Bar by bar, it checks the stop
   first, then the target. A bar that touches both counts as the stop.
3. **10,000 replays** give four odds. Target first. Stop first. Neither (the
   trade was still open at `--until`). Green (target first or above the entry
   at `--until`). R is +1 at a 1R target, -1 at the stop, and otherwise the
   distance from the entry at `--until` divided by the risk.
4. **The history.** The plan's own rule (the same opening range, stop rule,
   target R and tick) runs again on every one of those past sessions. That is
   what really happened, not a simulation.
5. **The verdict** is one line from the numbers. It looks only at the replays
   that hit one side and asks how often the target came first, against the
   share that breaks even at the target's R: 1 in (1 + R), so 50 % at 1R and
   33 % at 2R. Under 5 points: "Close to a coin flip" (1R) or "Close to
   break-even". 5 to 15: "Leans toward". 15 or more: "Strongly toward".
6. **Charges are not in the odds.** On a small Indian intraday trade they are
   a real share of the risk (trader-budget shows them): a coin flip before
   charges loses money after them.

Use `--until 15:05` (your flat-by time) so "neither" means still open at the
moment you would get out. Same plan, same data, same `--seed`: the same
numbers. Say the seed with every result.

## Steps

1. Make sure `trader/plan.json` is today's plan from `/trader-exit`.
2. Run `timemachine.py run --until 15:05 --write`.
3. Tell the user, in this order: the four odds, the median and the 5 to 95
   range of the price at 3:05, the average R, the history line, then the
   verdict line and any line under it exactly as printed. Say the seed.
4. If the verdict is a coin flip or leans toward the stop, say so plainly. If
   the history and the replays disagree, say that too.
5. Say once that this is built from the last 60 days and is not a prediction.
   Results, news and circuits can do things those 60 days never did.
6. If the user still wants the trade, hand off to `/trader-budget`.

## Example: RELIANCE, Monday 26 October 2026

Entry 1,193.60 at 10:00 AM (bar 8), stop 1,183.60, target 1,203.60 (1R, risk
10.00 a share). `run --until 15:05` over the 58 full sessions from 30 July:

```
  target first   22.6 %
  stop first     29.9 %
  neither        47.5 %   still open at 3:05 PM
  green          45.3 %   target first, or above the entry at 3:05 PM
  Price at 3:05 PM: median 1192.61, 90 % of replays between 1178.15 and 1207.66.
  Average R: -0.084
History: the same rule on each of those 58 real sessions fired 26 times: 13 target, 10 stop, 3 neither. Average R +0.075.
Leans toward the stop: target first 22.6 % vs stop first 29.9 %.
47.5 % of the replays hit neither by 3:05 PM; the price at 3:05 PM decides those.
```

The replays lean toward the stop; the real history was slightly better than
even. Neither is an edge, and the charges come on top. That is what the
user should hear before `/trader-budget` sizes anything.

## Rules

- Every number comes from the run. Never round a coin flip up into an edge.
- Repeat the verdict lines as printed. Never judge a 2R plan by target first
  vs stop first alone: the verdict already weighs the target's R.
- Simulated odds are not predictions and not promises. Say it once, plainly.
- Always say the seed. One plan per run.

## What it never does

It never places an order, never sizes a position, never changes the plan,
and never calls a result a sure thing. It never prints a P&L or a profit.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`): orders go to the Upstox sandbox. Going live is the user's own decision, in their own config.
- Nothing in this pack sends an order except trader-broker, and only when all of these hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and, for a
  live order, the user sends it themselves (place.py in their own terminal, or the Upstox app). Claude never
  sends a live order.
- No F&O, margin (Upstox's intraday leverage) or short selling unless the config allows it and the user confirms.
- Upstox access tokens live in environment variables, never in the chat.
