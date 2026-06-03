"""CLI for fetching the SEC 10-K corpus into data/raw/.

Examples:
    uv run python scripts/fetch_corpus.py --dry-run
    uv run python scripts/fetch_corpus.py
    uv run python scripts/fetch_corpus.py --companies apple microsoft --years 2023 2024
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

from finsight.config import get_settings
from finsight.ingestion.companies import COMPANIES, COMPANIES_BY_SLUG, Company
from finsight.ingestion.fetchers.edgar import DownloadStatus, EdgarClient
from finsight.logging import configure_logging

DEFAULT_FISCAL_YEARS = (2020, 2021, 2022, 2023, 2024)
PLACEHOLDER_USER_AGENT = "finsight your-email@example.com"


def _repo_root() -> Path:
    # scripts/fetch_corpus.py -> apps/api -> apps -> <repo root>
    return Path(__file__).resolve().parents[3]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch SEC 10-K filings into the raw corpus.")
    parser.add_argument(
        "--companies",
        nargs="+",
        metavar="SLUG",
        choices=sorted(COMPANIES_BY_SLUG),
        help="Company slugs to fetch (default: all).",
    )
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        metavar="YEAR",
        default=list(DEFAULT_FISCAL_YEARS),
        help="Fiscal years to fetch (default: 2020-2024).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_repo_root() / "data" / "raw",
        help="Destination for downloaded filings (default: <repo>/data/raw).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve and list the filings that would be fetched, then exit.",
    )
    return parser.parse_args(argv)


def _selected_companies(slugs: list[str] | None) -> list[Company]:
    if not slugs:
        return list(COMPANIES)
    return [COMPANIES_BY_SLUG[slug] for slug in slugs]


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.sec.user_agent == PLACEHOLDER_USER_AGENT:
        print(
            "ERROR: SEC_EDGAR_USER_AGENT is still the placeholder. SEC blocks requests without a "
            "real contact. Set it in .env to 'Your Name your-email@domain.com' and retry.",
            file=sys.stderr,
        )
        return 2

    companies = _selected_companies(args.companies)
    fiscal_years = sorted(set(args.years))

    print(f"Companies: {', '.join(c.slug for c in companies)}")
    print(f"Fiscal years: {', '.join(str(y) for y in fiscal_years)}")
    print(f"Output: {args.output_dir}\n")

    async with EdgarClient.from_settings(settings) as client:
        if args.dry_run:
            refs = await client.plan(companies, fiscal_years)
            print(f"\nDry run — {len(refs)} filing(s) would be fetched:")
            for ref in refs:
                print(f"  {ref.company.slug:<12} FY{ref.fiscal_year}  {ref.document_url}")
            return 0

        results = await client.fetch_corpus(companies, fiscal_years, args.output_dir)

    counts = Counter(result.status for result in results)
    print("\nSummary:")
    print(f"  downloaded: {counts[DownloadStatus.DOWNLOADED]}")
    print(f"  skipped:    {counts[DownloadStatus.SKIPPED]}")
    print(f"  failed:     {counts[DownloadStatus.FAILED]}")

    failures = [r for r in results if r.status == DownloadStatus.FAILED]
    if failures:
        print("\nFailures:")
        for result in failures:
            print(f"  {result.filing.company.slug} FY{result.filing.fiscal_year}: {result.error}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
