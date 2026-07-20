from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import TypeVar
from urllib.parse import urlparse

from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from config import Settings
from models import LogRecord

SHEET_HEADERS = [
    "recordKey",
    "scrapedAt",
    "environment",
    "indexPatternName",
    "indexPatternId",
    "query",
    "timeFrom",
    "timeTo",
    "username",
    "gameCode",
    "requestBody",
    "responseBody",
    "url",
    "decodedUrl",
    "operatorData",
    "operatorResponse",
    "operatorUrl",
    "decodedOperatorUrl",
    "error",
    "timeTaken",
    "parseWarnings",
]

# Compatibility layout used by the existing target spreadsheet.  The record
# key is kept in ``remark`` so upsert remains deterministic without changing
# the user's established columns.
LEGACY_SHEET_HEADERS = [
    "username",
    "game code",
    "requestBody",
    "responseBody",
    "url",
    "operatorData",
    "operatorResponse",
    "operatorUrl",
    "remark",
]
LEGACY_COLUMN_WIDTHS = [100, 100, 201, 217, 100, 403, 178, 100, 100]

GOOGLE_SHEETS_CELL_CHAR_LIMIT = 50_000
GOOGLE_SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
T = TypeVar("T")
PROVIDER_URL_PATTERN = re.compile(r"^/api/v1/([^/]+)/", re.IGNORECASE)


@dataclass(slots=True)
class SheetsWriteResult:
    status: str
    attempted: int = 0
    added: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    message: str | None = None


def _read_credentials_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Google 憑證檔無法讀取或不是有效 JSON：{path}。"
            "請確認 GOOGLE_CREDENTIALS_FILE 指向正確的憑證檔。"
        ) from exc


def worksheet_name_from_records(records: list[LogRecord]) -> str:
    """Derive a stable worksheet name from API provider URLs."""
    provider_names: set[str] = set()
    for record in records:
        raw_url = record.url.original or ""
        path = urlparse(raw_url).path if "://" in raw_url else raw_url.split("?", 1)[0]
        match = PROVIDER_URL_PATTERN.match(path.strip())
        if match:
            provider_names.add(match.group(1))

    if not provider_names:
        raise ValueError(
            "無法從 log URL 推導 Google worksheet 名稱；"
            "請設定 GOOGLE_WORKSHEET_NAME，或確認 URL 符合 /api/v1/{provider}/...。"
        )
    if len(provider_names) > 1:
        names = ", ".join(sorted(provider_names))
        raise ValueError(
            f"同一批 log 包含多個 provider（{names}），無法決定 Google worksheet；"
            "請設定 GOOGLE_WORKSHEET_NAME。"
        )
    return provider_names.pop()


def record_to_sheet_row(record: LogRecord) -> list[str]:
    return [
        record.record_key,
        record.scraped_at.isoformat(),
        record.environment,
        record.index_pattern_name,
        record.index_pattern_id,
        record.query,
        record.time_from,
        record.time_to,
        record.username or "",
        record.game_code or "",
        record.request_body.rendered,
        record.response_body.rendered,
        record.url.original or "",
        record.url.decoded or "",
        record.operator_data.rendered,
        record.operator_response.rendered,
        record.operator_url.original or "",
        record.operator_url.decoded or "",
        record.error.rendered,
        record.time_taken.rendered,
        "\n".join(record.parse_warnings),
    ]


def record_to_legacy_sheet_row(record: LogRecord) -> list[str]:
    remark_parts = [
        f"recordKey={record.record_key}",
        f"scrapedAt={record.scraped_at.isoformat()}",
        f"requestTime={record.request_time or ''}",
        f"timeTaken={record.time_taken.rendered}",
        f"error={record.error.rendered}",
    ]
    return [
        record.username or "",
        record.game_code or "",
        record.request_body.rendered,
        record.response_body.rendered,
        record.url.original or "",
        record.operator_data.rendered,
        record.operator_response.rendered,
        record.operator_url.original or "",
        "; ".join(remark_parts),
    ]


def _record_key_from_remark(value: str) -> str | None:
    match = re.search(r"(?:^|;\s*)recordKey=([0-9a-f]{64})(?:;|$)", value)
    return match.group(1) if match else None


