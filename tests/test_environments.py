import pytest

from opensearch_scrape.environments import resolve_environment


@pytest.mark.parametrize("value", ["QA", "qa", " Qa "])
def test_resolve_qa(value: str) -> None:
    environment = resolve_environment(value)
    assert environment.name == "QA"
    assert environment.pattern_name == "api-request-logs-qa-*"
    assert environment.index_pattern_id == "53ceb180-8f5d-11ef-b9c6-73a60e0d81fe"


@pytest.mark.parametrize("value", ["staging", "STAGING", "stg"])
def test_resolve_staging(value: str) -> None:
    environment = resolve_environment(value)
    assert environment.name == "staging"
    assert environment.pattern_name == "api-request-logs-stg-*"
    assert environment.index_pattern_id == "48481400-8c6a-11ef-b9c6-73a60e0d81fe"


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(ValueError, match="只接受 QA"):
        resolve_environment("production")

