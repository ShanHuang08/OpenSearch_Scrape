import pytest

from cli import (
    build_parser,
    clear_output_directory,
    google_spreadsheet_url,
    main,
    open_google_spreadsheet,
)
from config import Settings
from environments import resolve_environment
from query import (
    build_discover_url,
    build_kql,
    parse_keyword_expression,
    query_slug,
)
from scraper import RawScrapeResult


def test_single_keyword_kql_and_url() -> None:
    kql = build_kql(["groove"])
    url = build_discover_url("https://example.test/app/discover", resolve_environment("QA"), kql)

    assert kql == '"groove"'
    assert "%22groove%22%20" in url
    assert "53ceb180-8f5d-11ef-b9c6-73a60e0d81fe" in url


def test_multiple_keyword_kql_and_url() -> None:
    kql = build_kql(["groove", "cs20260716071044"])
    url = build_discover_url(
        "https://example.test/app/discover", resolve_environment("staging"), kql
    )

    assert kql == '"groove" or "cs20260716071044"'
    assert "%22groove%22%20or%20%22cs20260716071044%22%20" in url
    assert "48481400-8c6a-11ef-b9c6-73a60e0d81fe" in url


def test_kql_escapes_quotes_and_backslashes() -> None:
    assert build_kql(['a"b\\c']) == '"a\\"b\\\\c"'


def test_empty_keywords_are_rejected() -> None:
    with pytest.raises(ValueError, match="至少需要"):
        build_kql([" "])


@pytest.mark.parametrize(
    ("values", "expected_keywords", "expected_operator"),
    [
        (["groove", "or"], ["groove"], None),
        (["groove and"], ["groove"], None),
        (["A", "or", "B", "or"], ["A", "B"], "or"),
        (["A or or"], ["A"], None),
        (["123", "or", "456"], ["123", "456"], "or"),
    ],
)
def test_trailing_keyword_operators_are_removed(
    values: list[str],
    expected_keywords: list[str],
    expected_operator: str | None,
) -> None:
    assert parse_keyword_expression(values) == (expected_keywords, expected_operator)


@pytest.mark.parametrize("values", [["or"], ["and"], ["or", "or"]])
def test_operator_only_expression_is_rejected(values: list[str]) -> None:
    with pytest.raises(ValueError, match="至少需要"):
        parse_keyword_expression(values)


def test_query_slug() -> None:
    assert query_slug(["Groove", "cs20260716071044"]) == "groove-or-cs20260716071044"


def test_cli_defaults_to_fifty_records() -> None:
    args = build_parser().parse_args(["--environment", "QA", "--keyword", "groove"])
    assert args.max_records == 50


def test_google_sheets_is_disabled_by_default() -> None:
    args = build_parser().parse_args(["--environment", "QA", "--keyword", "groove"])
    assert Settings().google_sheets_enabled is False
    assert args.google_sheets is None


def test_google_sheets_cli_switches() -> None:
    enabled = build_parser().parse_args(
        ["--environment", "QA", "--keyword", "groove", "--google-sheets"]
    )
    disabled = build_parser().parse_args(
        ["--environment", "QA", "--keyword", "groove", "--no-google-sheets"]
    )
    assert enabled.google_sheets is True
    assert disabled.google_sheets is False


def test_google_spreadsheet_url() -> None:
    assert google_spreadsheet_url(" sheet-id ") == (
        "https://docs.google.com/spreadsheets/d/sheet-id/edit"
    )


def test_google_spreadsheet_url_requires_id() -> None:
    with pytest.raises(ValueError, match="GOOGLE_SPREADSHEET_ID"):
        google_spreadsheet_url(" ")


def test_open_google_spreadsheet_uses_default_browser(monkeypatch, capsys) -> None:
    opened_urls: list[str] = []
    monkeypatch.setattr(
        "cli.webbrowser.open",
        lambda url: opened_urls.append(url) or True,
    )

    assert open_google_spreadsheet("sheet-id") is True
    assert opened_urls == ["https://docs.google.com/spreadsheets/d/sheet-id/edit"]
    assert "Google Sheet 已開啟" in capsys.readouterr().out


def test_google_sheets_dry_run_opens_sheet_without_writing(monkeypatch) -> None:
    settings = Settings(
        google_sheets_enabled=True,
        google_spreadsheet_id="sheet-id",
    )
    opened_ids: list[str] = []
    monkeypatch.setattr("cli.Settings.from_env", lambda: settings)
    monkeypatch.setattr(
        "cli.open_google_spreadsheet",
        lambda spreadsheet_id: opened_ids.append(spreadsheet_id) or True,
    )

    exit_code = main(
        ["--environment", "QA", "--keyword", "groove", "--google-sheets", "--dry-run"]
    )

    assert exit_code == 0
    assert opened_ids == ["sheet-id"]


def test_zero_opensearch_results_fail_before_outputs(monkeypatch, capsys) -> None:
    class EmptyScraper:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def run(self) -> RawScrapeResult:
            return RawScrapeResult(rows=[], expected_total=0)

    def unexpected_output(*args, **kwargs):
        raise AssertionError("0 筆結果不得產生 Markdown 或寫入 Google Sheets")

    monkeypatch.setattr("cli.OpenSearchScraper", EmptyScraper)
    monkeypatch.setattr("cli.write_markdown", unexpected_output)
    monkeypatch.setattr("cli.GoogleSheetsWriter", unexpected_output)
    monkeypatch.setattr("cli.webbrowser.open", unexpected_output)

    exit_code = main(["--environment", "QA", "--keyword", "missing-log"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "OpenSearch 找不到符合條件的 log" in captured.err


def test_clear_log_switch_accepts_hyphen_and_underscore() -> None:
    hyphen = build_parser().parse_args(["--clear-log"])
    underscore = build_parser().parse_args(["--clear_log"])
    assert hyphen.clear_log is True
    assert underscore.clear_log is True


def test_clear_output_directory_removes_files_and_nested_directories(tmp_path) -> None:
    output_dir = tmp_path / "output"
    nested = output_dir / "nested"
    nested.mkdir(parents=True)
    (output_dir / "report.md").write_text("report", encoding="utf-8")
    (nested / "debug.log").write_text("log", encoding="utf-8")

    removed = clear_output_directory(output_dir)

    assert removed == 2
    assert output_dir.is_dir()
    assert list(output_dir.iterdir()) == []


def test_clear_output_directory_rejects_working_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="不安全"):
        clear_output_directory(tmp_path)


def test_clear_log_command_clears_and_exits_without_query(tmp_path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "report.md").write_text("report", encoding="utf-8")

    exit_code = main(["--clear-log", "--output-dir", str(output_dir)])

    assert exit_code == 0
    assert list(output_dir.iterdir()) == []
