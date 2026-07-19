from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from .config import Settings
from .environments import EnvironmentSpec
from .models import RawLogRow
from .query import build_discover_url


REQUIRED_HEADERS = {
    "requestBody",
    "responseBody",
    "url",
    "operatorData",
    "operatorResponse",
    "operatorUrl",
    "error",
    "timeTaken",
}

HEADER_ALIASES = {"Time": "requestTime", "requestTime": "requestTime"}

LOGIN_SELECTORS = {
    "username": (
        '[data-test-subj="user-name"]',
        'input[aria-label="username_input"]',
        'input[placeholder="Username"]',
    ),
    "password": (
        '[data-test-subj="password"]',
        'input[aria-label="password_input"]',
        'input[placeholder="Password"]',
    ),
    "submit": (
        '[data-test-subj="submit"]',
        'button[aria-label="basicauth_login_button"]',
        'button[type="submit"]',
    ),
}


class ScrapeError(RuntimeError):
    """A user-facing scraping failure that never includes credentials."""


class SecurityChallengeError(ScrapeError):
    """Raised when CAPTCHA, MFA, OTP, or another manual challenge is detected."""


@dataclass(slots=True)
class RawScrapeResult:
    rows: list[RawLogRow] = field(default_factory=list)
    expected_total: int | None = None
    human_time_range: str | None = None
    duplicate_count: int = 0
    incomplete_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


