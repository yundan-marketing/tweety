"""Tests for BaseGeneratorClass pagination with rate limit recovery."""

import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import pytest
from tweety.exceptions import RateLimitReached
from tweety.types.base import BaseGeneratorClass


class SimpleItem:
    """Simple item that won't trigger User/Tweet isinstance checks."""
    def __init__(self, value):
        self.value = value


class MockPaginator(BaseGeneratorClass):
    """Concrete implementation of BaseGeneratorClass for testing."""
    _RESULT_ATTR = "items"

    def __init__(self, pages=5, wait_time=0, items_per_page=2):
        super().__init__()
        self.items = []
        self.cursor = None
        self.cursor_top = None
        self.is_next_page = True
        self.client = MagicMock()
        self.client._cached_users = {}
        self.user_id = "12345"
        self.pages = pages
        self.wait_time = wait_time
        self._items_per_page = items_per_page
        self._page_counter = 0
        self._fail_on_pages = set()
        self._fail_count = {}

    async def get_page(self, cursor):
        self._page_counter += 1
        call_num = self._page_counter

        if call_num in self._fail_on_pages:
            self._fail_count[call_num] = self._fail_count.get(call_num, 0) + 1
            if self._fail_count[call_num] <= 1:  # Only fail once per call
                raise RateLimitReached(88, "RateLimitExceeded", None, retry_after=2)

        # Determine actual successful page number (excluding failed calls)
        successful_page = sum(1 for c in range(1, call_num + 1)
                              if c not in self._fail_on_pages or self._fail_count.get(c, 0) > 1)
        items = [SimpleItem(f"item_{successful_page}_{i}") for i in range(self._items_per_page)]
        new_cursor = f"cursor_call_{call_num}" if successful_page < self.pages else None
        return items, new_cursor, None


