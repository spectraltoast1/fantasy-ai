# Fantasy Football Assistant - Product Roadmap

**Last reviewed:** 2026-05-15

---

## V1 - Working Dashboard
**Target: NFL kickoff, September 2026. Redraft only.**

**Steps:**
- Pull 2024 historical data from nfl_data_py and explore it - identify which metrics correlate with fantasy output and are worth tracking
- Build dashboard panels against historical data - get views working and useful before worrying about live data
- Wire live fetchers (Sleeper, nfl_data_py, Odds API, FantasyPros, LeagueLogs) and confirm they're pulling correctly
- Add time-series snapshot infrastructure for trend views
- Connect live data to dashboard panels

**Stretch goal: AI advisor basics if time allows before September.**

---

## V2 - AI Advisor
**Target: In-season 2026, added incrementally as the season progresses.**

**Steps:**
- Run strategy interview to produce structured strategy document
- Wire advisor to data layer with pre-filtered context
- Build in-season feedback loop to track recommendation outcomes

---

## V3+ - Expanded Scope
**To be defined when V2 is complete. Candidates include:**

- Multiple league format support (dynasty, salary cap)
- Monte Carlo simulations (lineup, trade impact, playoff odds)
- More sophisticated strategy document sourcing
- Additional data sources if they become affordable