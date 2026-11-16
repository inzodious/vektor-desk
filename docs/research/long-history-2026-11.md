# Long-history strategy study (2026-11)

Baseline: the whole US stock market, bought and held (10.96% a year, 1990-01 to 2026-09).
Data: Ken French portfolios and factors (1926-07 to 2026-09, daily and monthly) and FRED rates, all public. Code: `research/long_history/` (`run.sh` fetches, runs and writes JSON).
Every return is after fund fees and 0.05% trading cost per side. Leveraged funds include daily reset, borrowing at T-bill + 1.5%, and fund fees.

## How ideas were judged

| Step | Rule |
|---|---|
| Design period | 1927 to 1989 |
| Test period (out of sample) | 1990 to 2026-09 |
| Recent check | 2010 to 2026-09 |
| Luck | Paired block bootstrap (12-month blocks), plus decade-by-decade consistency |
| Tries counted | 106 variants across three rounds |
| Taxes | Lot-level simulation for the finalists: 28% short-term, 19% long-term, losses carried forward |

## Results (points a year vs the baseline)

| Idea | 1927-89 | 1990-2026 | 2010-26 | Worst drop (baseline -50%) | Verdict |
|---|---|---|---|---|---|
| Sector momentum: top 3 of 12 industries by 12-1 month return, monthly | +3.2 | +2.6 | +1.6 | -39% | Promising: ahead in all 10 decades; paper first |
| Same idea, 54 variants (12/30/49 industries, 6/9/12 months, top 2 to 12) | +1.4 to +7.6 | -0.5 to +6.2 | -1.8 to +3.4 | -39% to -61% | Robust family: 52 of 54 ahead 1990-2026, all 54 ahead since 2000, 42 of 54 since 2010 |
| Sector momentum after taxes, taxable account | | +2.2 | | | Still ahead after tax |
| 2x S&P with a 10-month trend exit to T-bills | +2.1 | +2.5 | -0.7 | -36% (1929 era: -76%) | Lumpy: all the gain came from dodging 2000-02 and the 1950s; no |
| 3x S&P with trend exit | +3.6 | +5.3 | +2.5 | -51% (1929 era: -93%) | Too fragile; no |
| Constant 1.5x leverage | +0.9 | +2.0 | +4.5 | -68% | Just more risk, lower Sharpe; no |
| Profitability (quality) tilt | +0.6* | +0.9 | +0.4 | -43% | Within noise; calmer |
| Small value | +4.8 | +1.0 | -3.1 | -62% | Faded |
| Stock momentum (top 30%) | +4.3 | +1.0 | -0.7 | -49% | Faded after costs |
| Value (top fifth) | +3.3 | +1.5 | -0.6 | -59% | Faded |
| Multi-factor (small value, momentum, profitability) | +4.2* | +1.2 | -0.9 | -50% | Faded |
| High dividend (SCHD-like) | +1.0 | -0.4 | -1.1 | -63% | No; also taxed every year |
| Trend to cash, 1x (10-month or 12-month) | -0.4 | -1.2 | -5.0 | -18% | Cuts drawdowns, costs return; no |
| Volatility targeting | -0.2 | -0.8 | -1.8 | -37% | No |
| Sell in May | -1.5 | -2.6 | -5.6 | -30% | No |
| Dual momentum (US / international / bonds) | n/a | 0.0 | -6.1 | -24% | No |

\* from 1963.

## Sector momentum by decade (top 3 of 12, points a year)

| 1930s | 1940s | 1950s | 1960s | 1970s | 1980s | 1990s | 2000s | 2010s | 2020s |
|---|---|---|---|---|---|---|---|---|---|
| +4.3 | +2.4 | +2.6 | +4.8 | +0.1 | +3.9 | +3.1 | +3.7 | +0.7 | +2.9 |

Beta 0.93, alpha about 3 points a year out of sample (1.3 since 2010). Turnover about 275% a year.
As a sleeve: 20% of the portfolio adds about 0.6 points a year to the whole; 30% adds about 0.9.
Caveats: the strict luck bar across 106 tries is not cleared by any single variant; the evidence is the consistency. French industries are close to, not the same as, the 11 sector funds. Short-term gains make it a tax-advantaged-account idea first.

## Sell timing after a bad day (12 industries, daily, vs the market)

| Drop vs market that day | Next 5 days, 2010-2026 | Next 20 days, 2010-2026 |
|---|---|---|
| 2% or worse | -0.17% | -0.39% |
| 3% or worse | +0.17% | -0.11% |
| 4% or worse | +0.85% | +0.85% |

Small and inconsistent below a 4% gap. A same-day swap (sell the stock, buy the fund) is the default.

## Not tested here

Thematic funds have too little history. Academic work on specialized ETFs finds they tend to lag the market after launch, and their fees run 0.4% to 0.75%.
## Why this sits beside the library

The Strategies library tests on about ten years with every variant counted toward one luck bar, so its bar runs 9 to 16 points a year and no real edge of 2 to 3 points can read "held up" there. This study trades that for a century of research portfolios: more power, less like the funds you would actually buy.

## Rerun

| Step | Command |
|---|---|
| All | `research/long_history/run.sh [out_dir]` |
| Cache | `LONG_HISTORY_DATA` (default `~/.cache/vektor-desk/long-history`) |
| Time | about a minute, needs network to Dartmouth and FRED |
