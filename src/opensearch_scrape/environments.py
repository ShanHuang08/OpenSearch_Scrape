from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EnvironmentSpec:
    name: str
    pattern_name: str
    index_pattern_id: str


ENVIRONMENTS: dict[str, EnvironmentSpec] = {
    "qa": EnvironmentSpec(
        name="QA",
        pattern_name="api-request-logs-qa-*",
        index_pattern_id="53ceb180-8f5d-11ef-b9c6-73a60e0d81fe",
    ),
    "staging": EnvironmentSpec(
        name="staging",
        pattern_name="api-request-logs-stg-*",
        index_pattern_id="48481400-8c6a-11ef-b9c6-73a60e0d81fe",
    ),
}

ENVIRONMENT_ALIASES = {"qa": "qa", "staging": "staging", "stg": "staging"}


def resolve_environment(value: str) -> EnvironmentSpec:
    normalized = value.strip().lower()
    key = ENVIRONMENT_ALIASES.get(normalized)
    if key is None:
        raise ValueError("不支援的環境；目前只接受 QA、staging（或 stg）。")
    return ENVIRONMENTS[key]

