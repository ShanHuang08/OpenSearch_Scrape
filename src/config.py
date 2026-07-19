from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - only used before dependencies are installed
    load_dotenv = None


DEFAULT_DASHBOARD_URL = (
    "https://opensearch-dashboard-dev.newnextgen.site/app/data-explorer/discover"
)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} 必須是 true 或 false。")


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    username: str = ""
    password: str = ""
    dashboard_url: str = DEFAULT_DASHBOARD_URL
    # CLI runs are headless by default; use --no-headless when debugging.
    headless: bool = True
    scroll_wait_ms: int = Field(default=1000, ge=100)
    no_new_data_limit: int = Field(default=3, ge=1)
    timeout_seconds: int = Field(default=300, ge=10)
    output_dir: Path = Path("output")

    google_sheets_enabled: bool = False
    google_spreadsheet_id: str = ""
    google_worksheet_name: str = "OpenSearch Logs"
    google_auth_mode: str = "service-account"
    google_credentials_file: Path | None = None
    google_token_file: Path = Path("google-token.json")
    google_write_mode: str = "upsert"
    google_batch_size: int = Field(default=100, ge=1, le=1000)

    @field_validator("google_write_mode")
    @classmethod
    def validate_write_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"upsert", "append"}:
            raise ValueError("GOOGLE_WRITE_MODE 只接受 upsert 或 append。")
        return normalized

    @field_validator("google_auth_mode")
    @classmethod
    def validate_auth_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"service-account", "oauth"}:
            raise ValueError("GOOGLE_AUTH_MODE 只接受 service-account 或 oauth。")
        return normalized

    @classmethod
    def from_env(cls, env_file: Path | None = Path(".env")) -> Settings:
        if load_dotenv is not None and env_file is not None:
            # The CLI is commonly launched from the project directory, but an
            # installed console script may be launched from another directory.
            # Try the requested path first, then the repository root next to
            # ``src`` so credentials are loaded consistently in both cases.
            candidates = [Path(env_file)]
            project_env = Path(__file__).resolve().parents[2] / ".env"
            if project_env not in candidates:
                candidates.append(project_env)
            for candidate in candidates:
                if candidate.is_file():
                    load_dotenv(candidate, override=False)
                    break

        credentials_path = os.getenv("GOOGLE_CREDENTIALS_FILE", "").strip()
        return cls(
            username=os.getenv("OPENSEARCH_USERNAME", "").strip(),
            password=os.getenv("OPENSEARCH_PASSWORD", ""),
            dashboard_url=os.getenv("OPENSEARCH_DASHBOARD_URL", DEFAULT_DASHBOARD_URL).strip(),
            headless=_env_bool("OPENSEARCH_HEADLESS", True),
            scroll_wait_ms=int(os.getenv("OPENSEARCH_SCROLL_WAIT_MS", "1000")),
            no_new_data_limit=int(os.getenv("OPENSEARCH_NO_NEW_DATA_LIMIT", "3")),
            timeout_seconds=int(os.getenv("OPENSEARCH_TIMEOUT_SECONDS", "300")),
            output_dir=Path(os.getenv("OPENSEARCH_OUTPUT_DIR", "output")),
            google_sheets_enabled=_env_bool("GOOGLE_SHEETS_ENABLED", False),
            google_spreadsheet_id=os.getenv("GOOGLE_SPREADSHEET_ID", "").strip(),
            google_worksheet_name=os.getenv(
                "GOOGLE_WORKSHEET_NAME", "OpenSearch Logs"
            ).strip(),
            google_auth_mode=os.getenv("GOOGLE_AUTH_MODE", "service-account"),
            google_credentials_file=Path(credentials_path) if credentials_path else None,
            google_token_file=Path(
                os.getenv("GOOGLE_TOKEN_FILE", "google-token.json").strip()
                or "google-token.json"
            ),
            google_write_mode=os.getenv("GOOGLE_WRITE_MODE", "upsert"),
            google_batch_size=int(os.getenv("GOOGLE_BATCH_SIZE", "100")),
        )

    def validate_opensearch_credentials(self) -> None:
        missing = []
        if not self.username:
            missing.append("OPENSEARCH_USERNAME")
        if not self.password:
            missing.append("OPENSEARCH_PASSWORD")
        if missing:
            raise ValueError(f"缺少 OpenSearch 設定：{', '.join(missing)}")

    def validate_google_settings(self) -> None:
        if not self.google_sheets_enabled:
            return
        if not self.google_spreadsheet_id:
            raise ValueError("GOOGLE_SHEETS_ENABLED=true 時必須設定 GOOGLE_SPREADSHEET_ID。")
        if not self.google_credentials_file:
            raise ValueError("Google Sheets 已啟用，但未設定 GOOGLE_CREDENTIALS_FILE。")
        if not self.google_credentials_file.is_file():
            raise ValueError("GOOGLE_CREDENTIALS_FILE 指向的檔案不存在。")
