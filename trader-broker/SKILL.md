---
name: trader-broker
description: >-
  Order Executor for Upstox. Sends approved orders to Upstox, paper trading
  (the Upstox sandbox) by default, never without your yes. Shows each order
  as a plain ticket (a bracket shows its stop-loss, target and the max loss
  at the stop with charges) plus the exact Upstox request: a GTT with three
  legs (ENTRY, TARGET, STOPLOSS, product I) for a live bracket, the entry leg
  on the sandbox for paper. Records your yes word for word. Paper orders go
  out with place.py; a LIVE order is always sent by you, in your own terminal
  (place.py asks you to type the order back) or in the Upstox app, because
  Upstox needs a registered static IP for API orders and real money needs a
  person. Builds the sell ticket that closes a day trade by 3:05 PM, records
  fills, and logs each trade's max loss so trader-risk can hold the daily
  limit. Covers setting up Upstox's sandbox and API tokens (environment
  variables, never in chat). Use when the user says "place the order", "buy
  it", "execute", "send it to Upstox", "close my position", "flatten", "get
  me out", "connect Upstox", "set up paper trading", or after /trader-risk passes.
argument-hint: "[order number]"
---

# trader-broker

The Order Executor is the only skill in this pack that can lead to a real
order, so it is the strictest. An order reaches Upstox only after these
gates, every time, for every order, and `place.py` checks each one itself:

1. **trader-risk passed this exact order today** (matched by fingerprint).
2. **The user typed an explicit yes for this one order** in the chat
   (`ticket.py approve` records it word for word).
3. **Paper or live matches the config.** Paper (`"paper": true`) goes to the
   Upstox sandbox: no money moves. Live needs `"paper": false`, set by the
   user, AND the user running `place.py --live` in their own terminal and
   typing the order back ("BUY 43 RELIANCE"). With no person at a keyboard it
   refuses. Or the user places it in the Upstox app from the ticket.

