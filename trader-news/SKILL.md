---
name: trader-news
description: >-
  News Monitor for NSE stocks. Tracks breaking news on every stock you watch
  and flags what moves it: Google News (India edition) headlines per company,
  how far each stock is from yesterday's close, and a link to the company's
  NSE corporate announcements (results, board meetings, insider trades,
  pledges). Shows only what is new since the last check, newest first, in
  India time (IST), tags each item (earnings, analyst, deal, capital, halt,
  regulatory, macro...) and never repeats one. Use when the user says "any
  news on RELIANCE", "why is this stock moving", "what's the news on my
  watchlist", "morning briefing", "pre-market news", "monitor the news",
  "did anything break", "results date", or after /trader-scanner finds setups.
argument-hint: "[symbols]"
---

# trader-news

A chart can look perfect and still be about to gap on a results day, a
circuit, a SEBI order or a promoter pledge. Before a setup becomes a trade,
this skill reads the headlines for every stock on the watchlist and tells you
only what is new. It also prints how far each stock has moved today, so a
headline and a move sit side by side.

Tool in this folder (standard library Python, no keys):

```bash
python3 "${CLAUDE_SKILL_DIR}/news.py"                         # watchlist + plan + portfolio
python3 "${CLAUDE_SKILL_DIR}/news.py" --tickers RELIANCE 'M&M' --hours 12
python3 "${CLAUDE_SKILL_DIR}/news.py" --tickers IRFC --name 'IRFC="Indian Railway Finance"'
python3 "${CLAUDE_SKILL_DIR}/news.py" --json
```

## What it reads and writes

| file / feed | what |
| --- | --- |
| `--tickers`, else `trader/watchlist.json` | the scanner's hits (trader-scanner) |
| `trader/plan.json` | the trade you are planning (trader-exit) |
| `trader/portfolio.json` | what you hold (trader-broker records fills there) |
| `trader/instruments.json` | company names to search for (trader-scanner's universe) |
| Google News RSS, India edition | `news.google.com/rss/search?q="Reliance Industries" OR "NSE:RELIANCE" when:2d&hl=en-IN&gl=IN&ceid=IN:en` |
| Yahoo Finance chart endpoint | the last price against yesterday's close (unofficial, can lag) |
| `trader/state/news.json` | what has been shown (kept 30 days) |

Exchange filings live on NSE's corporate announcements page, which blocks
scripts. The tool prints the link for each symbol; open it in a browser when
a headline mentions results, a board meeting, a deal or a SEBI order.

## The rules

- **Headlines are leads, not facts.** Before telling the user something
  happened, open the story or the filing and read it. Quote the source and
  link it. Never summarise a paywalled story you could not read: say so.
- **Filings beat headlines.** If an exchange filing and a headline disagree,
  the filing is what the company told NSE.
- **Say what it touches.** Every item lists the symbols it touches and its
  tags: earnings, analyst, legal, deal, capital (dividend, bonus, split, QIP,
  OFS, IPO), people, risk (pledge, default, insolvency), halt (circuit,
  ASM / GSM), regulatory (SEBI, RBI, CCI, USFDA), macro (RBI policy, CPI,
  Budget, FII flows, crude, the rupee). Items with earnings, halt, risk,
  legal or regulatory tags are marked `!`.
- **MOVING** marks a stock 3 % or more from yesterday's close (`--move-pct`).
  A move with no headline is worth saying out loud too.
- **No predictions.** Report what was published and how far the price is from
  yesterday's close. Never say what the stock will do next.

## Steps

1. Run the check: `python3 "${CLAUDE_SKILL_DIR}/news.py"`. Exit code 1 means
   nothing new. `--all` shows items already seen, `--json` gives everything
   machine readable, `--dry-run` leaves the state alone.
2. Read the items that matter: every `!` item and every MOVING symbol first.
3. Write a short brief, per symbol: what happened, the source and link, the
   move, and one line on why it matters to the setup (for example "results
   are on Thursday: an overnight gap can jump past any stop, but a day trade
   is out by 3:05").
4. If a story changes the picture, say so before `/trader-entry` and
   `/trader-exit`: results inside the trade, a circuit, an ASM listing, an
   offering. Never act on a headline alone.

During the session: `/loop 15m /trader-news`, or a scheduled task each
morning before 9:15.

## Example: RELIANCE, Monday 26 October 2026

The check that evening (Google News India, 45 headlines over two days) leads
with "Religare sets INR 1,696.00 target for Reliance stock" (ad-hoc-news.de,
7:56 PM, tagged analyst) and several Jio Platforms IPO stories (tagged
capital: the listing is on Wednesday). The price line reads `RELIANCE
1,201.80 +0.99% vs yesterday's close 1,190.00`. The brief: "Jio Platforms
lists on Wednesday; that is news about a subsidiary, and it can move
RELIANCE at the open. No exchange filing checked yet: here is the link."
When a symbol has no news, say so rather than padding the brief.

## What it never does

- Never invents or embellishes a story, a quote or a number.
- Never trades on news, and never tells the user to buy or sell because of a
  headline.
- Never hammers a server: one request per feed per symbol, a pause between.
- Never tries to get past NSE's block on scripts: it links the page instead.

## Safety

Education and tooling, not financial advice. This skill only reads and
reports. Nothing sends an order except `/trader-broker`, after
`/trader-risk` passes and the user types an explicit yes for that order.
