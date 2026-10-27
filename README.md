# The Day Trader skill, India edition

11 Claude skills for day trading on India's NSE: scan thousands of charts, track breaking news, time every entry and exit, and replay every outcome before you risk a rupee.

An India port of [Jake Schincariol's day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(MIT). Same method, same tools, rebuilt for the NSE: India time (UTC+5:30, no
daylight saving), the 9:15 to 3:30 PM session and NSE's 2026 holidays,
NSE symbols (RELIANCE, M&M, BAJAJ-AUTO), tick sizes, rupees and crore,
intraday charges (STT, stamp duty, GST and the rest), Indian fiscal quarters,
and Upstox as the broker.

Free, MIT, no API key for the data. The tools are plain Python that read free
public data: Yahoo Finance charts for SYMBOL.NS, NSE's equity list and its
bulk and block deal files, Upstox's public instrument list, and Google News
(India edition).

And no trade goes through until you say yes. Paper trading on the Upstox
sandbox is the default, and a live order is always sent by you, never by
Claude.

## Install

Paste this into Claude Code:

```
https://github.com/Khuranasidharth/day-trader-india

install skill
```

Or as a plugin, in Claude Code:

```
/plugin marketplace add Khuranasidharth/day-trader-india
/plugin install day-trader-india@day-trader-india
```

Claude Code namespaces plugin skills, so installed as a plugin they show up as
`/day-trader-india:trader-scanner` and so on. Copy the folders instead if you
want plain `/trader-scanner`:

```bash
git clone https://github.com/Khuranasidharth/day-trader-india.git
cp -r day-trader-india/trader-* ~/.claude/skills/
```

Project-local instead of global: copy the same folders into your repo's
`.claude/skills/`. The tools need Python 3.8 or newer. Nothing to pip install.

## The eleven

| command | job | what it does |
| --- | --- | --- |
| `/trader-scanner` | Chart Scanner | Scans about 2,360 NSE stocks (the EQ series) for setups: opening-range breakouts, flags, oversold bounces. |
| `/trader-news` | News Monitor | Tracks Google News (India) headlines on every stock you watch, with the day's move and the NSE filings link. |
| `/trader-entry` | Entry Timer | Watches a setup bar by bar from 9:15 IST and tells you the moment to get in. |
| `/trader-exit` | Exit Planner | Sets your stop and target on the stock's tick before you enter; flat by 3:05 PM. |
| `/trader-timemachine` | Time Machine | Replays 10,000 simulated sessions plus every past time the setup fired. |
| `/trader-risk` | Risk Manager | Checks every order against your limits, charges included, and stops anything over them. |
| `/trader-budget` | Budget Manager | Sizes every position to your rupee budget and max loss, with Indian charges counted. |
| `/trader-broker` | Order Executor | Sends approved orders to Upstox: the sandbox on paper; live orders you send yourself. |
| `/trader-alerts` | Price Alerts | Rings on a price, your stop, your target, the 3:05 flat-by and the 9:15 bell. |
| `/trader-analyst` | Earnings Analyst | Reads quarterly results on India's April-to-March year, in crore, and says what changed. |
| `/trader-deals` | Deals Tracker | Reads NSE's bulk and block deals and nets each client's buys against its sells. |

The US pack's Pelosi tracker (US Congress trade disclosures) has no Indian
equivalent; `/trader-deals` takes its place.

## How to use it

Everything lands in a `trader/` folder in your project, and each skill reads
what the last one wrote:

```
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker   (one trade)
alerts: stop, target, flat by 3:05                                            (while it is open)
news / analyst / deals                                                        (on a schedule)
```

An example, real data: RELIANCE, Monday 26 October 2026.

1. **`/trader-scanner`** (`scan.py universe` once, then `scan.py orb` at
   10:00 AM IST): of 30 NIFTY 50 charts, 19 had closed above their 15-minute
   opening range (9:15 to 9:30). RELIANCE is one: range 1,175.30 to 1,192.00,
   the 9:55 candle closed at 1,193.60.
