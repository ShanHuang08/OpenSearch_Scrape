from datetime import datetime, timezone

from opensearch_scrape.environments import resolve_environment
from opensearch_scrape.markdown import code_block, render_markdown
from opensearch_scrape.models import ParsedField, RawLogRow, ScrapeResult
from opensearch_scrape.parsing import normalize_row


def test_code_block_uses_longer_fence_when_content_contains_backticks() -> None:
    field = ParsedField(original="```", rendered="value ``` inside", kind="text")
    rendered = code_block(field)
    assert rendered.startswith("````text\n")
    assert rendered.endswith("\n````")


def test_empty_report_renders_summary() -> None:
    executed_at = datetime(2026, 7, 19, tzinfo=timezone.utc)
    content = render_markdown(
        ScrapeResult(records=[], expected_total=0),
        environment=resolve_environment("QA"),
        keywords=["groove"],
        kql='"groove"',
        time_from="now-1w",
        time_to="now",
        executed_at=executed_at,
    )
    assert "OpenSearch Log Report" in content
    assert "api-request-logs-qa-*" in content
    assert "沒有符合條件的 log" in content


def test_url_operator_url_and_error_are_single_line_summary_fields() -> None:
    executed_at = datetime(2026, 7, 19, tzinfo=timezone.utc)
    record = normalize_row(
        RawLogRow(
            url="/api/v1/casinoGate",
            operatorUrl="https://operator.example.test/api",
            error="DuplicateRequestException",
        ),
        scraped_at=executed_at,
        environment=resolve_environment("QA"),
        query='"casinoGate"',
        time_from="now-1w",
        time_to="now",
    )
    content = render_markdown(
        ScrapeResult(records=[record]),
        environment=resolve_environment("QA"),
        keywords=["casinoGate"],
        kql='"casinoGate"',
        time_from="now-1w",
        time_to="now",
        executed_at=executed_at,
    )
    assert "- URL: `/api/v1/casinoGate`" in content
    assert "- Operator URL: `https://operator.example.test/api`" in content
    assert "- Error: `DuplicateRequestException`" in content
    assert "### URL" not in content
    assert "### Operator URL" not in content
    assert "### Error" not in content


def test_log_directory_links_to_named_log_and_blanks_no_error() -> None:
    executed_at = datetime(2026, 7, 19, tzinfo=timezone.utc)
    record = normalize_row(
        RawLogRow(url="/api/v1/casinogate", error="-"),
        scraped_at=executed_at,
        environment=resolve_environment("QA"),
        query='"casinoGate"',
        time_from="now-1w",
        time_to="now",
    )
    content = render_markdown(
        ScrapeResult(records=[record]),
        environment=resolve_environment("QA"),
        keywords=["casinoGate"],
        kql='"casinoGate"',
        time_from="now-1w",
        time_to="now",
        executed_at=executed_at,
    )
    assert "## Log 目錄" in content
    assert '| 1 | <a href="#log-1">/api/v1/casinogate</a> |  |' in content
    assert "## Log 1: `/api/v1/casinogate`" in content


def test_log_directory_has_new_tab_opensearch_link() -> None:
    content = render_markdown(
        ScrapeResult(records=[]),
        environment=resolve_environment("QA"),
        keywords=["casinoGate"],
        kql='"casinoGate"',
        time_from="now-1w",
        time_to="now",
        executed_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        discover_url="https://example.test/discover#?_q=query%3A%27casinoGate%27",
    )
    assert '<a href="https://example.test/discover#?_q=query%3A%27casinoGate%27"' in content
    assert 'target="_blank"' in content
