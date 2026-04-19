"""MOPS (公開資訊觀測站) scraping fallback.

Placeholder: activated only if FinMind quota is exhausted. Not yet implemented.

Target endpoints:
- Monthly revenue:  https://mops.twse.com.tw/mops/web/ajax_t05st10_ifrs
- Quarterly income: https://mops.twse.com.tw/mops/web/ajax_t163sb04
- Balance sheet:    https://mops.twse.com.tw/mops/web/ajax_t163sb05

Implementation notes (when time comes):
1. POST form data with co_id, year, season
2. Response is HTML, parse tables with pandas.read_html
3. Rate limit strictly: time.sleep(3) between calls, random jitter
4. Use realistic User-Agent
5. Respect robots.txt (MOPS disallows automated scraping of some paths)
6. Consider saving raw HTML to data/raw/mops/ for later re-parsing
"""
from __future__ import annotations


def fetch_monthly_revenue_from_mops(stock_code: str, year: int) -> None:
    raise NotImplementedError(
        "MOPS scraping not implemented. "
        "Use FinMind with --resume first. "
        "See RUNBOOK.md section 'FinMind 配額耗盡'."
    )


def fetch_quarterly_financials_from_mops(stock_code: str, year: int, quarter: int) -> None:
    raise NotImplementedError(
        "MOPS scraping not implemented. "
        "Use FinMind with --resume first. "
        "See RUNBOOK.md section 'FinMind 配額耗盡'."
    )
