from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import urlparse

from models import RawLogRow

BALANCE_FILTER_LABEL = "--exclude-balance"


@dataclass(frozen=True, slots=True)
class UrlFilterResult:
    rows: list[RawLogRow]
    removed_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def removed_count(self) -> int:
        return sum(self.removed_counts.values())


def normalize_excluded_urls(
    urls: Iterable[str],
) -> set[str]:
    """Normalize CLI exclusions while preserving exact URL matching semantics."""
    excluded_urls = {url.strip() for url in urls}
    if "" in excluded_urls:
        raise ValueError("--exclude-url 不可為空字串。")
    return excluded_urls


def _contains_balance(value: str | None) -> bool:
    return bool(value and "balance" in value.strip().casefold())


def _is_vendor_root_url(value: str | None) -> bool:
    """Return whether URL has the exact /api/v1/<vendor> path shape."""
    if not value:
        return False
    path = urlparse(value.strip()).path.rstrip("/")
    segments = [segment for segment in path.split("/") if segment]
    return (
        len(segments) == 3
        and segments[0].casefold() == "api"
        and segments[1].casefold() == "v1"
        and bool(segments[2])
    )


def _has_no_error(value: str | None) -> bool:
    """Match raw values rendered as an empty Error field in the report."""
    return value is None or value.strip().casefold() in {
        "",
        "-",
        "null",
        "n/a",
        "(empty)",
    }


def _is_balance_row(row: RawLogRow) -> bool:
    # The primary URL has priority. Only a vendor-root URL may fall back to the
    # operator URL, because deeper primary URLs already identify the API action.
    if _contains_balance(row.url):
        return True
    return (
        _is_vendor_root_url(row.url)
        and _contains_balance(row.operatorUrl)
        and _has_no_error(row.error)
    )


def filter_rows_by_url(
    rows: Iterable[RawLogRow],
    *,
    excluded_urls: set[str],
    exclude_balance: bool = False,
) -> UrlFilterResult:
    """Apply exact URL exclusions and the balance rule while preserving order."""
    kept_rows: list[RawLogRow] = []
    removed_counts: dict[str, int] = {}
    missing_url_count = 0

    for row in rows:
        normalized_url = row.url.strip() if row.url is not None else ""
        if normalized_url in excluded_urls:
            removed_counts[normalized_url] = removed_counts.get(normalized_url, 0) + 1
        elif exclude_balance and _is_balance_row(row):
            removed_counts[BALANCE_FILTER_LABEL] = (
                removed_counts.get(BALANCE_FILTER_LABEL, 0) + 1
            )
        elif not normalized_url:
            missing_url_count += 1
            kept_rows.append(row)
        else:
            kept_rows.append(row)

    warnings = []
    if (excluded_urls or exclude_balance) and missing_url_count:
        warnings.append(
            f"URL 排除時保留 {missing_url_count} 筆缺少 URL 或 URL 為空的 log。"
        )
    return UrlFilterResult(
        rows=kept_rows,
        removed_counts=removed_counts,
        warnings=warnings,
    )
