from __future__ import annotations

import argparse
import plistlib
import shutil
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config import Settings
from environments import resolve_environment
from markdown import render_markdown, write_markdown
from models import ScrapeResult
from parsing import normalize_row
from query import build_discover_url, build_kql, parse_keyword_expression
from scraper import OpenSearchScraper, ScrapeError
from sheets import GoogleSheetsWriter

TAIPEI = ZoneInfo("Asia/Taipei")
GOOGLE_SHEETS_URL_TEMPLATE = "https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"


def _macos_default_browser_bundle_id() -> str | None:
    try:
        result = subprocess.run(
            [
                "defaults",
                "export",
                "com.apple.LaunchServices/com.apple.launchservices.secure",
                "-",
            ],
            capture_output=True,
            check=True,
        )
        preferences = plistlib.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException):
        return None

    handlers = preferences.get("LSHandlers", [])
    for scheme in ("https", "http"):
        for handler in handlers:
            if handler.get("LSHandlerURLScheme") == scheme:
                bundle_id = handler.get("LSHandlerRoleAll")
                if bundle_id:
                    return bundle_id
    return None


def open_in_default_browser(url: str) -> bool:
    """Open a URL with the system default browser."""
    if sys.platform == "darwin":
        # A local Markdown file follows the `.md` file association when opened
        # with `open`; explicitly target the browser that handles HTTPS URLs.
        bundle_id = _macos_default_browser_bundle_id()
        if bundle_id:
            result = subprocess.run(["open", "-b", bundle_id, url], check=False)
            return result.returncode == 0
    return webbrowser.open(url)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="open-search",
        description="從 OpenSearch Dashboard 擷取 log 並輸出 Markdown。",
        epilog=(
            "範例：\n"
            "  open-search -k cs20260714032331\n"
            "  open-search -k cs20260714032331 -e QA\n"
            "  open-search -k cs20260714032331 -e QA --google-sheets"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--env", "-e", dest="environment", help="QA 或 staging（stg 亦可）")
    parser.add_argument("--environment", dest="environment", help=argparse.SUPPRESS)
    parser.add_argument(
        "--keyword", "-k", action="append", nargs="+", dest="keywords",
        help="搜尋關鍵字；可寫成 'groove or cs123' 或重複使用 --keyword",
    )
    parser.add_argument("--operator", choices=("or", "and"), default="or")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "只顯示 KQL 與 OpenSearch URL，不登入、抓取或寫入資料；"
            "搭配 --google-sheets 時會開啟目標 Sheet"
        ),
    )
    parser.add_argument("--time-from", default="now-1w")
    parser.add_argument("--time-to", default="now")
    parser.add_argument(
        "--max-records",
        type=int,
        default=50,
        help="最多擷取筆數（預設 50；使用 0 以下會被拒絕）",
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--clear-log",
        "--clear_log",
        action="store_true",
        dest="clear_log",
        help="清空設定的 output 目錄；單獨使用時清空後退出",
    )
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="以無頭模式執行瀏覽器（預設）；除錯時可使用 --no-headless",
    )
    parser.add_argument(
        "--open-output",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Markdown 產生後用系統預設瀏覽器開啟（預設開啟）",
    )
    parser.add_argument(
        "--google-sheets",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="寫入 Google Sheets；預設依 GOOGLE_SHEETS_ENABLED（預設 false）",
    )
    return parser


def _interactive_inputs(
    environment: str | None,
    keywords: list[list[str]] | None,
) -> tuple[str, list[str], str | None]:
    selected_environment = environment or input("請輸入環境（QA/staging）：").strip()
    selected_keywords = keywords
    if not selected_keywords:
        raw = input("請輸入搜尋關鍵字（多個關鍵字以逗號分隔）：")
        selected_keywords = [[part.strip() for part in raw.split(",")]]
    parsed_keywords, expression_operator = parse_keyword_expression(
        [item for group in selected_keywords for item in group]
    )
    return selected_environment, parsed_keywords, expression_operator


def _settings_with_overrides(settings: Settings, args: argparse.Namespace) -> Settings:
    updates = {}
    if args.output_dir is not None:
        updates["output_dir"] = args.output_dir
    if args.headless is not None:
        updates["headless"] = args.headless
    if args.google_sheets is not None:
        updates["google_sheets_enabled"] = args.google_sheets
    return settings.model_copy(update=updates)


def clear_output_directory(output_dir: Path) -> int:
    """Remove every item inside an output directory while preserving the directory."""
    requested_path = output_dir.expanduser()
    if requested_path.is_symlink():
        raise ValueError("拒絕清空符號連結指向的 output 目錄。")

    target = requested_path.resolve()
    protected_paths = {
        Path.cwd().resolve(),
        Path.home().resolve(),
        Path(target.anchor).resolve(),
    }
    if target in protected_paths:
        raise ValueError(f"拒絕清空不安全的 output 路徑：{target}")
    if target.exists() and not target.is_dir():
        raise ValueError(f"output 路徑不是資料夾：{target}")

    target.mkdir(parents=True, exist_ok=True)
    removed = 0
    for child in target.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
        removed += 1
    return removed


