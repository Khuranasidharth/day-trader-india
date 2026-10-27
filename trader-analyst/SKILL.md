---
name: trader-analyst
description: >-
  The Earnings Analyst for NSE companies. Reads a company's reported numbers
  (Yahoo Finance's fundamentals for the NSE listing, consolidated) and sums
  up what changed: revenue, gross, operating and net margins, net profit and
  diluted EPS, quarter by quarter on India's April-to-March fiscal year (Q1
  FY27 = April to June 2026), each against the same quarter a year earlier,
  plus four fiscal years, in rupee crore. Says plainly when a quarter is
  missing or out of date and links the exchange filing, which is the
  authority. Reads a results press release or a con-call transcript when you
  paste one. Use when the user says "how were Reliance's results", "analyse
  the quarterly results", "what changed this quarter", "is revenue growing",
  "compare margins", "sum up the con call", "when are results", or before
  trading a stock around its results.
argument-hint: "[symbols]"
---

# trader-analyst

Quarterly results move Indian stocks more than anything else on the
calendar, and the press release puts the best number first. This skill lines
the reported numbers up quarter by quarter and says plainly what changed.
For a day trader it answers two questions before a trade: what did the last
results say, and is the next board meeting for results inside this trade?

Tool in this folder (standard library Python, no keys):

```bash
python3 "${CLAUDE_SKILL_DIR}/facts.py" RELIANCE
python3 "${CLAUDE_SKILL_DIR}/facts.py" RELIANCE TCS INFY --metrics trader/metrics.json
python3 "${CLAUDE_SKILL_DIR}/facts.py" TCS --quarters 8 --json
```

## What it reads and writes

- Reads Yahoo Finance's fundamentals time series for SYMBOL.NS: quarterly
  and annual revenue, gross profit, operating income, net income and diluted
  EPS (about five quarters and four fiscal years). Free and unofficial.
- Company names come from `trader/instruments.json` (trader-scanner).
- Writes `trader/metrics.json` with `--metrics`: one row per company (the
  latest quarter, margins, growth, TTM when four quarters in a row exist,
  and the quarters Yahoo is missing). `metrics.example.json` in this folder
  is a real run on 2026-10-26.
- The filings themselves are on NSE's financial results page
  (`nseindia.com/companies-listing/corporate-filings-financial-results?symbol=X`)
  and on BSE. Both block scripts: the tool links the page, the user opens it,
  and you read what they paste or save. Con-call transcripts and investor
  presentations are on the company's investor relations page.

## The rules

- **Filed numbers win.** The table is Yahoo's copy of what the company
  reported. When Yahoo is behind (it can be weeks after a results board
  meeting) or skips a quarter, say so and read the filing. The tool marks a
  missing quarter ("Yahoo is missing Q2 FY26 (2025-09-30)") and a stale one
  ("newer results are out"). Never fill a gap with an estimate.
- **Compare like with like.** Growth is against the same quarter a year
  earlier, only when Yahoo has both. Many Indian businesses are seasonal
  (festive quarters, monsoon), so quarter-on-quarter is a note, not the story.
- **Indian fiscal years.** FY26 is April 2025 to March 2026. Q1 FY27 ends
  30 June 2026. Say the quarter both ways when it helps ("Q1 FY27, April to
  June").
- **Amounts in crore.** 1 crore = 10 million rupees; the tool groups Indian
  style (₹3,09,468 cr). EPS is in rupees.
- **Flag one-offs.** When net profit is above operating profit, other income
  or exceptional gains are inside it. Banks and NBFCs have no gross margin:
  blank, not zero. An EPS change of 40% or more is often a bonus issue or a
  split that Yahoo did not adjust: check before calling it a fall.
- **Standalone vs consolidated.** Yahoo shows consolidated. Headlines often
  quote standalone. Say which one a number is.

## Steps

1. Run it for the companies in question (or the symbols on
   `trader/watchlist.json`).
2. If the table is stale or has a gap that matters, give the user the
   filing link and ask them to open it (or paste the results).
3. Write the summary: one line on the quarter (revenue, profit, EPS,
   growth), one on margins, one on anything unusual (a one-off, a gap, a
   stale quarter, a bonus or split), and the links. Plain words, real
   numbers, no adjectives the numbers do not support.
4. If the next results board meeting falls inside the planned trade, say it
   before `/trader-exit` sets the stop. The date is in NSE's corporate
   announcements (board meeting intimation) and in `/trader-news`
   headlines; say where it came from. A day trade flat by 3:05 is not
   exposed to results announced after the close; anything held overnight is.

## Example: RELIANCE, 26 October 2026

`facts.py RELIANCE`: Q1 FY27 (quarter ended 2026-06-30) revenue ₹3,09,468 cr,
+27.0% against Q1 FY26; net profit ₹20,946 cr, -22.4%; diluted EPS ₹15.48,
-22.4%; operating margin 10.5%, +0.5 points on Q4 FY26. FY26 revenue
₹10,57,219 cr (+9.6%), net profit ₹80,775 cr (+16.0%). Yahoo is missing Q2
FY26, so there is no TTM. Q2 FY27 (July to September) results are due around
now: the summary ends "Yahoo does not have Q2 FY27 yet. If the board has
met, read the filing: [link]."

## What it never does

- Never says a stock is cheap, expensive, a buy or a sell. It reports what
  the company reported.
- Never invents a number the data does not have, or estimates a quarter.
- Never tries to get past NSE's or BSE's block on scripts.

## Safety

Education and tooling, not financial advice. This skill only reads numbers.
Nothing sends an order except `/trader-broker`, after `/trader-risk` passes
and the user types an explicit yes for that order.