2. **`/trader-news`**: the day's RELIANCE headlines in IST: a broker's target
   and the Jio Platforms IPO listing on Wednesday. A day trade is out by
   3:05, so it is not exposed to an overnight gap.
3. **`/trader-entry`** watched it bar by bar: waiting at 9:58, triggered at
   10:00 AM, 1,193.60.
4. **`/trader-exit`** set the plan: stop at the range's midpoint, 1,183.65,
   rounded down to RELIANCE's ₹0.10 tick: 1,183.60, so ₹10.00 a share at
   risk; target 1R, 1,203.60; flat by 15:05.
5. **`/trader-timemachine`** replayed the rest of the day 10,000 times from
   RELIANCE's own 5-minute bars over 58 sessions (seed 19): target first
   22.6 %, stop first 29.9 %, still open at 3:05 47.5 %. The same rule on
   those 58 real sessions fired 26 times: 13 target, 10 stop, 3 neither. Its
   verdict: leans toward the stop.
6. **`/trader-budget`** with ₹1,00,000 and a ₹500 max loss per trade: 43
   shares (₹51,324.80). At the stop that is ₹430 plus about ₹65.17 in
   charges = ₹495.17. A win at the target is ₹364.59 after charges, so a 1R
   plan is 0.74 to 1 net. It writes one bracket order.
7. **`/trader-risk`** checks it: the max loss with charges, the daily loss
   limit, trades per day, reward to risk, the entry window (09:30 to 14:30),
   the tick, the instrument key, position size and cash. PASS or BLOCK, with
   the reason.
8. **`/trader-broker`** shows the ticket. You type yes for that exact order.
   On paper Claude sends it to the Upstox sandbox. Live, you send it
   yourself: `place.py --live` in your own terminal (it asks you to type the
   order back), or the Upstox app, from the ticket's steps.
9. **`/trader-alerts`** rings on the stop, the target and at 3:05 PM to
   flatten whatever is still open (cancel the GTT first).

## The tools

All standard-library Python.

```bash
python3 trader-scanner/scan.py universe                              # NSE's EQ list + Upstox ticks and keys
python3 trader-scanner/scan.py daily                                 # setups from daily closes
python3 trader-scanner/scan.py orb --at 10:00                        # opening-range breakouts so far
python3 trader-news/news.py --tickers RELIANCE --hours 12            # headlines, the move, the filings link
python3 trader-entry/entry.py check RELIANCE --setup orb             # waiting / triggered / expired
python3 trader-entry/entry.py watch RELIANCE --every 30              # bar by bar until it triggers
python3 trader-exit/exit.py plan --stop or-mid --target 1R --write   # -> trader/plan.json
python3 trader-timemachine/timemachine.py run --until 15:05 --write  # 10,000 replays + the history
python3 trader-budget/size.py --write                                # -> trader/orders.json
python3 trader-risk/check.py                                         # PASS / BLOCK per order
python3 trader-broker/ticket.py show                                 # the tickets, READY or not
python3 trader-broker/place.py --index 1                             # paper: the Upstox sandbox
python3 trader-alerts/alerts.py add --from-plan                      # stop, target, flat by 3:05
python3 trader-alerts/alerts.py check                                # rings what hit, once
python3 trader-analyst/facts.py RELIANCE                             # quarters, growth, EPS, in crore
python3 trader-deals/deals.py today                                  # bulk and block deals, netted
```

```bash
python3 -m unittest discover -s tests -v
```

The tests run offline, on fixtures saved from real data on 26 October 2026:
RELIANCE's 5-minute bars for 60 days, 30 NIFTY 50 charts, NSE's equity list
and Upstox's instrument list (cut to those stocks), Google News headlines,
Yahoo fundamentals for RELIANCE, TCS and HDFC Bank, and NSE's bulk deals
file. They reproduce every number in the example above.

## Fine print

**Not financial advice.** This is software that reads public data and does
arithmetic. It does not know your situation and it cannot see the future.
SEBI's own study of individual intraday traders found most of them lost
money. You can lose money. Decide for yourself, and talk to a SEBI-registered
investment adviser if you need advice.

