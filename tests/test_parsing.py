from datetime import UTC, datetime

from environments import resolve_environment
from models import RawLogRow
from parsing import (
    build_record_key,
    extract_operator_identity,
    normalize_row,
    parse_field,
)


def test_pretty_json() -> None:
    field, parsed = parse_field('{"ok":true,"count":2}')
    assert field.kind == "json"
    assert field.rendered == '{\n  "ok": true,\n  "count": 2\n}'
    assert parsed == {"ok": True, "count": 2}


def test_double_encoded_json_string() -> None:
    field, parsed = parse_field('"{\\"username\\":\\"shan\\"}"')
    assert field.kind == "json"
    assert parsed == {"username": "shan"}


def test_percent_decoding_does_not_convert_plus_to_space() -> None:
    field, _ = parse_field("name=hello+world%21")
    assert field.kind == "url-encoded"
    assert field.decoded == "name=hello+world!"
    assert field.rendered == "name=hello+world!"


def test_missing_empty_and_json_null_are_distinct() -> None:
    missing, _ = parse_field(None)
    empty, _ = parse_field("")
    null, parsed = parse_field("null")
    assert (missing.kind, missing.rendered) == ("missing", "N/A")
    assert (empty.kind, empty.rendered) == ("empty", "(empty)")
    assert (null.kind, null.rendered, parsed) == ("null", "null", None)


def test_extract_nested_identity_with_aliases() -> None:
    username, game_code = extract_operator_identity(
        {"payload": {"user_name": "user-1", "game_code": "game-2"}}
    )
    assert username == "user-1"
    assert game_code == "game-2"


def test_record_key_contains_environment() -> None:
    row = RawLogRow(url="/api/v1/groove")
    assert build_record_key("QA", row) != build_record_key("staging", row)


def test_normalize_row_extracts_identity() -> None:
    record = normalize_row(
        RawLogRow(operatorData='{"username":"user-1","gameCode":"game-2"}'),
        scraped_at=datetime(2026, 7, 19, tzinfo=UTC),
        environment=resolve_environment("QA"),
        query='"groove"',
        time_from="now-1w",
        time_to="now",
    )
    assert record.username == "user-1"
    assert record.game_code == "game-2"

