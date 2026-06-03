"""SEC EDGAR fetcher for 10-K filings.

Resolves company tickers to CIKs, reads each company's submission history from
the EDGAR data API, selects the requested 10-K filings, and downloads each
filing's primary document into the raw corpus.

SEC access rules enforced here:
  - every request carries a descriptive User-Agent (SEC blocks generic/empty ones)
  - requests are throttled below the 10 req/s per-IP ceiling
See https://www.sec.gov/about/developer-resources for the current policy.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Collection, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from types import TracebackType

import httpx
from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

from finsight.config import Settings
from finsight.ingestion.companies import Company
from finsight.logging import get_logger

_log = get_logger(__name__)

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
DATA_BASE = "https://data.sec.gov"
ARCHIVES_BASE = "https://www.sec.gov/Archives"
TARGET_FORM = "10-K"


class EdgarError(RuntimeError):
    """Raised when EDGAR data cannot be retrieved or resolved."""


# --- External response models (pydantic: validate untrusted SEC payloads) ---


class _TickerEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cik_str: int
    ticker: str


class _TickerFile(RootModel[dict[str, _TickerEntry]]):
    pass


class _FilingArrays(BaseModel):
    """The parallel-array filing shape shared by `recent` and overflow files."""

    model_config = ConfigDict(extra="ignore")

    accession_number: list[str] = Field(alias="accessionNumber")
    filing_date: list[str] = Field(alias="filingDate")
    report_date: list[str] = Field(alias="reportDate")
    form: list[str]
    primary_document: list[str] = Field(alias="primaryDocument")

    @model_validator(mode="after")
    def _equal_lengths(self) -> _FilingArrays:
        lengths = {
            len(self.accession_number),
            len(self.filing_date),
            len(self.report_date),
            len(self.form),
            len(self.primary_document),
        }
        if len(lengths) > 1:
            raise ValueError("SEC submissions arrays have mismatched lengths")
        return self


class _FilingFileRef(BaseModel):
    """Reference to a supplementary submissions file holding older filings."""

    model_config = ConfigDict(extra="ignore")

    name: str
    filing_from: str = Field(default="", alias="filingFrom")
    filing_to: str = Field(default="", alias="filingTo")


class _Filings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    recent: _FilingArrays
    files: list[_FilingFileRef] = Field(default_factory=list)


class SubmissionsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    filings: _Filings


# --- Internal value objects (frozen dataclasses) ---


@dataclass(frozen=True, slots=True)
class FilingRef:
    """A resolved 10-K filing, ready to download."""

    company: Company
    cik: str
    form: str
    fiscal_year: int
    accession_number: str
    primary_document: str
    report_date: date
    filing_date: date
    document_url: str


@dataclass(frozen=True, slots=True)
class FilingMetadata:
    """Provenance written alongside each downloaded filing."""

    company_slug: str
    ticker: str
    display_name: str
    cik: str
    form: str
    fiscal_year: int
    accession_number: str
    report_date: str
    filing_date: str
    source_url: str
    retrieved_at: str


class DownloadStatus(StrEnum):
    DOWNLOADED = "downloaded"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DownloadResult:
    filing: FilingRef
    status: DownloadStatus
    path: Path | None
    error: str | None = None


# --- Pure helpers (no I/O; unit-tested directly) ---


def format_cik(cik: int | str) -> str:
    """Zero-pad a CIK to the 10-digit form required by data.sec.gov."""
    return f"{int(cik):010d}"


def build_document_url(cik: str, accession_number: str, primary_document: str) -> str:
    """Construct the archives URL of a filing's primary document."""
    accession_plain = accession_number.replace("-", "")
    return f"{ARCHIVES_BASE}/edgar/data/{int(cik)}/{accession_plain}/{primary_document}"


def fiscal_year_from_report_date(report_date: date) -> int:
    """Map a 10-K period-of-report date to a fiscal year.

    Uses the calendar year of the period end. For the corpus companies this
    matches each issuer's own labelling, including non-December year-ends
    (e.g. NVIDIA's fiscal year ends in late January and is labelled with that
    calendar year).
    """
    return report_date.year