Claude may run `place.py` for a paper order after the user's yes. Claude
never sends a live order: it shows the user the command or the app steps.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/ticket.py" show                     # every ticket, READY or not
python3 "${CLAUDE_SKILL_DIR}/ticket.py" approve --index 1 --reply "yes"
python3 "${CLAUDE_SKILL_DIR}/place.py" --index 1 --dry-run       # the request, nothing sent
python3 "${CLAUDE_SKILL_DIR}/place.py" --index 1                 # paper: the Upstox sandbox
python3 "${CLAUDE_SKILL_DIR}/place.py" --index 1 --live          # LIVE: the user runs this, never Claude
python3 "${CLAUDE_SKILL_DIR}/ticket.py" result --index 1 --status placed --broker-id GTT-C26...   # placed in the app
python3 "${CLAUDE_SKILL_DIR}/ticket.py" fill --symbol RELIANCE --side buy --qty 43 --price 1193.60
python3 "${CLAUDE_SKILL_DIR}/ticket.py" flatten --symbol RELIANCE --qty 43
python3 "${CLAUDE_SKILL_DIR}/place.py" cancel-gtt --id GTT-C26... --live   # the user runs this
python3 "${CLAUDE_SKILL_DIR}/ticket.py" log
```

`ticket.py` never talks to a broker. `place.py` sends one order, never
retries, and records placed (with Upstox's order id) or failed (with
Upstox's message) in `trader/state/broker.json`. `--now "2026-10-26 10:00"`
pins the clock (IST).

## What it reads and writes

| file | what |
| --- | --- |
| `trader/orders.json` | the proposed orders (trader-budget writes it; `flatten` replaces it) |
| `trader/state/risk.json` | trader-risk's verdicts; only a PASS from today is READY |
| `trader/state/broker.json` | every yes, no, placed, failed and filled, with each entry's max loss |
| `trader/portfolio.json` | cash and shares, updated by `fill` |
| `trader/instruments.json` | the Upstox instrument key for `flatten` |
| `trader/plan.json` | the flat-by time for `flatten` |

## Setup: Upstox

1. **Paper first: the sandbox.** In Upstox's developer console
   (account.upstox.com/developer/apps), open Sandbox, make the one sandbox
   app Upstox allows, and Generate a token (it lasts 30 days). The user
   exports it in their own terminal or shell profile:
   `export UPSTOX_SANDBOX_ACCESS_TOKEN=...`. The sandbox takes plain orders
   only (no GTT), so on paper `place.py` sends the entry leg as a limit
   order and trader-alerts watches the stop and the target.
2. **Live, later, and only if the user decides to.** An Upstox API app and a
   daily access token (`UPSTOX_ACCESS_TOKEN`; Upstox makes you log in again
   every day). Since April 2026 Upstox, following SEBI's retail algo rules,
   accepts API orders only from a static IP registered on the API app. Most
   home connections have no static IP: then place live orders in the Upstox
   app from the ticket (`ticket.py show` prints the steps), and use the API
   for paper only.
3. **Tokens never go in the chat.** Never ask for them, never read a shell
   profile or env file back into the conversation, and if the user pastes a
   token anyway, tell them to delete that message and generate a new one.
4. **Read-only account access** (optional): Upstox's own Claude plugin
   (`/plugin marketplace add upstox/upstox-plugin-marketplace`, then
   `/plugin install upstox-mcp@upstox-plugins-official`) gives Claude
   read-only holdings, positions, orders and funds. Use it to check
   positions and fills. It cannot place orders.
5. In Claude Code, keep `place.py` on ask: never put
   `Bash(python3 *place.py*)` in an allow list.

**Brackets on Upstox.** A live bracket is a GTT order of type MULTIPLE with
three legs: ENTRY (IMMEDIATE, a limit at the plan's entry), TARGET and
STOPLOSS (IMMEDIATE: armed once the entry fills, and they cancel each
other). GTT legs fill as limit orders. A plain market order carries
`"market_protection": -1`, Upstox's automatic price protection: Upstox no
longer takes bare market orders from the API.

## Steps: the entry

1. `ticket.py show`. Only READY tickets go to the user. A ticket that is NOT
   READY or BLOCKED goes back to `/trader-risk`.
2. Show ONE ticket and ask: "Place this order? Reply yes or no." One order
   per question. Never offer "yes to all".
3. Run `ticket.py approve --index N --reply "<the user's reply, word for word>"`.
   If it prints "Not recorded", the reply was not an explicit yes for this
   order (for example "sure", "haan", "yes to all", or a yes that names a
   different stock or amount). Ask again. Never turn a reply into a yes yourself.
4. Paper: run `place.py --index N` and tell the user the result and the
   sandbox order id. Live: show the user the command (`place.py --index N
   --live`, to run in their own terminal) or the app steps from the ticket,
   and wait. When they have placed it in the app, record it with
   `ticket.py result --index N --status placed --broker-id ID`.
5. A failed order is not retried without a new check and a new yes.

## Steps: while it is open, and out by 3:05

- trader-alerts watches the stop, the target and the flat-by time
  (`alerts.py add --from-plan`). On a live bracket, the GTT's legs do the
  stopping.
- When the stop-loss or the target fills, record it:
  `ticket.py fill --symbol RELIANCE --side sell --qty 43 --price 1183.60`.
- By `flat_by` (15:05 IST), anything still open gets closed:
  1. Check the position in Upstox (the app, or upstox-mcp read-only).
  2. Cancel the bracket's GTT FIRST (Upstox app: Orders > GTT, or the user
     runs `place.py cancel-gtt --id GTT-... --live`). Left open, its target
     or stop-loss leg could sell again after you are flat, and that sell
     would be a short.
  3. `ticket.py flatten --symbol RELIANCE --qty 43` writes a market sell
     (product I, with price protection) to `trader/orders.json`.
  4. `/trader-risk`. A sell that only closes what the user holds is never
     blocked by the daily limits or the entry window.
  5. `ticket.py show`, the user's yes for that one order, then `place.py`
     (paper) or the user (live).
- Upstox squares off intraday positions on its own from 3:10 PM (CAS stocks)
  or 3:25 PM (the rest) and charges for it. Flat by 3:05 beats both.

## Example: RELIANCE, Monday 26 October 2026

```
ORDER 1 of 1, PAPER (Upstox sandbox), Upstox
  BUY 43 RELIANCE, limit 1193.60, intraday, good for today
  stop-loss 1183.60
  target 1203.60
  max loss about ₹495.17 if the stop fills at 1183.60, charges included (it can fill worse in a fast market)
  READY: trader-risk PASS, waiting for your yes
  place.py sends the Upstox sandbox (paper, no money): it takes plain orders only, so this is the ENTRY
  leg; trader-alerts watches the stop and the target on paper, POST https://api-sandbox.upstox.com/v3/order/place
  Reply "yes" to place this one order, or "no" to skip it.
```

The user replies "yes". Claude records it, runs `place.py --index 1`, and
reports the sandbox's order id. Live, the same ticket shows the GTT request
to `https://api.upstox.com/v3/order/gtt/place` and the app steps: RELIANCE >
Buy > GTT, Intraday, qty 43, entry 1193.60, target 1203.60, stop-loss 1183.60.

## What it never does

- Never sends an order without all the gates, and never two orders on one yes.
- Never sends a live order itself, and never from a scheduled or background task.
- Never asks for, reads, stores or repeats an access token.
- Never switches `"paper"` to false. The user does that themselves.
- Never places F&O, MTF or cover orders, and never cancels everything at once.
- Never promises a fill price.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`): orders go to the Upstox sandbox. Going live is the user's own decision, in their own config.
- Nothing in this pack sends an order except trader-broker, and only when all of these hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and, for a
  live order, the user sends it themselves (place.py in their own terminal, or the Upstox app). Claude never
  sends a live order.
- No F&O, margin (Upstox's intraday leverage) or short selling unless the config allows it and the user confirms.
- Upstox access tokens live in environment variables, never in the chat.
