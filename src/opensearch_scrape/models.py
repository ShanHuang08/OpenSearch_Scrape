from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ParsedField(BaseModel):
    model_config = ConfigDict(frozen=True)

    original: str | None
    rendered: str
    decoded: str | None = None
    kind: Literal["missing", "empty", "null", "json", "text", "url-encoded"]
    warning: str | None = None


class RawLogRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    requestTime: str | None = None
    requestBody: str | None = None
    responseBody: str | None = None
    url: str | None = None
    operatorData: str | None = None
    operatorResponse: str | None = None
    operatorUrl: str | None = None
    error: str | None = None
    timeTaken: str | None = None


class LogRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    record_key: str
    scraped_at: datetime
    environment: str
    index_pattern_name: str
    index_pattern_id: str
    query: str
    time_from: str
    time_to: str
    request_time: str | None = None
    username: str | None = None
    game_code: str | None = None
    request_body: ParsedField
    response_body: ParsedField
    url: ParsedField
    operator_data: ParsedField
    operator_response: ParsedField
    operator_url: ParsedField
    error: ParsedField
    time_taken: ParsedField
    parse_warnings: list[str] = Field(default_factory=list)


class ScrapeResult(BaseModel):
    records: list[LogRecord]
    expected_total: int | None = None
    human_time_range: str | None = None
    duplicate_count: int = 0
    status: Literal["success", "partial", "failed"] = "success"
    incomplete_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
