"""Unit tests for the SEC EDGAR fetcher."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx
import pytest

from finsight.config import get_settings
from finsight.ingestion.companies import Company
from finsight.ingestion.fetchers.edgar import (
    DownloadStatus,
    EdgarClient,
    EdgarError,
    FilingRef,
    RateLimiter,
    SubmissionsResponse,
    _FilingFileRef,
    build_document_url,
    fiscal_year_from_report_date,
    format_cik,
    overflow_file_in_range,
    select_10k_filings,
)

ACME = Company(slug="acme", ticker="ACME", display_name="Acme Corporation")


def _make_client(
    handler: Callable[[httpx.Request], httpx.Response], *, rate: float = 1000.0
) -> EdgarClient:
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"User-Agent": "finsight-test test@example.com"},
        follow_redirects=True,
    )
    return EdgarClient(http_client=http_client, rate_limiter=RateLimiter(rate))


def _submissions(forms: list[str], reports: list[str]) -> SubmissionsResponse:
    n = len(forms)
    return SubmissionsResponse.model_validate(
        {
            "filings": {
                "recent": {
                    "form": forms,
                    "accessionNumber": [f"0000000000-00-{i:06d}" for i in range(n)],
                    "reportDate": reports,
                    "filingDate": reports,
                    "primaryDocument": [f"doc-{i}.htm" for i in range(n)],
                }
            }
        }
    )


def _filing() -> FilingRef:
    return FilingRef(
        company=ACME,
        cik="0000000000",
        form="10-K",
        fiscal_year=2023,
        accession_number="0000000000-23-000001",
        primary_document="acme-20231231.htm",
        report_date=date(2023, 12, 31),
        filing_date=date(2024, 2, 1),
        document_url="https://www.sec.gov/Archives/edgar/data/0/000000000023000001/acme-20231231.htm",
    )


def test_format_cik_pads_to_ten_digits() -> None:
    assert format_cik(320193) == "0000320193"
    assert format_cik("789019") == "0000789019"


def test_build_document_url_strips_dashes_and_padding() -> None:
    url = build_document_url("0000320193", "0000320193-24-000123", "aapl-20240928.htm")
    assert (
        url == "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"
    )


@pytest.mark.parametrize(
    ("report", "expected"),
    [
        (date(2024, 12, 31), 2024),
        (date(2024, 9, 28), 2024),
        (date(2024, 6, 30), 2024),
        (date(2024, 1, 28), 2024),
    ],
)
def test_fiscal_year_uses_report_year(report: date, expected: int) -> None:
    assert fiscal_year_from_report_date(report) == expected


def test_select_filters_form_and_year_and_sorts() -> None:
    submissions = _submissions(
        forms=["10-K", "10-Q", "10-K", "8-K", "10-K"],
        reports=["2022-12-31", "2023-03-31", "2023-12-31", "2023-05-01", "2019-12-31"],
    )
    refs = select_10k_filings(ACME, "0000000000", submissions, {2020, 2021, 2022, 2023, 2024})
    assert [ref.fiscal_year for ref in refs] == [2022, 2023]


def test_select_skips_empty_report_date() -> None:
    submissions = _submissions(forms=["10-K", "10-K"], reports=["", "2023-12-31"])
    refs = select_10k_filings(ACME, "0000000000", submissions, {2023})
    assert [ref.fiscal_year for ref in refs] == [2023]


async def test_resolve_ciks_maps_and_caches() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            200,
            json={
                "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
                "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
            },
        )

    apple = Company(slug="apple", ticker="AAPL", display_name="Apple Inc.")
    msft = Company(slug="microsoft", ticker="MSFT", display_name="Microsoft Corp")
    async with _make_client(handler) as client:
        first = await client.resolve_ciks([apple, msft])
        second = await client.resolve_ciks([apple])

    assert first == {"AAPL": "0000320193", "MSFT": "0000789019"}
    assert second == {"AAPL": "0000320193"}
    assert calls["count"] == 1


async def test_resolve_ciks_raises_on_unknown_ticker() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"0": {"cik_str": 1, "ticker": "AAPL", "title": "Apple"}})

    unknown = Company(slug="unknown", ticker="ZZZZ", display_name="Unknown")
    async with _make_client(handler) as client:
        with pytest.raises(EdgarError):
            await client.resolve_ciks([unknown])


async def test_download_writes_document_and_metadata(tmp_path: Path) -> None:
    html = b"<html><body>10-K</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=html)

    filing = _filing()
    async with _make_client(handler) as client:
        result = await client.download(filing, tmp_path)

    assert result.status == DownloadStatus.DOWNLOADED
    base = tmp_path / "acme" / "FY2023"
    assert (base / "10-K.htm").read_bytes() == html
    payload = json.loads((base / "metadata.json").read_text())
    assert payload["accession_number"] == filing.accession_number
    assert payload["cik"] == filing.cik
    assert payload["source_url"] == filing.document_url


async def test_download_skips_existing_file(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("network must not be hit when the file already exists")

    base = tmp_path / "acme" / "FY2023"
    base.mkdir(parents=True)
    (base / "10-K.htm").write_bytes(b"cached")

    async with _make_client(handler) as client:
        result = await client.download(_filing(), tmp_path)

    assert result.status == DownloadStatus.SKIPPED
    assert (base / "10-K.htm").read_bytes() == b"cached"


async def test_download_marks_failure_on_http_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    async with _make_client(handler) as client:
        result = await client.download(_filing(), tmp_path)

    assert result.status == DownloadStatus.FAILED
    assert result.error is not None
    assert not (tmp_path / "acme" / "FY2023" / "10-K.htm").exists()


async def test_rate_limiter_spaces_requests() -> None:
    limiter = RateLimiter(rate_per_second=50)
    start = time.monotonic()
    await limiter.acquire()
    await limiter.acquire()
    await limiter.acquire()
    assert time.monotonic() - start >= 0.04


async def test_from_settings_builds_and_closes() -> None:
    async with EdgarClient.from_settings(get_settings()):
        pass


def test_overflow_in_range_keeps_overlapping_span() -> None:
    ref = _FilingFileRef.model_validate(
        {"name": "x-001.json", "filingFrom": "2018-01-01", "filingTo": "2021-06-01"}
    )
    assert overflow_file_in_range(ref, {2020, 2021, 2022, 2023, 2024}) is True


def test_overflow_out_of_range_is_skipped() -> None:
    ref = _FilingFileRef.model_validate(
        {"name": "x-001.json", "filingFrom": "2005-01-01", "filingTo": "2009-12-31"}
    )
    assert overflow_file_in_range(ref, {2020, 2021, 2022, 2023, 2024}) is False


def test_overflow_empty_years_is_skipped() -> None:
    ref = _FilingFileRef.model_validate({"name": "x-001.json"})
    assert overflow_file_in_range(ref, set()) is False


async def test_fetch_submissions_merges_overflow() -> None:
    main = {
        "filings": {
            "recent": {
                "form": ["10-K"],
                "accessionNumber": ["0000000000-24-000001"],
                "reportDate": ["2024-12-31"],
                "filingDate": ["2025-02-01"],
                "primaryDocument": ["doc-2024.htm"],
            },
            "files": [
                {
                    "name": "CIK-submissions-001.json",
                    "filingFrom": "2019-01-01",
                    "filingTo": "2023-12-31",
                }
            ],
        }
    }
    overflow = {
        "form": ["10-K", "8-K"],
        "accessionNumber": ["0000000000-21-000001", "0000000000-21-000002"],
        "reportDate": ["2021-12-31", "2021-06-01"],
        "filingDate": ["2022-02-01", "2021-06-02"],
        "primaryDocument": ["doc-2021.htm", "doc-8k.htm"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("CIK-submissions-001.json"):
            return httpx.Response(200, json=overflow)
        return httpx.Response(200, json=main)

    async with _make_client(handler) as client:
        submissions = await client.fetch_submissions("0000000000", {2020, 2021, 2022, 2023, 2024})
        refs = select_10k_filings(ACME, "0000000000", submissions, {2020, 2021, 2022, 2023, 2024})

    assert [ref.fiscal_year for ref in refs] == [2021, 2024]


async def test_fetch_submissions_skips_out_of_range_overflow() -> None:
    main = {
        "filings": {
            "recent": {
                "form": ["10-K"],
                "accessionNumber": ["0000000000-24-000001"],
                "reportDate": ["2024-12-31"],
                "filingDate": ["2025-02-01"],
                "primaryDocument": ["doc-2024.htm"],
            },
            "files": [
                {"name": "ancient-001.json", "filingFrom": "2001-01-01", "filingTo": "2008-12-31"}
            ],
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "ancient" in request.url.path:
            raise AssertionError("out-of-range overflow file must not be fetched")
        return httpx.Response(200, json=main)

    async with _make_client(handler) as client:
        submissions = await client.fetch_submissions("0000000000", {2023, 2024})

    assert len(submissions.filings.recent.form) == 1