class TestPaginationBasic:
    """Tests for basic pagination behavior."""

    @pytest.mark.asyncio
    async def test_iterates_all_pages(self):
        paginator = MockPaginator(pages=3, items_per_page=2)
        pages_yielded = 0

        async for gen, results in paginator.generator():
            pages_yielded += 1
            assert len(results) == 2

        assert pages_yielded == 3

    @pytest.mark.asyncio
    async def test_stops_on_empty_results(self):
        paginator = MockPaginator(pages=5, items_per_page=0)
        pages_yielded = 0

        async for gen, results in paginator.generator():
            pages_yielded += 1

        assert pages_yielded == 0  # First page returns empty, stops immediately

    @pytest.mark.asyncio
    async def test_stops_when_no_next_page(self):
        """When cursor is None, pagination should stop."""
        paginator = MockPaginator(pages=10, items_per_page=2)
        pages_yielded = 0

        async for gen, results in paginator.generator():
            pages_yielded += 1

        assert pages_yielded == 10

    @pytest.mark.asyncio
    async def test_accumulates_items(self):
        paginator = MockPaginator(pages=3, items_per_page=5)

        async for gen, results in paginator.generator():
            pass

        assert len(paginator.items) == 15  # 3 pages * 5 items

    @pytest.mark.asyncio
    async def test_wait_time_between_pages(self):
        paginator = MockPaginator(pages=3, wait_time=1, items_per_page=2)

        with patch('tweety.types.base.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            async for gen, results in paginator.generator():
                pass

        # Should sleep between pages (not after the last one)
        assert mock_sleep.call_count == 2


class TestPaginationRateLimitRecovery:
    """Tests for rate limit recovery during pagination."""

    @pytest.mark.asyncio
    async def test_recovers_from_rate_limit(self):
        """Pagination should wait and retry when hitting rate limit."""
        paginator = MockPaginator(pages=3, items_per_page=2)
        paginator._fail_on_pages = {2}  # Fail on page 2

        with patch('tweety.types.base.asyncio.sleep', new_callable=AsyncMock):
            pages_yielded = 0
            async for gen, results in paginator.generator():
                pages_yielded += 1

        # Should still complete all 3 pages (page 2 retried after rate limit)
        assert pages_yielded == 3

    @pytest.mark.asyncio
    async def test_rate_limit_uses_retry_after(self):
        """Should sleep for retry_after seconds from the exception."""
        paginator = MockPaginator(pages=2, items_per_page=2)
        paginator._fail_on_pages = {1}

        with patch('tweety.types.base.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            async for gen, results in paginator.generator():
                pass

        # First sleep should be retry_after + 1 = 3 seconds
        first_sleep = mock_sleep.call_args_list[0][0][0]
        assert first_sleep == 3  # retry_after(2) + 1

    @pytest.mark.asyncio
    async def test_rate_limit_max_retries_exceeded(self):
        """After 3 rate limit retries, should raise the exception."""

        class AlwaysFailPaginator(MockPaginator):
            async def get_page(self, cursor):
                raise RateLimitReached(88, "RateLimitExceeded", None, retry_after=1)

        paginator = AlwaysFailPaginator(pages=3, items_per_page=2)

        with patch('tweety.types.base.asyncio.sleep', new_callable=AsyncMock):
            with pytest.raises(RateLimitReached):
                async for gen, results in paginator.generator():
                    pass

    @pytest.mark.asyncio
    async def test_rate_limit_fallback_sleep(self):
        """When retry_after is None or out of range, use fallback sleep."""

        class NoRetryAfterPaginator(MockPaginator):
            _fail_count_total = 0

            async def get_page(self, cursor):
                self._fail_count_total += 1
                if self._fail_count_total == 1:
                    raise RateLimitReached(88, "RateLimitExceeded", None, retry_after=None)
                items = [SimpleItem(f"item_{i}") for i in range(2)]
                return items, None, None

        paginator = NoRetryAfterPaginator(pages=2, items_per_page=2)

        with patch('tweety.types.base.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            async for gen, results in paginator.generator():
                pass

        # Fallback: 60 * _rate_limit_retries = 60 * 1 = 60 seconds
        first_sleep = mock_sleep.call_args_list[0][0][0]
        assert first_sleep == 60

    @pytest.mark.asyncio
    async def test_rate_limit_counter_resets_on_success(self):
        """Rate limit retry counter should reset after a successful page."""
        paginator = MockPaginator(pages=4, items_per_page=2)
        paginator._fail_on_pages = {1, 3}  # Fail on pages 1 and 3

        with patch('tweety.types.base.asyncio.sleep', new_callable=AsyncMock):
            pages_yielded = 0
            async for gen, results in paginator.generator():
                pages_yielded += 1

        assert pages_yielded == 4

    @pytest.mark.asyncio
    async def test_cancelled_error_breaks(self):
        """asyncio.CancelledError should break the loop cleanly."""

        class CancelPaginator(MockPaginator):
            async def get_page(self, cursor):
                raise asyncio.CancelledError()

        paginator = CancelPaginator(pages=3, items_per_page=2)
        pages_yielded = 0

        async for gen, results in paginator.generator():
            pages_yielded += 1

        assert pages_yielded == 0


class TestPaginationHelpers:
    """Tests for helper methods on BaseGeneratorClass."""

    def test_has_next_page_false_when_same_cursor(self):
        paginator = MockPaginator(pages=1)
        paginator.cursor = "cursor_1"
        assert paginator._has_next_page("cursor_1") is False

    def test_has_next_page_false_when_none(self):
        paginator = MockPaginator(pages=1)
        paginator.cursor = "cursor_1"
        assert paginator._has_next_page(None) is False

    def test_has_next_page_true_when_new_cursor(self):
        paginator = MockPaginator(pages=1)
        paginator.cursor = "cursor_1"
        assert paginator._has_next_page("cursor_2") is True

    def test_len(self):
        paginator = MockPaginator(pages=1)
        paginator.items = [1, 2, 3]
        assert len(paginator) == 3

    def test_repr(self):
        paginator = MockPaginator(pages=1)
        repr_str = repr(paginator)
        assert "MockPaginator" in repr_str
        assert "user_id=12345" in repr_str