def overflow_file_in_range(ref: _FilingFileRef, fiscal_years: Collection[int]) -> bool:
    """Whether a supplementary file's date span could contain the wanted years.

    Overflow files are bounded by filingFrom/filingTo dates. We keep a file
    only if its span overlaps the calendar years we care about; an absent or
    unparseable bound is treated as open-ended (fetch to be safe).
    """
    if not fiscal_years:
        return False
    wanted_min, wanted_max = min(fiscal_years), max(fiscal_years)
    try:
        file_from = date.fromisoformat(ref.filing_from).year if ref.filing_from else wanted_min
    except ValueError:
        file_from = wanted_min
    try:
        file_to = date.fromisoformat(ref.filing_to).year if ref.filing_to else wanted_max
    except ValueError:
        file_to = wanted_max
    # 10-Ks are filed a few months after period end, so widen the window by one year.
    return file_from <= wanted_max + 1 and file_to >= wanted_min


def _merge_arrays(target: _FilingArrays, extra: _FilingArrays) -> None:
    """Append one filing-array block onto another (in place)."""
    target.accession_number.extend(extra.accession_number)
    target.filing_date.extend(extra.filing_date)
    target.report_date.extend(extra.report_date)
    target.form.extend(extra.form)
    target.primary_document.extend(extra.primary_document)


def select_10k_filings(
    company: Company,
    cik: str,
    submissions: SubmissionsResponse,
    fiscal_years: Collection[int],
) -> list[FilingRef]:
    """Filter a submission history down to the requested 10-K filings."""
    recent = submissions.filings.recent
    refs: list[FilingRef] = []
    for form, accession, report, filed, primary in zip(
        recent.form,
        recent.accession_number,
        recent.report_date,
        recent.filing_date,
        recent.primary_document,
        strict=True,
    ):
        if form != TARGET_FORM or not report or not primary:
            continue
        try:
            report_date = date.fromisoformat(report)
            filing_date = date.fromisoformat(filed) if filed else report_date
        except ValueError:
            continue
        fiscal_year = fiscal_year_from_report_date(report_date)
        if fiscal_year not in fiscal_years:
            continue
        refs.append(
            FilingRef(
                company=company,
                cik=cik,
                form=form,
                fiscal_year=fiscal_year,
                accession_number=accession,
                primary_document=primary,
                report_date=report_date,
                filing_date=filing_date,
                document_url=build_document_url(cik, accession, primary),
            )
        )
    refs.sort(key=lambda ref: ref.fiscal_year)
    return refs


class RateLimiter:
    """Throttle to at most `rate_per_second` operations by spacing their starts."""

    def __init__(self, rate_per_second: float) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        self._min_interval = 1.0 / rate_per_second
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._next_allowed - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._next_allowed = now + self._min_interval


