from scraper import LOGIN_SELECTORS, OpenSearchScraper


def test_header_map_uses_names_instead_of_fixed_columns() -> None:
    headers = [
        "",
        "Time",
        "operatorData",
        "url",
        "requestBody",
        "responseBody",
        "operatorResponse",
        "operatorUrl",
        "error",
        "timeTaken",
    ]
    mapping = OpenSearchScraper._build_header_map(headers)
    assert mapping["requestTime"] == 1
    assert mapping["operatorData"] == 2
    assert mapping["requestBody"] == 4
    assert mapping["timeTaken"] == 9


def test_login_selectors_prefer_stable_attributes() -> None:
    assert LOGIN_SELECTORS["username"][0] == '[data-test-subj="user-name"]'
    assert LOGIN_SELECTORS["password"][0] == '[data-test-subj="password"]'
    assert LOGIN_SELECTORS["submit"][0] == '[data-test-subj="submit"]'
    assert all(
        "i739" not in selector
        for selectors in LOGIN_SELECTORS.values()
        for selector in selectors
    )


def test_time_range_label_removes_show_dates_suffix() -> None:
    class FakeLocator:
        def count(self) -> int:
            return 1

        def inner_text(self) -> str:
            return "Last 1 weekShow dates"

    class FakePage:
        def locator(self, selector: str) -> FakeLocator:
            assert selector == '[data-test-subj="superDatePickerShowDatesButton"]'
            return FakeLocator()

    assert OpenSearchScraper._read_human_time_range(FakePage()) == "Last 1 week"