class OpenSearchScraper:
    def __init__(
        self,
        settings: Settings,
        environment: EnvironmentSpec,
        *,
        kql: str,
        time_from: str,
        time_to: str,
        max_records: int | None = None,
    ) -> None:
        self.settings = settings
        self.environment = environment
        self.kql = kql
        self.time_from = time_from
        self.time_to = time_to
        self.max_records = max_records

    def run(self) -> RawScrapeResult:
        self.settings.validate_opensearch_credentials()
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - dependency installation issue
            raise ScrapeError("缺少 Playwright，請先安裝專案 dependencies 與 Chromium。") from exc

        target_url = build_discover_url(
            self.settings.dashboard_url,
            self.environment,
            self.kql,
            self.time_from,
            self.time_to,
        )
        timeout_ms = self.settings.timeout_seconds * 1000
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=self.settings.headless)
                context = browser.new_context()
                page = context.new_page()
                page.set_default_timeout(min(timeout_ms, 30_000))
                try:
                    page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
                    self._login_if_needed(page)
                    self._verify_security_state(page)
                    self._verify_environment(page)
                    self._ensure_query(page)
                    table, header_map = self._find_results_table(page)
                    result = self._collect_rows(page, table, header_map)
                finally:
                    context.close()
                    browser.close()
                return result
        except SecurityChallengeError:
            raise
        except PlaywrightTimeoutError as exc:
            raise ScrapeError("OpenSearch 頁面或查詢載入逾時。") from exc
        except ScrapeError:
            raise
        except Exception as exc:
            raise ScrapeError(f"OpenSearch 擷取失敗：{type(exc).__name__}") from exc

    def _verify_security_state(self, page: Any) -> None:
        challenge_markers = [
            "captcha",
            "recaptcha",
            "verification code",
            "one-time password",
            "enter otp",
            "two-factor authentication",
            "multi-factor authentication",
        ]
        body_text = page.locator("body").inner_text(timeout=10_000).lower()
        if any(marker in body_text for marker in challenge_markers):
            raise SecurityChallengeError("登入遇到 CAPTCHA、MFA 或 OTP，需要人工完成驗證。")
        if page.locator('iframe[src*="captcha" i], [class*="captcha" i], [id*="captcha" i]').count():
            raise SecurityChallengeError("登入遇到 CAPTCHA，需要人工完成驗證。")

    def _login_if_needed(self, page: Any) -> None:
        if "/app/login" not in page.url:
            return

        try:
            page.wait_for_selector("input", state="attached", timeout=30_000)
        except Exception as exc:
            raise ScrapeError("登入頁面載入逾時，找不到登入欄位。") from exc

        self._verify_security_state(page)
        username = self._first_unique_locator(page, LOGIN_SELECTORS["username"])
        password = self._first_unique_locator(page, LOGIN_SELECTORS["password"])
        login_button = self._first_unique_locator(page, LOGIN_SELECTORS["submit"])
        if username.count() != 1 or password.count() != 1 or login_button.count() != 1:
            raise ScrapeError("登入頁面結構已改變，找不到唯一的帳號、密碼或登入按鈕。")
        username.fill(self.settings.username)
        password.fill(self.settings.password)
        login_button.click()
        page.wait_for_url(re.compile(r"/app/(?!login)"), timeout=30_000)
        page.wait_for_load_state("domcontentloaded")

        if "/app/login" in page.url:
            raise ScrapeError("OpenSearch 登入失敗，請檢查帳號、密碼或安全驗證。")

    @staticmethod
    def _first_unique_locator(page: Any, selectors: tuple[str, ...]) -> Any:
        """Choose a stable selector without ever depending on generated element IDs."""
        for selector in selectors:
            locator = page.locator(selector)
            if locator.count() == 1:
                return locator
        return page.locator("[data-opensearch-scrape-missing-login-control]")

    def _verify_environment(self, page: Any) -> None:
        if self.environment.index_pattern_id not in page.url:
            raise ScrapeError("頁面 URL 的 indexPattern 與指定環境不一致，已停止擷取。")

        pattern_label = page.get_by_text(self.environment.pattern_name, exact=True)
        try:
            pattern_label.first.wait_for(state="visible", timeout=20_000)
        except Exception as exc:
            raise ScrapeError("頁面顯示的 index pattern 與指定環境不一致。") from exc

    def _ensure_query(self, page: Any) -> None:
        # Discover renders the search input after the data view has started loading.
        # The direct URL already contains the full KQL, so wait for the result surface
        # before falling back to URL verification when the input is not yet mounted.
        try:
            page.wait_for_selector("table", timeout=30_000)
        except Exception:
            pass
        search_box = page.locator('input[placeholder="Search"]')
        if search_box.count() != 1:
            encoded_query = quote(f"{self.kql} ", safe="")
            if encoded_query in page.url:
                return
            raise ScrapeError("找不到唯一的 OpenSearch 搜尋欄位。")
        current_value = search_box.input_value().strip()
        if current_value == self.kql:
            return

        search_box.fill(self.kql)
        submit = page.get_by_role("button", name="Submit query", exact=True)
        if submit.count() != 1:
            raise ScrapeError("找不到唯一的查詢送出按鈕。")
        submit.click()

    @staticmethod
    def _read_human_time_range(page: Any) -> str | None:
        """Read the visible SuperDatePicker label without relying on a panel ID."""
        locator = page.locator('[data-test-subj="superDatePickerShowDatesButton"]')
        if locator.count() != 1:
            return None
        value = locator.inner_text().strip()
        value = re.sub(r"\s*Show dates\s*$", "", value, flags=re.IGNORECASE)
        return " ".join(value.split()) or None

    def _find_results_table(self, page: Any) -> tuple[Any, dict[str, int]]:
        page.wait_for_selector("table", timeout=30_000)
        tables = page.locator("table")
        table_count = tables.count()
        for index in range(table_count):
            table = tables.nth(index)
            headers = table.locator("thead th").all_inner_texts()
            if not headers:
                headers = table.locator("th").all_inner_texts()
            header_map = self._build_header_map(headers)
            if REQUIRED_HEADERS.issubset(header_map):
                return table, header_map
        raise ScrapeError("找不到包含必要欄位的 OpenSearch 結果表格。")

    @staticmethod
    def _build_header_map(headers: list[str]) -> dict[str, int]:
        mapping: dict[str, int] = {}
        known = REQUIRED_HEADERS | {"requestTime", "Time"}
        for index, text in enumerate(headers):
            compact = " ".join(text.split())
            matched = next(
                (name for name in sorted(known, key=len, reverse=True) if name in compact),
                None,
            )
            if matched:
                mapping[HEADER_ALIASES.get(matched, matched)] = index
        return mapping

    @staticmethod
    def _expected_total(page: Any) -> int | None:
        for text in page.locator("strong").all_inner_texts():
            match = re.search(r"Results\s*\(([\d,]+)(?:/([\d,]+))?\)", text, re.IGNORECASE)
            if match:
                values = [int(value.replace(",", "")) for value in match.groups() if value]
                return max(values)
        return None

    @staticmethod
    def _row_values(row: Any) -> list[str]:
        return row.locator("td").evaluate_all(
            """
            cells => cells.map(cell => {
              const copy = cell.cloneNode(true);
              copy.querySelectorAll('button, svg, [aria-hidden="true"]').forEach(node => node.remove());
              return (copy.innerText || copy.textContent || '').trim();
            })
            """
        )

    @staticmethod
    def _scroll_results(table: Any) -> dict[str, Any]:
        return table.evaluate(
            """
            table => {
              let container = table.parentElement;
              while (container) {
                const style = getComputedStyle(container);
                const canScroll = container.scrollHeight > container.clientHeight + 2 &&
                  ['auto', 'scroll'].includes(style.overflowY);
                if (canScroll) {
                  const before = container.scrollTop;
                  const atBottomBefore = before + container.clientHeight >= container.scrollHeight - 2;
                  container.scrollTop = Math.min(
                    container.scrollHeight,
                    before + Math.max(container.clientHeight * 0.8, 400)
                  );
                  return {
                    found: true,
                    moved: container.scrollTop > before,
                    atBottomBefore,
                    scrollTop: container.scrollTop,
                    scrollHeight: container.scrollHeight,
                    clientHeight: container.clientHeight
                  };
                }
                container = container.parentElement;
              }
              const before = window.scrollY;
              window.scrollBy(0, Math.max(window.innerHeight * 0.8, 400));
              return {found: false, moved: window.scrollY > before, atBottomBefore: false};
            }
            """
        )

    def _collect_rows(self, page: Any, table: Any, header_map: dict[str, int]) -> RawScrapeResult:
        expected_total = self._expected_total(page)
        collected: dict[str, RawLogRow] = {}
        duplicate_count = 0
        no_new_rounds = 0
        start = time.monotonic()
        incomplete_reason = None

        while True:
            before_count = len(collected)
            rows = table.locator("tbody tr")
            row_count = rows.count()
            for index in range(row_count):
                values = self._row_values(rows.nth(index))
                data = {
                    field: values[column] if column < len(values) else None
                    for field, column in header_map.items()
                }
                raw_row = RawLogRow.model_validate(data)
                provisional_key = raw_row.model_dump_json()
                if provisional_key in collected:
                    duplicate_count += 1
                else:
                    collected[provisional_key] = raw_row
                if self.max_records is not None and len(collected) >= self.max_records:
                    break

            if len(collected) == before_count:
                no_new_rounds += 1
            else:
                no_new_rounds = 0

            if self.max_records is not None and len(collected) >= self.max_records:
                break
            if expected_total is not None and len(collected) >= expected_total:
                break
            if time.monotonic() - start >= self.settings.timeout_seconds:
                incomplete_reason = "超過擷取 timeout。"
                break

            scroll_state = self._scroll_results(table)
            if no_new_rounds >= self.settings.no_new_data_limit and (
                scroll_state.get("atBottomBefore") or not scroll_state.get("moved")
            ):
                if expected_total is not None and len(collected) < expected_total:
                    incomplete_reason = "已到達捲動底部，但擷取筆數少於頁面預期筆數。"
                break
            page.wait_for_timeout(self.settings.scroll_wait_ms)

        rows_result = list(collected.values())
        if self.max_records is not None:
            rows_result = rows_result[: self.max_records]
        return RawScrapeResult(
            rows=rows_result,
            expected_total=expected_total,
            human_time_range=self._read_human_time_range(page),
            duplicate_count=duplicate_count,
            incomplete_reason=incomplete_reason,
        )
