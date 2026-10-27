import json
import os
import re
import unittest

from _load import ROOT

# the India pack: the eleven folders, trader-deals in place of the US-only Pelosi tracker
SKILLS = ["trader-scanner", "trader-news", "trader-entry", "trader-exit", "trader-timemachine",
          "trader-risk", "trader-budget", "trader-broker", "trader-alerts", "trader-analyst",
          "trader-deals"]
ABOUT = ("11 Claude skills for day trading on India's NSE: scan thousands of charts, track breaking news, time "
         "every entry and exit, and replay every outcome before you risk a rupee.")
# skills on the way to an order carry the safety block
ORDER_PATH = ["trader-scanner", "trader-entry", "trader-exit", "trader-timemachine", "trader-budget",
              "trader-deals", "trader-risk", "trader-broker", "trader-alerts"]
US_ONLY = ["Alpaca", "alpaca", "place_stock_order", "NYSE", "nasdaqtrader", "sec_user_agent", "pdt_guard",
           "_usd\"", "trader-pelosi", "TSLA"]


def frontmatter(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return (m.group(1) if m else ""), text


def every_text_file():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "trader")]
        for f in files:
            if f.endswith((".md", ".py", ".json", ".csv", ".txt", ".xml")) or f == "LICENSE":
                yield os.path.join(base, f)


class Repo(unittest.TestCase):
    def test_eleven_skill_folders_at_the_root(self):
        found = sorted(d for d in os.listdir(ROOT)
                       if os.path.isfile(os.path.join(ROOT, d, "SKILL.md")))
        self.assertEqual(found, sorted(SKILLS))

    def test_frontmatter_name_and_description(self):
        for s in SKILLS:
            fm, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            self.assertIn("name: %s\n" % s, fm + "\n", s)
            self.assertRegex(fm, r"description: ", s)
            self.assertGreater(len(fm), 200, "%s description is too thin" % s)
            self.assertGreater(len(text.splitlines()), 50, s)

    def test_order_path_skills_carry_the_safety_rule(self):
        for s in ORDER_PATH:
            _, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            low = " ".join(text.lower().split())
            self.assertIn("not financial advice", low, s)
            self.assertIn("yes", low, s)

    def test_plugin_manifest_points_at_the_root_skills(self):
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json")) as fh:
            plugin = json.load(fh)
        self.assertEqual(plugin["name"], "day-trader-india")
        self.assertEqual(plugin["skills"], "./")
        self.assertEqual(plugin["description"], ABOUT)
        with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")) as fh:
            market = json.load(fh)
        self.assertEqual(market["plugins"][0]["name"], "day-trader-india")

    def test_readme_names_every_skill(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = " ".join(fh.read().split())
        self.assertIn(ABOUT, readme)
        self.assertIn("## Fine print", readme)
        for s in SKILLS:
            self.assertIn("/" + s, readme, s)

    def test_no_us_only_leftovers(self):
        for path in every_text_file():
            rel = os.path.relpath(path, ROOT)
            if rel.startswith(os.path.join("tests", "")) or rel == "README.md":
                continue  # the tests name what they check for; the README credits the US original
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            for old in US_ONLY:
                self.assertNotIn(old, text, "%s in %s" % (old, rel))

    def test_no_em_dashes_and_no_personal_email(self):
        for path in every_text_file():
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            rel = os.path.relpath(path, ROOT)
            if not rel.startswith(os.path.join("tests", "fixtures")):  # fixtures are real data, kept as published
                self.assertNotIn(chr(0x2014), text, rel)
            self.assertNotIn("jakeschincariol" + "@" + "gmail.com", text, rel)

    def test_every_tool_runs_on_python_3_8(self):
        for s in SKILLS:
            folder = os.path.join(ROOT, s)
            for f in os.listdir(folder):
                if not f.endswith(".py"):
                    continue
                with open(os.path.join(folder, f), encoding="utf-8") as fh:
                    src = fh.read()
                for bad in ("import zoneinfo", "from zoneinfo", ".removeprefix(", ".removesuffix("):
                    self.assertNotIn(bad, src, "%s/%s" % (s, f))
                self.assertNotRegex(src, r"(?m)^\s+match \w+.*:$", "%s/%s" % (s, f))
                for gen in ("list[", "dict[", "tuple["):
                    self.assertNotRegex(src, r"(?<![\w.\"'])%s" % re.escape(gen), "%s/%s" % (s, f))

    def test_day_trading_limits_ship_in_the_example_config(self):
        with open(os.path.join(ROOT, "trader-budget", "config.example.json")) as fh:
            cfg = json.load(fh)
        for k in ("max_loss_per_trade_inr", "max_daily_loss_inr", "max_trades_per_day", "min_reward_risk",
                  "require_stop", "no_entries_before", "no_entries_after", "flat_by", "charges", "product"):
            self.assertIn(k, cfg, k)
        self.assertIs(cfg["require_stop"], True)
        self.assertEqual(cfg["product"], "I")
        self.assertEqual(cfg["broker"], "upstox")
        self.assertIs(cfg.get("allow_short", False), False)
        self.assertIs(cfg.get("allow_margin", False), False)
        self.assertLess(cfg["flat_by"], "15:10")    # before Upstox's own square-off

    def test_paper_trading_is_the_default(self):
        with open(os.path.join(ROOT, "trader-budget", "config.example.json")) as fh:
            cfg = json.load(fh)
        self.assertIs(cfg["paper"], True)
        self.assertIs(cfg.get("allow_options", False), False)

    def test_the_nse_calendar_is_the_same_everywhere(self):
        lists = {}
        for s in SKILLS:
            for f in os.listdir(os.path.join(ROOT, s)):
                if f.endswith(".py"):
                    with open(os.path.join(ROOT, s, f), encoding="utf-8") as fh:
                        m = re.search(r"NSE_HOLIDAYS = \{.*?\n\}", fh.read(), re.S)
                    if m:
                        lists["%s/%s" % (s, f)] = m.group(0)
        self.assertGreaterEqual(len(lists), 5)
        self.assertEqual(len(set(lists.values())), 1, sorted(lists))
        one = next(iter(lists.values()))
        for d in ("2026-10-20", "2026-11-10", "2026-01-26", "2026-12-25"):
            self.assertIn(d, one)


if __name__ == "__main__":
    unittest.main()
