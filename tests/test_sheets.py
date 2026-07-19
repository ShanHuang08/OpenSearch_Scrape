import json
import sys
from datetime import UTC, datetime
from types import ModuleType

from opensearch_scrape.config import Settings
from opensearch_scrape.environments import resolve_environment
from opensearch_scrape.models import RawLogRow
from opensearch_scrape.parsing import normalize_row
from opensearch_scrape.sheets import (
    GOOGLE_SHEETS_CELL_CHAR_LIMIT,
    LEGACY_SHEET_HEADERS,
    SHEET_HEADERS,
    GoogleSheetsWriter,
    _record_key_from_remark,
    record_to_legacy_sheet_row,
    record_to_sheet_row,
)


def test_sheet_row_matches_headers() -> None:
    record = normalize_row(
        RawLogRow(
            operatorData='{"username":"user-1","gameCode":"game-2"}',
            url="/api/v1/groove",
        ),
        scraped_at=datetime(2026, 7, 19, tzinfo=UTC),
        environment=resolve_environment("QA"),
        query='"groove"',
        time_from="now-1w",
        time_to="now",
    )
    row = record_to_sheet_row(record)
    assert len(row) == len(SHEET_HEADERS)
    assert row[SHEET_HEADERS.index("environment")] == "QA"
    assert row[SHEET_HEADERS.index("username")] == "user-1"
    assert row[SHEET_HEADERS.index("gameCode")] == "game-2"


def test_documented_cell_limit_is_explicit() -> None:
    assert GOOGLE_SHEETS_CELL_CHAR_LIMIT == 50_000


def test_legacy_sheet_row_matches_existing_target_layout() -> None:
    record = normalize_row(
        RawLogRow(
            requestTime="Jul 14, 2026 @ 11:23:52.129",
            requestBody='{"token":"abc"}',
            responseBody='{"balance":50000000}',
            operatorData='{"username":"user-1","gameCode":"game-2"}',
            operatorResponse='{"status":"SC_OK"}',
            url="/api/v1/wallet",
            operatorUrl="https://operator.example/wallet",
            timeTaken="106",
        ),
        scraped_at=datetime(2026, 7, 19, tzinfo=UTC),
        environment=resolve_environment("QA"),
        query='"user-1"',
        time_from="now-1w",
        time_to="now",
    )

    row = record_to_legacy_sheet_row(record)

    assert len(row) == len(LEGACY_SHEET_HEADERS)
    assert row[LEGACY_SHEET_HEADERS.index("username")] == "user-1"
    assert row[LEGACY_SHEET_HEADERS.index("game code")] == "game-2"
    assert _record_key_from_remark(row[-1]) == record.record_key


def test_record_key_is_not_guessed_from_invalid_remark() -> None:
    assert _record_key_from_remark("recordKey=not-a-real-key") is None


def test_oauth_migrates_and_refreshes_existing_token(tmp_path, monkeypatch) -> None:
    token_path = tmp_path / "google-token.json"
    token_path.write_text(
        json.dumps(
            {
                "access_token": "expired-access-token",
                "refresh_token": "refresh-token",
                "client_id": "client-id",
                "client_secret": "client-secret",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        ),
        encoding="utf-8",
    )

    class FakeCredentials:
        refresh_token = "refresh-token"
        valid = False
        refreshed = False

        @classmethod
        def from_authorized_user_info(cls, info, scopes):
            assert info["token"] == "expired-access-token"
            assert scopes == ["https://www.googleapis.com/auth/spreadsheets"]
            return cls()

        def refresh(self, request):
            self.refreshed = True
            self.valid = True

        def to_json(self):
            return json.dumps(
                {
                    "token": "new-access-token",
                    "refresh_token": self.refresh_token,
                }
            )

    class FakeFlow:
        @classmethod
        def from_client_secrets_file(cls, *args, **kwargs):
            raise AssertionError("existing refresh token should avoid browser authorization")

    modules = {
        "google": ModuleType("google"),
        "google.auth": ModuleType("google.auth"),
        "google.auth.transport": ModuleType("google.auth.transport"),
        "google.auth.transport.requests": ModuleType("google.auth.transport.requests"),
        "google.oauth2": ModuleType("google.oauth2"),
        "google.oauth2.credentials": ModuleType("google.oauth2.credentials"),
        "google_auth_oauthlib": ModuleType("google_auth_oauthlib"),
        "google_auth_oauthlib.flow": ModuleType("google_auth_oauthlib.flow"),
    }
    modules["google.auth.transport.requests"].Request = object
    modules["google.oauth2.credentials"].Credentials = FakeCredentials
    modules["google_auth_oauthlib.flow"].InstalledAppFlow = FakeFlow
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    writer = GoogleSheetsWriter(
        Settings(
            google_auth_mode="oauth",
            google_credentials_file=tmp_path / "client-secret.json",
            google_token_file=token_path,
        )
    )

    credentials = writer._oauth_credentials()

    assert credentials.refreshed is True
    assert json.loads(token_path.read_text(encoding="utf-8"))["token"] == "new-access-token"


def test_writer_upserts_existing_legacy_sheet_row(tmp_path, monkeypatch) -> None:
    record = normalize_row(
        RawLogRow(
            requestTime="Jul 14, 2026 @ 11:23:52.129",
            operatorData='{"username":"user-1","gameCode":"game-2"}',
            url="/api/v1/wallet",
        ),
        scraped_at=datetime(2026, 7, 19, tzinfo=UTC),
        environment=resolve_environment("QA"),
        query='"user-1"',
        time_from="now-1w",
        time_to="now",
    )
    credentials_file = tmp_path / "client-secret.json"
    credentials_file.write_text("{}", encoding="utf-8")

    class FakeWorksheet:
        batch_updates = []
        appended_rows = []

        def row_values(self, row_number):
            assert row_number == 1
            return LEGACY_SHEET_HEADERS

        def col_values(self, column_number):
            assert column_number == 9
            return ["remark", f"recordKey={record.record_key}"]

        def batch_update(self, updates, value_input_option):
            assert value_input_option == "RAW"
            self.batch_updates.extend(updates)

        def append_rows(self, rows, value_input_option):
            self.appended_rows.extend(rows)

    worksheet = FakeWorksheet()

    class FakeSpreadsheet:
        def worksheet(self, name):
            assert name == "工作表1"
            return worksheet

    class FakeClient:
        def open_by_key(self, spreadsheet_id):
            assert spreadsheet_id == "spreadsheet-id"
            return FakeSpreadsheet()

    class FakeAPIError(Exception):
        pass

    class FakeRequestException(Exception):
        pass

    fake_gspread = ModuleType("gspread")
    fake_gspread.exceptions = type("Exceptions", (), {"APIError": FakeAPIError})
    fake_requests = ModuleType("requests")
    fake_requests.RequestException = FakeRequestException
    monkeypatch.setitem(sys.modules, "gspread", fake_gspread)
    monkeypatch.setitem(sys.modules, "requests", fake_requests)

    writer = GoogleSheetsWriter(
        Settings(
            google_sheets_enabled=True,
            google_spreadsheet_id="spreadsheet-id",
            google_worksheet_name="工作表1",
            google_auth_mode="oauth",
            google_credentials_file=credentials_file,
        )
    )
    monkeypatch.setattr(writer, "_authorize", lambda gspread: FakeClient())

    result = writer.write([record])

    assert result.added == 0
    assert result.updated == 1
    assert worksheet.batch_updates[0]["range"] == "A2:I2"
    assert worksheet.appended_rows == []
