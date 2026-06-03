"""Registry of companies in the finsight corpus.

Each company is identified by its SEC ticker (resolved to a CIK at fetch time)
and a filesystem-safe slug used for the on-disk corpus layout.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Company:
    """A company tracked in the corpus."""

    slug: str
    ticker: str
    display_name: str


COMPANIES: tuple[Company, ...] = (
    Company(slug="apple", ticker="AAPL", display_name="Apple Inc."),
    Company(slug="microsoft", ticker="MSFT", display_name="Microsoft Corporation"),
    Company(slug="alphabet", ticker="GOOGL", display_name="Alphabet Inc."),
    Company(slug="amazon", ticker="AMZN", display_name="Amazon.com, Inc."),
    Company(slug="meta", ticker="META", display_name="Meta Platforms, Inc."),
    Company(slug="nvidia", ticker="NVDA", display_name="NVIDIA Corporation"),
    Company(slug="tesla", ticker="TSLA", display_name="Tesla, Inc."),
    Company(slug="jpmorgan", ticker="JPM", display_name="JPMorgan Chase & Co."),
    Company(slug="walmart", ticker="WMT", display_name="Walmart Inc."),
    Company(slug="exxonmobil", ticker="XOM", display_name="Exxon Mobil Corporation"),
)

COMPANIES_BY_SLUG: dict[str, Company] = {company.slug: company for company in COMPANIES}
COMPANIES_BY_TICKER: dict[str, Company] = {company.ticker: company for company in COMPANIES}
