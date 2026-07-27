import pytest

from scraper import (
    LOGIN_SELECTORS,
    NO_RESULTS_SELECTOR,
    QUERY_LOADING_SELECTOR,
    RESULT_SURFACE_SELECTOR,
    OpenSearchScraper,
    ScrapeError,
)


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


def test_cloudflare_tunnel_error_is_reported_directly() -> None:
    class FakeLocator:
        def __init__(self, selector: str):
            self.selector = selector

        def inner_text(self, timeout: int) -> str:
            assert self.selector == "body"
            assert timeout == 10_000
            return "Error\n1033\nRay ID: test\nCloudflare Tunnel error"

        def count(self) -> int:
            return 0

    class FakePage:
        def locator(self, selector: str) -> FakeLocator:
            return FakeLocator(selector)

    scraper = OpenSearchScraper.__new__(OpenSearchScraper)
    with pytest.raises(ScrapeError, match=r"^Error 1033: Cloudflare Tunnel error$"):
        scraper._verify_security_state(FakePage())


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


def test_no_results_prompt_stops_waiting_immediately() -> None:
    class FakeLocator:
        def __init__(self, *, visible: bool, count: int = 1):
            self.visible = visible
            self.locator_count = count

        @property
        def first(self):
            return self

        def count(self) -> int:
            return self.locator_count

        def is_visible(self) -> bool:
            return self.visible

    class FakePage:
        def wait_for_selector(self, selector: str, timeout: int) -> None:
            assert selector == RESULT_SURFACE_SELECTOR
            assert 0 < timeout <= 30_000

        def locator(self, selector: str) -> FakeLocator:
            if selector == NO_RESULTS_SELECTOR:
                return FakeLocator(visible=True)
            assert selector == QUERY_LOADING_SELECTOR
            return FakeLocator(visible=False, count=0)

        def wait_for_timeout(self, timeout: int) -> None:
            assert timeout == 250

    with pytest.raises(ScrapeError, match="找不到符合條件的 log"):
        OpenSearchScraper._wait_for_result_surface(FakePage())


def test_transient_no_results_prompt_waits_for_loading_to_finish() -> None:
    class State:
        no_results = True
        loading = True

    page_state = State()

    class FakeLocator:
        def __init__(self, kind: str):
            self.kind = kind

        @property
        def first(self):
            return self

        def count(self) -> int:
            return 1

        def is_visible(self) -> bool:
            return page_state.loading if self.kind == "loading" else page_state.no_results

        def wait_for(self, *, state: str, timeout: int) -> None:
            assert self.kind == "loading"
            assert state == "hidden"
            assert timeout > 0
            page_state.loading = False
            page_state.no_results = False

    class FakePage:
        def wait_for_selector(self, selector: str, timeout: int) -> None:
            assert selector == RESULT_SURFACE_SELECTOR
            assert timeout > 0

        def locator(self, selector: str) -> FakeLocator:
            if selector == NO_RESULTS_SELECTOR:
                return FakeLocator("no-results")
            assert selector == QUERY_LOADING_SELECTOR
            return FakeLocator("loading")

    OpenSearchScraper._wait_for_result_surface(FakePage())