**No trade goes through until you say yes, and Claude never sends a live
order.** Only `/trader-broker` can lead to an order, and only after
`/trader-risk` passes that exact order and you type yes for it in the chat.
On paper, `place.py` sends it to the Upstox sandbox. Live, you send it:
`place.py --live` refuses unless your config says `"paper": false` and you
type the order back at a terminal, or you place it in the Upstox app. No
F&O, margin (intraday leverage) or short selling unless you turn them on.

**Upstox's rules.** Since April 2026 Upstox, following SEBI's retail algo
framework, accepts API orders only from a static IP registered on your API
app, allows one API app per user, and no longer takes bare market orders
(market orders carry price protection). Live access tokens last one day;
the sandbox token 30 days. Tokens live in environment variables
(`UPSTOX_SANDBOX_ACCESS_TOKEN`, `UPSTOX_ACCESS_TOKEN`), never in the chat.
If you have no static IP, use the API for paper and the Upstox app for live.

**Square-off.** Upstox squares off intraday (MIS, product I) positions
itself from 3:10 PM (CAS stocks) or 3:25 PM (the rest) and charges for it.
The pack plans to be flat by 3:05.

**Charges are an estimate.** Brokerage (₹20 an order by default: set your
plan's), STT 0.025% on the intraday sell side, NSE transaction charges
0.00297%, SEBI fees 0.0001%, stamp duty 0.003% on the buy side, GST 18% on
brokerage and fees; read in October 2026. Your contract note is exact.

**The Time Machine is a simulation, not a prediction.** It is built from the
stock's own last 60 days of 5-minute bars (9:15 to 3:15: Yahoo leaves the
last 15 minutes of past NSE sessions empty). Results days, circuits and
news can do things those days never did.

**A stop is a plan, not a guarantee.** In a fast market, at a circuit limit
or across a gap, a stop can fill well past its price, or not at all.

**The data is free and unofficial.** Yahoo's endpoints can lag, change or
rate-limit you; its fundamentals skip quarters. NSE blocks scripts from its
website, so filings and announcements are linked for you to open. Check
anything that matters against Upstox and the exchange.

**Holidays.** NSE's 2026 holidays are built in. For 2027, add NSE's circular
(usually out in December) to the `NSE_HOLIDAYS` lists.

**Taxes.** Intraday equity gains are taxed as speculative business income
in India. Nothing here is tax advice.

## Files

```
trader-scanner/     SKILL.md, scan.py
trader-news/        SKILL.md, news.py
trader-entry/       SKILL.md, entry.py
trader-exit/        SKILL.md, exit.py
trader-timemachine/ SKILL.md, timemachine.py
trader-risk/        SKILL.md, check.py
trader-budget/      SKILL.md, size.py, config.example.json, targets.example.json
trader-broker/      SKILL.md, ticket.py, place.py
trader-alerts/      SKILL.md, alerts.py, alerts.example.json
trader-analyst/     SKILL.md, facts.py, metrics.example.json
trader-deals/       SKILL.md, deals.py
tests/              unittest suite + offline fixtures
```

## Contributing

Issues and pull requests are welcome. The things that go stale first:

- **NSE holidays.** Each December NSE publishes the next year's trading
  holidays. Add them to every `NSE_HOLIDAYS` list (the tests check that the
  lists match) and to `CALENDAR_YEARS`.
- **Charges.** STT, stamp duty, exchange and SEBI rates change with budgets
  and circulars: `CHARGES` in `trader-budget/size.py` and `trader-risk/check.py`,
  and `config.example.json`.
- **Upstox's API.** Endpoints, the sandbox's coverage and the square-off
  times: `trader-broker/ticket.py`, `place.py` and the broker skill.
- **Other brokers.** Zerodha, Dhan, Angel One and others would need their own
  request builder in `ticket.py` and sender in `place.py`; the rest of the
  pack is broker-neutral.

Run `python3 -m unittest discover -s tests` before a pull request. The tests
run offline.

## License

MIT. The original US pack is by [Jake Schincariol](https://opusjake.ai)
([day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)); the
India port is by [Sidharth Khurana](https://github.com/Khuranasidharth).
See [LICENSE](LICENSE).
