from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import unquote

from environments import EnvironmentSpec
from models import LogRecord, ParsedField, RawLogRow

PERCENT_ENCODED = re.compile(r"%[0-9a-fA-F]{2}")
IDENTITY_NAMES = {
    "username": "username",
    "user_name": "username",
    "gamecode": "gameCode",
    "game_code": "gameCode",
}


def _parse_json_layers(value: str, max_layers: int = 3) -> tuple[Any, bool]:
    current: Any = value
    parsed = False
    for _ in range(max_layers):
        if not isinstance(current, str):
            break
        candidate = current.strip()
        if not candidate:
            break
        try:
            current = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            break
        parsed = True
    return current, parsed


def parse_field(value: str | None) -> tuple[ParsedField, Any | None]:
    if value is None:
        return ParsedField(original=None, rendered="N/A", kind="missing"), None
    if value == "":
        return ParsedField(original="", rendered="(empty)", kind="empty"), None

    parsed_value, parsed = _parse_json_layers(value)
    if parsed:
        return (
            ParsedField(
                original=value,
                rendered=json.dumps(parsed_value, ensure_ascii=False, indent=2),
                kind="null" if parsed_value is None else "json",
            ),
            parsed_value,
        )

    decoded = None
    if PERCENT_ENCODED.search(value):
        decoded = unquote(value)
        decoded_value, decoded_parsed = _parse_json_layers(decoded)
        if decoded_parsed:
            return (
                ParsedField(
                    original=value,
                    decoded=decoded,
                    rendered=json.dumps(decoded_value, ensure_ascii=False, indent=2),
                    kind="null" if decoded_value is None else "json",
                ),
                decoded_value,
            )
        return (
            ParsedField(
                original=value,
                decoded=decoded,
                rendered=decoded,
                kind="url-encoded",
            ),
            None,
        )

    stripped = value.lstrip()
    warning = None
    if stripped.startswith(("{", "[")):
        warning = "內容疑似 JSON，但解析失敗；已保留原始文字。"
    return ParsedField(original=value, rendered=value, kind="text", warning=warning), None


def _normalize_identity_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def extract_operator_identity(value: Any) -> tuple[str | None, str | None]:
    found: dict[str, str] = {}

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                normalized = _normalize_identity_key(str(key))
                canonical = IDENTITY_NAMES.get(normalized)
                if canonical and canonical not in found and child is not None:
                    found[canonical] = str(child)
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return found.get("username"), found.get("gameCode")


def build_record_key(environment: str, row: RawLogRow) -> str:
    payload = {"environment": environment, **row.model_dump(mode="json")}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_row(
    row: RawLogRow,
    *,
    scraped_at: datetime,
    environment: EnvironmentSpec,
    query: str,
    time_from: str,
    time_to: str,
) -> LogRecord:
    request_body, _ = parse_field(row.requestBody)
    response_body, _ = parse_field(row.responseBody)
    url, _ = parse_field(row.url)
    operator_data, operator_data_json = parse_field(row.operatorData)
    operator_response, _ = parse_field(row.operatorResponse)
    operator_url, _ = parse_field(row.operatorUrl)
    error, _ = parse_field(row.error)
    time_taken, _ = parse_field(row.timeTaken)

    username, game_code = extract_operator_identity(operator_data_json)
    warnings = []
    for name, field in (
        ("requestBody", request_body),
        ("responseBody", response_body),
        ("url", url),
        ("operatorData", operator_data),
        ("operatorResponse", operator_response),
        ("operatorUrl", operator_url),
        ("error", error),
        ("timeTaken", time_taken),
    ):
        if field.warning:
            warnings.append(f"{name}: {field.warning}")
    if operator_data_json is not None and username is None:
        warnings.append("operatorData: 找不到 username。")
    if operator_data_json is not None and game_code is None:
        warnings.append("operatorData: 找不到 gameCode。")

    return LogRecord(
        record_key=build_record_key(environment.name, row),
        scraped_at=scraped_at,
        environment=environment.name,
        index_pattern_name=environment.pattern_name,
        index_pattern_id=environment.index_pattern_id,
        query=query,
        time_from=time_from,
        time_to=time_to,
        request_time=row.requestTime,
        username=username,
        game_code=game_code,
        request_body=request_body,
        response_body=response_body,
        url=url,
        operator_data=operator_data,
        operator_response=operator_response,
        operator_url=operator_url,
        error=error,
        time_taken=time_taken,
        parse_warnings=warnings,
    )
