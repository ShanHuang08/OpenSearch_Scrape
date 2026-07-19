from __future__ import annotations

import re
from urllib.parse import quote

from environments import EnvironmentSpec

CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


def normalize_keywords(keywords: list[str]) -> list[str]:
    normalized = [keyword.strip() for keyword in keywords if keyword.strip()]
    if not normalized:
        raise ValueError("至少需要一個非空白搜尋關鍵字。")
    for keyword in normalized:
        if CONTROL_CHARACTERS.search(keyword):
            raise ValueError("搜尋關鍵字不可包含控制字元。")
    return normalized


def parse_keyword_expression(values: list[str]) -> tuple[list[str], str | None]:
    """Parse CLI values, accepting ``groove or cs123`` as one expression."""
    tokens = [value.strip() for value in values if value.strip()]
    trailing_operator = re.compile(r"(?:^|\s+)(?:or|and)\s*$", re.I)
    while tokens and trailing_operator.search(tokens[-1]):
        trimmed = trailing_operator.sub("", tokens[-1]).strip()
        if trimmed:
            tokens[-1] = trimmed
        else:
            tokens.pop()
    if not tokens:
        raise ValueError("至少需要一個非空白搜尋關鍵字。")

    expression = " ".join(tokens)
    operators = {match.lower() for match in re.findall(r"\b(or|and)\b", expression, re.I)}
    if len(operators) > 1:
        raise ValueError("關鍵字查詢不可混用 or 與 and。")
    if operators:
        operator = next(iter(operators))
        parts = [part.strip() for part in re.split(r"\s+(?:or|and)\s+", expression, flags=re.I)]
        return normalize_keywords(parts), operator
    return normalize_keywords(tokens), None


def escape_kql_phrase(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_kql(keywords: list[str], operator: str = "or") -> str:
    normalized = normalize_keywords(keywords)
    normalized_operator = operator.strip().lower()
    if normalized_operator not in {"or", "and"}:
        raise ValueError("query operator 只接受 or 或 and。")
    return f" {normalized_operator} ".join(
        f'"{escape_kql_phrase(keyword)}"' for keyword in normalized
    )


def build_discover_url(
    dashboard_url: str,
    environment: EnvironmentSpec,
    kql: str,
    time_from: str = "now-1w",
    time_to: str = "now",
) -> str:
    base_url = dashboard_url.split("#", maxsplit=1)[0]
    encoded_query = quote(f"{kql} ", safe="")
    columns = (
        "requestBody,responseBody,url,operatorData,operatorResponse,"
        "operatorUrl,error,timeTaken"
    )
    return (
        f"{base_url}#?_a=(discover:(columns:!({columns}),isDirty:!f,sort:!()),"
        f"metadata:(indexPattern:'{environment.index_pattern_id}',view:discover))"
        f"&_g=(filters:!(),refreshInterval:(pause:!t,value:0),"
        f"time:(from:{time_from},to:{time_to}))"
        f"&_q=(filters:!(),query:(language:kuery,query:'{encoded_query}'))"
    )


def query_slug(keywords: list[str], max_length: int = 80) -> str:
    parts = []
    for keyword in normalize_keywords(keywords):
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", keyword).strip("-").lower()
        parts.append(slug or "query")
    value = "-or-".join(parts)
    return value[:max_length].rstrip("-") or "query"
