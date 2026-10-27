---
name: trader-deals
description: >-
  The Bulk and Block Deals Tracker for NSE. Reads the two files NSE
  publishes after every session: bulk deals (a client's trades in one stock
  adding up to more than 0.5% of its listed shares that day) and block deals
  (large trades in the exchange's block-deal windows). Says who bought and
  sold what, in rupee crore, nets each client's buys against its sells (most
  bulk deals are trading firms on both sides), flags deals in the stocks you
  watch or hold, alerts once per new deal, and keeps 90 days of history. Use
  when the user says "bulk deals", "block deals", "who bought RELIANCE
  today", "big investor deals", "did any fund buy", "what are FIIs or funds
  buying", "smart money", "track deals", or "run the deals tracker".
argument-hint: "[today | new | history] [--symbol X] [--client NAME]"
---

# trader-deals

Every evening NSE lists the day's bulk deals and block deals by name: the
client, the side, the quantity and the price. This skill reads those two
files, notices the moment a new deal appears, and turns them into a short,
honest summary.

It is public, and it is after the fact. The trade is done before anyone can
read it. And most bulk deals are not what they look like: high-frequency and
market-making firms (in the example below, the biggest names on the list)
buy and sell the same stock the same day and end flat. The net per client is
what actually changed hands. Say that every time.

Tool in this folder (standard library Python, no keys):

```bash
python3 "${CLAUDE_SKILL_DIR}/deals.py" today                       # the latest day, biggest first
python3 "${CLAUDE_SKILL_DIR}/deals.py" today --min-crore 10
python3 "${CLAUDE_SKILL_DIR}/deals.py" today --symbol RELIANCE
python3 "${CLAUDE_SKILL_DIR}/deals.py" today --client "morgan stanley"
python3 "${CLAUDE_SKILL_DIR}/deals.py" new                         # only deals not shown before (exit 1 = none)
python3 "${CLAUDE_SKILL_DIR}/deals.py" history --symbol APOLLO     # from the state file, 90 days
```

## What it reads and writes

- Reads `https://archives.nseindia.com/content/equities/bulk.csv` and
  `.../block.csv` (Date, Symbol, Security Name, Client Name, Buy/Sell,
  Quantity Traded, Trade Price). Both hold the latest trading day only; a
  day with none says `NO RECORDS`.
- Writes `trader/state/deals.json`: every deal it has seen, kept 90 days,
  so `new` alerts once per deal and `history` works. Because NSE's files
  hold one day, run it each evening (a scheduled task) to keep it complete.
- Reads `trader/watchlist.json`, `trader/plan.json` and
  `trader/portfolio.json` to flag deals in your stocks.

## The rules

- **Quote the file.** Every row comes from NSE's file: date, client,
  side, quantity, price. Value = quantity x price, in crore.
- **Net, not gross.** A client that bought and sold the same stock the same
  day is marked "both sides"; give its net. Do not call a both-sides
  trading firm "buying".
- **Who it is.** A fund house, an FPI, a promoter entity or an insurer
  buying is different from a proprietary trading firm. Say what kind of
  client it looks like only when the name makes it plain, and say when it
  does not.
- **Bulk vs block.** Bulk deals happen in the normal market; block deals in
  the separate block windows, often a pre-arranged sale by a promoter or a
  big holder. A block sale can mean shares about to be absorbed, or a holder
  leaving; the file does not say which.
- **No signal.** A deal is a reason to look at a chart, not a setup.

## Steps

1. `deals.py today` (or `--symbol` for one stock). Lead with deals in the
   user's stocks (flagged), then the largest by value.
2. For each stock that matters: who bought, who sold, the net, the price
   against today's close (`/trader-alerts` `quote`), and whether the clients
   look like trading firms or long-term holders.
3. Each evening after about 6 PM IST: `deals.py new`, on a schedule. Exit 1
   means nothing new.
4. If the user wants to act on a deal, it goes the long way:
   `/trader-scanner` and `/trader-entry` decide if there is a trade tomorrow;
   then shares only, sized by `/trader-budget`, checked by `/trader-risk`,
   placed by `/trader-broker` only after their yes.

## Example: Monday 26 October 2026

`deals.py today --min-crore 50`: 17 bulk deals of ₹50 crore or more, and no
block deals ("NO RECORDS"). The largest by value is SSWL (Steel Strips
Wheels), ₹590.68 crore across 8 deals, where ALPHAGREP SECURITIES bought and
sold 16,57,804 shares each way (net zero) and MICROCURVES TRADING did the
same. In APOLLO, JUMP TRADING bought and sold 26,41,960 shares (net zero)
and QE SECURITIES was net -50,442. 8 of those clients were on both sides of
the same stock. The honest summary: "Big numbers, mostly trading firms flat
by the close. No fund built a position in your stocks today."

## What it never does

- Never says or implies a deal is inside information, or that copying a
  client beats the market. No return claims.
- Never presents a gross both-sides deal as a purchase.
- Never places an order.

## Safety

- Education and tooling, not financial advice. Nothing in this pack is a recommendation to buy or sell anything.
- Paper trading by default (`"paper": true`): orders go to the Upstox sandbox. Going live is the user's own decision, in their own config.
- Nothing in this pack sends an order except trader-broker, and only when all of these hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and, for a
  live order, the user sends it themselves (place.py in their own terminal, or the Upstox app). Claude never
  sends a live order.
- No F&O, margin (Upstox's intraday leverage) or short selling unless the config allows it and the user confirms.
- Bulk and block deals are PUBLIC records of trades already done. This skill reads them; it has no inside
  information, and it says so.