def google_spreadsheet_url(spreadsheet_id: str) -> str:
    normalized_id = spreadsheet_id.strip()
    if not normalized_id:
        raise ValueError("開啟 Google Sheet 前必須設定 GOOGLE_SPREADSHEET_ID。")
    return GOOGLE_SHEETS_URL_TEMPLATE.format(spreadsheet_id=normalized_id)


def open_google_spreadsheet(spreadsheet_id: str) -> bool:
    """Open a Google spreadsheet in the system default browser."""
    url = google_spreadsheet_url(spreadsheet_id)
    try:
        opened = webbrowser.open(url)
    except Exception as exc:
        print(
            f"警告：開啟 Google Sheet 失敗（{type(exc).__name__}）。",
            file=sys.stderr,
        )
        return False
    if not opened:
        print("警告：無法以系統預設瀏覽器開啟 Google Sheet。", file=sys.stderr)
        return False
    print(f"Google Sheet 已開啟：{url}")
    return True


def run(args: argparse.Namespace) -> int:
    settings = _settings_with_overrides(Settings.from_env(), args)
    if args.clear_log:
        removed = clear_output_directory(settings.output_dir)
        print(f"Output 已清空：{settings.output_dir.resolve()}（移除 {removed} 個項目）")
        if args.environment is None and not args.keywords:
            return 0

    environment_input, keywords, expression_operator = _interactive_inputs(
        args.environment,
        args.keywords,
    )
    environment = resolve_environment(environment_input)
    if args.max_records is not None and args.max_records < 1:
        raise ValueError("--max-records 必須大於 0。")

    kql = build_kql(keywords, expression_operator or args.operator)
    discover_url = build_discover_url(
        settings.dashboard_url,
        environment,
        kql,
        args.time_from,
        args.time_to,
    )
    executed_at = datetime.now(TAIPEI)
    print(f"開始查詢：環境={environment.name}，KQL={kql}")

    if args.dry_run:
        print(f"KQL: {kql}")
        print(f"OpenSearch URL: {discover_url}")
        if settings.google_sheets_enabled:
            open_google_spreadsheet(settings.google_spreadsheet_id)
        return 0

    raw_result = OpenSearchScraper(
        settings,
        environment,
        kql=kql,
        time_from=args.time_from,
        time_to=args.time_to,
        max_records=args.max_records,
    ).run()
    if raw_result.expected_total == 0:
        raise ScrapeError("OpenSearch 找不到符合條件的 log。")

    # OpenSearch renders newest records first. Reports and downstream writes use
    # chronological order so the Markdown is easier to read from top to bottom.
    records = [
        normalize_row(
            row,
            scraped_at=executed_at,
            environment=environment,
            query=kql,
            time_from=args.time_from,
            time_to=args.time_to,
        )
        for row in reversed(raw_result.rows)
    ]
    status = "partial" if raw_result.incomplete_reason else "success"
    result = ScrapeResult(
        records=records,
        expected_total=raw_result.expected_total,
        human_time_range=raw_result.human_time_range,
        duplicate_count=raw_result.duplicate_count,
        status=status,
        incomplete_reason=raw_result.incomplete_reason,
        warnings=raw_result.warnings,
    )

    markdown = render_markdown(
        result,
        environment=environment,
        keywords=keywords,
        kql=kql,
        time_from=args.time_from,
        time_to=args.time_to,
        executed_at=executed_at,
        discover_url=discover_url,
    )
    output_path = write_markdown(
        markdown,
        output_dir=settings.output_dir,
        environment=environment,
        keywords=keywords,
        executed_at=executed_at,
    )
    print(f"Markdown：{output_path.resolve()}")
    if args.open_output:
        try:
            opened = open_in_default_browser(output_path.resolve().as_uri())
            if not opened:
                print("警告：無法自動開啟系統預設瀏覽器。", file=sys.stderr)
        except Exception as exc:
            print(f"警告：開啟 Markdown 瀏覽器失敗（{type(exc).__name__}）。", file=sys.stderr)

    try:
        sheets_result = GoogleSheetsWriter(settings).write(records)
    except Exception as exc:
        print(
            "Google Sheets：failed "
            f"(Markdown 已保留；錯誤類型={type(exc).__name__}；詳細原因={exc})",
            file=sys.stderr,
        )
        return 2
    print(
        "Google Sheets："
        f"{sheets_result.status} "
        f"(新增={sheets_result.added}, 更新={sheets_result.updated}, "
        f"跳過={sheets_result.skipped}, 失敗={sheets_result.failed}"
        f"{f', {sheets_result.message}' if sheets_result.message else ''})"
    )
    if sheets_result.status == "success":
        open_google_spreadsheet(settings.google_spreadsheet_id)
    if result.status == "partial":
        print(f"警告：{result.incomplete_reason}", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (ValueError, ScrapeError, NotImplementedError) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