class EdgarClient:
    """Async client for fetching 10-K filings from SEC EDGAR.

    The injected HTTP client must send a SEC-compliant User-Agent header; use
    `from_settings` to build one that does.
    """

    def __init__(self, *, http_client: httpx.AsyncClient, rate_limiter: RateLimiter) -> None:
        self._http_client = http_client
        self._rate_limiter = rate_limiter
        self._ticker_map: dict[str, int] | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> EdgarClient:
        http_client = httpx.AsyncClient(
            headers={"User-Agent": settings.sec.user_agent},
            timeout=httpx.Timeout(settings.sec.timeout_seconds),
            follow_redirects=True,
        )
        return cls(
            http_client=http_client, rate_limiter=RateLimiter(settings.sec.requests_per_second)
        )

    async def __aenter__(self) -> EdgarClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http_client.aclose()

    async def _get(self, url: str) -> httpx.Response:
        await self._rate_limiter.acquire()
        response = await self._http_client.get(url)
        response.raise_for_status()
        return response

    async def _load_ticker_map(self) -> dict[str, int]:
        cached = self._ticker_map
        if cached is not None:
            return cached
        response = await self._get(SEC_TICKERS_URL)
        parsed = _TickerFile.model_validate(response.json())
        ticker_map = {entry.ticker.upper(): entry.cik_str for entry in parsed.root.values()}
        self._ticker_map = ticker_map
        return ticker_map

    async def resolve_ciks(self, companies: Sequence[Company]) -> dict[str, str]:
        ticker_map = await self._load_ticker_map()
        resolved: dict[str, str] = {}
        missing: list[str] = []
        for company in companies:
            cik_int = ticker_map.get(company.ticker.upper())
            if cik_int is None:
                missing.append(company.ticker)
                continue
            resolved[company.ticker] = format_cik(cik_int)
        if missing:
            raise EdgarError(f"tickers not found in SEC ticker map: {', '.join(missing)}")
        return resolved

    async def fetch_submissions(
        self, cik: str, fiscal_years: Collection[int] = ()
    ) -> SubmissionsResponse:
        response = await self._get(f"{DATA_BASE}/submissions/CIK{cik}.json")
        submissions = SubmissionsResponse.model_validate(response.json())
        for ref in submissions.filings.files:
            if not overflow_file_in_range(ref, fiscal_years):
                continue
            overflow_response = await self._get(f"{DATA_BASE}/submissions/{ref.name}")
            overflow = _FilingArrays.model_validate(overflow_response.json())
            _merge_arrays(submissions.filings.recent, overflow)
        return submissions

    async def plan(
        self, companies: Sequence[Company], fiscal_years: Collection[int]
    ) -> list[FilingRef]:
        cik_by_ticker = await self.resolve_ciks(companies)
        refs: list[FilingRef] = []
        for company in companies:
            cik = cik_by_ticker[company.ticker]
            submissions = await self.fetch_submissions(cik, fiscal_years)
            company_refs = select_10k_filings(company, cik, submissions, fiscal_years)
            _log.info(
                "company_planned",
                company=company.slug,
                cik=cik,
                filings=len(company_refs),
                fiscal_years=sorted(ref.fiscal_year for ref in company_refs),
            )
            refs.extend(company_refs)
        return refs

    def _persist(self, filing: FilingRef, content: bytes, doc_path: Path, dest_dir: Path) -> None:
        dest_dir.mkdir(parents=True, exist_ok=True)
        doc_path.write_bytes(content)
        metadata = FilingMetadata(
            company_slug=filing.company.slug,
            ticker=filing.company.ticker,
            display_name=filing.company.display_name,
            cik=filing.cik,
            form=filing.form,
            fiscal_year=filing.fiscal_year,
            accession_number=filing.accession_number,
            report_date=filing.report_date.isoformat(),
            filing_date=filing.filing_date.isoformat(),
            source_url=filing.document_url,
            retrieved_at=datetime.now(tz=UTC).isoformat(),
        )
        (dest_dir / "metadata.json").write_text(
            json.dumps(asdict(metadata), indent=2) + "\n", encoding="utf-8"
        )

    async def download(self, filing: FilingRef, output_dir: Path) -> DownloadResult:
        dest_dir = output_dir / filing.company.slug / f"FY{filing.fiscal_year}"
        suffix = Path(filing.primary_document).suffix or ".htm"
        doc_path = dest_dir / f"{filing.form}{suffix}"

        if doc_path.exists():
            _log.info("filing_skipped", company=filing.company.slug, fiscal_year=filing.fiscal_year)
            return DownloadResult(filing=filing, status=DownloadStatus.SKIPPED, path=doc_path)

        try:
            response = await self._get(filing.document_url)
            await asyncio.to_thread(self._persist, filing, response.content, doc_path, dest_dir)
        except (httpx.HTTPError, OSError) as exc:
            _log.warning(
                "filing_failed",
                company=filing.company.slug,
                fiscal_year=filing.fiscal_year,
                error=str(exc),
            )
            return DownloadResult(
                filing=filing, status=DownloadStatus.FAILED, path=None, error=str(exc)
            )

        _log.info(
            "filing_downloaded",
            company=filing.company.slug,
            fiscal_year=filing.fiscal_year,
            bytes=len(response.content),
        )
        return DownloadResult(filing=filing, status=DownloadStatus.DOWNLOADED, path=doc_path)

    async def fetch_corpus(
        self, companies: Sequence[Company], fiscal_years: Collection[int], output_dir: Path
    ) -> list[DownloadResult]:
        refs = await self.plan(companies, fiscal_years)
        results: list[DownloadResult] = []
        for ref in refs:
            results.append(await self.download(ref, output_dir))
        return results