def _chunks(values: list[T], size: int) -> Iterable[list[T]]:
    iterator = iter(values)
    while chunk := list(islice(iterator, size)):
        yield chunk


def _column_name(number: int) -> str:
    value = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        value = chr(65 + remainder) + value
    return value


def _legacy_column_width_requests(sheet_id: int) -> list[dict]:
    return [
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": index,
                    "endIndex": index + 1,
                },
                "properties": {"pixelSize": width},
                "fields": "pixelSize",
            }
        }
        for index, width in enumerate(LEGACY_COLUMN_WIDTHS)
    ]


def _legacy_wrap_requests(sheet_id: int) -> list[dict]:
    return [
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "startColumnIndex": column_index,
                    "endColumnIndex": column_index + 1,
                },
                "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
                "fields": "userEnteredFormat.wrapStrategy",
            }
        }
        for column_index in (1, 4)
    ]


class GoogleSheetsWriter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _oauth_credentials(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:  # pragma: no cover - integration dependency
            raise RuntimeError(
                "OAuth 模式缺少 google-auth-oauthlib，請先安裝專案 dependencies。"
            ) from exc

        token_path = self.settings.google_token_file
        credentials = None
        must_refresh = False
        if token_path.is_file():
            token_info = json.loads(token_path.read_text(encoding="utf-8"))
            # Migrate the token file created by the original Node integration
            # test to google-auth's standard authorized-user representation.
            if "token" not in token_info and token_info.get("access_token"):
                token_info["token"] = token_info["access_token"]
            must_refresh = "expiry" not in token_info
            credentials = Credentials.from_authorized_user_info(
                token_info,
                scopes=GOOGLE_SHEETS_SCOPES,
            )

        if credentials and credentials.refresh_token and (
            must_refresh or not credentials.valid
        ):
            credentials.refresh(Request())

        if not credentials or not credentials.valid:
            credentials_data = _read_credentials_json(self.settings.google_credentials_file)
            if not (credentials_data.get("installed") or credentials_data.get("web")):
                raise ValueError(
                    "GOOGLE_AUTH_MODE=oauth 需要 OAuth client secret JSON（通常是 "
                    "client_secret_*.json）；目前檔案格式不符合。"
                )
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.settings.google_credentials_file),
                    scopes=GOOGLE_SHEETS_SCOPES,
                )
            except Exception as exc:
                raise ValueError(
                    "OAuth 憑證載入失敗。請確認 GOOGLE_CREDENTIALS_FILE 是 OAuth client "
                    "secret JSON，且 GOOGLE_AUTH_MODE=oauth。"
                ) from exc
            credentials = flow.run_local_server(
                host="localhost",
                port=0,
                open_browser=True,
                access_type="offline",
                prompt="consent",
            )

        self._save_oauth_token(token_path, credentials.to_json())
        return credentials

    @staticmethod
    def _save_oauth_token(token_path: Path, contents: str) -> None:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = token_path.with_suffix(token_path.suffix + ".tmp")
        temporary_path.write_text(contents, encoding="utf-8")
        temporary_path.replace(token_path)

    def _authorize(self, gspread):
        if self.settings.google_auth_mode == "service-account":
            try:
                from google.oauth2.service_account import Credentials
            except ImportError as exc:  # pragma: no cover - integration dependency
                raise RuntimeError("缺少 google-auth，請先安裝專案 dependencies。") from exc
            credentials_data = _read_credentials_json(self.settings.google_credentials_file)
            if credentials_data.get("type") != "service_account":
                raise ValueError(
                    "GOOGLE_AUTH_MODE=service-account 需要 Service Account JSON；"
                    "目前檔案看起來是 OAuth client secret。"
                    "若使用 client_secret_*.json，請改成 GOOGLE_AUTH_MODE=oauth。"
                )
            try:
                credentials = Credentials.from_service_account_file(
                    str(self.settings.google_credentials_file),
                    scopes=GOOGLE_SHEETS_SCOPES,
                )
            except Exception as exc:
                raise ValueError(
                    "Service Account 憑證載入失敗。請重新下載 Service Account JSON，"
                    "並確認 GOOGLE_CREDENTIALS_FILE 路徑正確。"
                ) from exc
        else:
            credentials = self._oauth_credentials()
        return gspread.authorize(credentials)

    def write(self, records: list[LogRecord]) -> SheetsWriteResult:
        if not self.settings.google_sheets_enabled:
            return SheetsWriteResult(
                status="skipped", attempted=len(records), skipped=len(records), message="未啟用"
            )

        self.settings.validate_google_settings()

        try:
            import gspread
            from requests import RequestException
        except ImportError as exc:  # pragma: no cover - integration dependency
            raise RuntimeError("缺少 gspread 或 requests，請先安裝專案 dependencies。") from exc

        client = self._authorize(gspread)
        spreadsheet = client.open_by_key(self.settings.google_spreadsheet_id)
        worksheet_name = self.settings.google_worksheet_name or worksheet_name_from_records(records)
        worksheet_created = False
        try:
            worksheet = spreadsheet.worksheet(worksheet_name)
        except gspread.exceptions.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                title=worksheet_name,
                rows=1000,
                cols=len(LEGACY_SHEET_HEADERS),
            )
            worksheet_created = True

        retrying = Retrying(
            retry=retry_if_exception_type((gspread.exceptions.APIError, RequestException)),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            reraise=True,
        )

        def api_call(function, *args, **kwargs):
            return retrying(function, *args, **kwargs)

        current_headers = api_call(worksheet.row_values, 1)
        if worksheet_created or not current_headers:
            api_call(worksheet.update, [LEGACY_SHEET_HEADERS], "A1")
            api_call(worksheet.freeze, rows=1)
            api_call(
                spreadsheet.batch_update,
                {
                    "requests": [
                        *_legacy_column_width_requests(worksheet.id),
                        *_legacy_wrap_requests(worksheet.id),
                    ]
                },
            )
            active_headers = LEGACY_SHEET_HEADERS
            row_builder = record_to_legacy_sheet_row
        elif current_headers == SHEET_HEADERS:
            active_headers = SHEET_HEADERS
            row_builder = record_to_sheet_row
        elif current_headers == LEGACY_SHEET_HEADERS:
            active_headers = LEGACY_SHEET_HEADERS
            row_builder = record_to_legacy_sheet_row
        else:
            raise ValueError("Google Sheet 表頭與需求不相容，已停止寫入以避免覆蓋資料。")

        rows = [row_builder(record) for record in records]
        oversized = [
            (row_index + 1, active_headers[column_index], len(value))
            for row_index, row in enumerate(rows)
            for column_index, value in enumerate(row)
            if len(value) > GOOGLE_SHEETS_CELL_CHAR_LIMIT
        ]
        if oversized:
            row_number, column_name, length = oversized[0]
            raise ValueError(
                "Google Sheets 儲存格內容過大，已停止寫入且保留 Markdown："
                f"資料列 {row_number}、欄位 {column_name}、{length} 字元。"
            )
        result = SheetsWriteResult(
            status="success",
            attempted=len(rows),
            message=f"worksheet={worksheet_name}",
        )
        if not rows:
            return result

        if self.settings.google_write_mode == "append":
            for chunk in _chunks(rows, self.settings.google_batch_size):
                api_call(worksheet.append_rows, chunk, value_input_option="RAW")
                result.added += len(chunk)
            return result

        if active_headers == LEGACY_SHEET_HEADERS:
            existing_values = api_call(worksheet.col_values, 9)[1:]
            existing_keys = [_record_key_from_remark(value) for value in existing_values]
        else:
            existing_keys = api_call(worksheet.col_values, 1)[1:]
        key_to_row = {
            key: row_number
            for row_number, key in enumerate(existing_keys, start=2)
            if key
        }
        updates = []
        additions = []
        last_column = _column_name(len(active_headers))
        for record, row in zip(records, rows, strict=True):
            existing_row = key_to_row.get(record.record_key)
            if existing_row is None:
                additions.append(row)
            else:
                updates.append(
                    {"range": f"A{existing_row}:{last_column}{existing_row}", "values": [row]}
                )

        for chunk in _chunks(updates, self.settings.google_batch_size):
            api_call(worksheet.batch_update, chunk, value_input_option="RAW")
            result.updated += len(chunk)
        for chunk in _chunks(additions, self.settings.google_batch_size):
            api_call(worksheet.append_rows, chunk, value_input_option="RAW")
            result.added += len(chunk)
        return result
