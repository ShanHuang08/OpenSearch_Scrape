from filtering import (
    BALANCE_FILTER_LABEL,
    filter_rows_by_url,
    normalize_excluded_urls,
)
from models import RawLogRow

BALANCE_API_URL = "/api/v1/esoterica/balance"


def test_filter_rows_by_url_uses_exact_trimmed_match_and_preserves_order() -> None:
    rows = [
        RawLogRow(url="/api/v1/first"),
        RawLogRow(url=f" {BALANCE_API_URL} "),
        RawLogRow(url=f"{BALANCE_API_URL}/extra"),
        RawLogRow(url=None),
        RawLogRow(url=""),
        RawLogRow(url="/api/v1/last"),
    ]

    result = filter_rows_by_url(rows, excluded_urls={BALANCE_API_URL})

    assert [row.url for row in result.rows] == [
        "/api/v1/first",
        f"{BALANCE_API_URL}/extra",
        None,
        "",
        "/api/v1/last",
    ]
    assert result.removed_counts == {BALANCE_API_URL: 1}
    assert result.removed_count == 1
    assert result.warnings == ["URL 排除時保留 2 筆缺少 URL 或 URL 為空的 log。"]


def test_filter_rows_without_exclusions_keeps_every_row_without_warnings() -> None:
    rows = [RawLogRow(url=BALANCE_API_URL), RawLogRow(url=None)]

    result = filter_rows_by_url(rows, excluded_urls=set())

    assert result.rows == rows
    assert result.removed_count == 0
    assert result.warnings == []


def test_normalize_excluded_urls_combines_repeated_exact_urls() -> None:
    assert normalize_excluded_urls(
        [" /api/v1/one ", "/api/v1/two", "/api/v1/one"],
    ) == {"/api/v1/one", "/api/v1/two"}


def test_balance_filter_prioritizes_primary_url() -> None:
    rows = [
        RawLogRow(
            url="/api/v1/esoterica/balance",
            operatorUrl="https://operator.test/api/v2/wallet/bet",
            error="OperatorApiException",
        ),
        RawLogRow(
            url="/api/v1/softgaming/bet",
            operatorUrl="https://operator.test/api/v2/wallet/balance",
            error="",
        ),
    ]

    result = filter_rows_by_url(
        rows,
        excluded_urls=set(),
        exclude_balance=True,
    )

    assert result.rows == [rows[1]]
    assert result.removed_counts == {BALANCE_FILTER_LABEL: 1}


def test_balance_filter_uses_operator_url_for_error_free_vendor_root() -> None:
    rows = [
        RawLogRow(
            url="/api/v1/softgaming",
            operatorUrl="https://operator-stub.gasea168.com/api/v2/wallet/balance",
            error=error,
        )
        for error in (None, "", " ", "-", "null")
    ]

    result = filter_rows_by_url(
        rows,
        excluded_urls=set(),
        exclude_balance=True,
    )

    assert result.rows == []
    assert result.removed_counts == {BALANCE_FILTER_LABEL: 5}


def test_balance_filter_keeps_operator_balance_when_fallback_conditions_fail() -> None:
    rows = [
        RawLogRow(
            url="/api/v1/softgaming",
            operatorUrl="https://operator.test/api/v2/wallet/balance",
            error="OperatorApiException",
        ),
        RawLogRow(
            url="/api/v1/softgaming/bet",
            operatorUrl="https://operator.test/api/v2/wallet/balance",
            error="",
        ),
        RawLogRow(
            url="/api/v2/softgaming",
            operatorUrl="https://operator.test/api/v2/wallet/balance",
            error="",
        ),
        RawLogRow(
            url="/api/v1/softgaming",
            operatorUrl="https://operator.test/api/v2/wallet/bet",
            error="",
        ),
    ]

    result = filter_rows_by_url(
        rows,
        excluded_urls=set(),
        exclude_balance=True,
    )

    assert result.rows == rows
    assert result.removed_count == 0
