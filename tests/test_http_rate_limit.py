"""Tests for HTTP-layer rate limit auto-wait and retry logic."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import pytest
from tweety.http import Request
from tweety.exceptions import RateLimitReached, TwitterError


def _make_mock_client():
    """Create a mock client with necessary attributes."""
    client = MagicMock()
    client.cookies = {"ct0": "fake_csrf", "auth_token": "fake_token"}
    client.session = MagicMock()
    client.session.cookies_dict = MagicMock(return_value={"ct0": "fake_csrf"})
    client.session.logged_in = True
    client.session.save_session = AsyncMock()
    return client


def _make_429_response(retry_after_seconds=60):
    """Create a mock 429 response with rate limit headers."""
    response = MagicMock()
    response.status_code = 429
    response.text = "Rate limit exceeded"
    reset_epoch = int(time.time()) + retry_after_seconds
    response.headers = {
        'x-rate-limit-reset': str(reset_epoch),
        'x-rate-limit-remaining': '0',
    }
    response.cookies = MagicMock()
    response.cookies.get = MagicMock(return_value=None)
    response.url = MagicMock()
    response.url.path = "/test"
    response.json = MagicMock(return_value=None)
    return response


def _make_success_response(data=None):
    """Create a mock successful response."""
    response = MagicMock()
    response.status_code = 200
    response.text = '{"data": {}}'
    response.headers = {}
    response.cookies = MagicMock()
    response.cookies.get = MagicMock(return_value=None)
    response.url = MagicMock()
    response.url.path = "/test"
    response.json = MagicMock(return_value=data or {"data": {"result": "ok"}})
    return response


class TestRateLimitAutoWait:
    """Tests that __get_response__ auto-waits on 429 and retries."""

    @pytest.mark.asyncio
    async def test_429_with_short_retry_triggers_wait_and_retry(self):
        """When 429 is received with retry_after <= 900s, should wait and retry once."""
        client = _make_mock_client()
        request = Request(client, max_retries=3)
        request._transaction = MagicMock()
        request._transaction.generate_transaction_id = MagicMock(return_value="tx123")
        request._guest_token = "guest"
        request._cookie = {"ct0": "test"}

        response_429 = _make_429_response(retry_after_seconds=2)  # 2 seconds
        response_ok = _make_success_response({"data": {"user": "test"}})

        call_count = 0

        async def mock_request(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return response_429
            return response_ok

        request._session = MagicMock()
        request._session.request = mock_request

        with patch('tweety.http.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            result = await request.__get_response__(
                method="GET", url="https://api.x.com/test"
            )

        # Should have called sleep with ~3 seconds (2 + 1 buffer)
        mock_sleep.assert_called_once()
        sleep_time = mock_sleep.call_args[0][0]
        assert 1 <= sleep_time <= 10  # Within reasonable range

        # Should return the successful response
        assert result == {"data": {"user": "test"}}
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_429_with_long_retry_raises_immediately(self):
        """When retry_after > 900s, should NOT wait; raise RateLimitReached."""
        client = _make_mock_client()
        request = Request(client, max_retries=3)
        request._transaction = MagicMock()
        request._transaction.generate_transaction_id = MagicMock(return_value="tx123")
        request._guest_token = "guest"
        request._cookie = {"ct0": "test"}

        response_429 = _make_429_response(retry_after_seconds=1800)  # 30 min — too long

        async def mock_request(**kwargs):
            return response_429

        request._session = MagicMock()
        request._session.request = mock_request

        with patch('tweety.http.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(RateLimitReached):
                await request.__get_response__(
                    method="GET", url="https://api.x.com/test"
                )

        # Should NOT have called sleep since retry_after > 900
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_429_no_retry_header_raises(self):
        """When 429 without x-rate-limit-reset header, should raise immediately."""
        client = _make_mock_client()
        request = Request(client, max_retries=3)
        request._transaction = MagicMock()
        request._transaction.generate_transaction_id = MagicMock(return_value="tx123")
        request._guest_token = "guest"
        request._cookie = {"ct0": "test"}

        response = MagicMock()
        response.status_code = 429
        response.text = "Rate limit exceeded"
        response.headers = {}  # No rate limit headers
        response.cookies = MagicMock()
        response.cookies.get = MagicMock(return_value=None)
        response.url = MagicMock()
        response.url.path = "/test"
        response.json = MagicMock(return_value=None)

        async def mock_request(**kwargs):
            return response

        request._session = MagicMock()
        request._session.request = mock_request

        with pytest.raises(RateLimitReached):
            await request.__get_response__(
                method="GET", url="https://api.x.com/test"
            )

    @pytest.mark.asyncio
    async def test_429_only_retries_once(self):
        """Should not enter infinite retry loop — only retry once on 429."""
        client = _make_mock_client()
        request = Request(client, max_retries=3)
        request._transaction = MagicMock()
        request._transaction.generate_transaction_id = MagicMock(return_value="tx123")
        request._guest_token = "guest"
        request._cookie = {"ct0": "test"}

        response_429 = _make_429_response(retry_after_seconds=2)
        call_count = 0

        async def mock_request(**kwargs):
            nonlocal call_count
            call_count += 1
            return response_429  # Always return 429

        request._session = MagicMock()
        request._session.request = mock_request

        with patch('tweety.http.asyncio.sleep', new_callable=AsyncMock):
            with pytest.raises(RateLimitReached):
                await request.__get_response__(
                    method="GET", url="https://api.x.com/test"
                )

        # First call + one retry = 2 calls total
        assert call_count == 2


class TestNetworkRetry:
    """Tests for network-level retry in __get_response__."""

    @pytest.mark.asyncio
    async def test_network_error_retries(self):
        """Network errors should be retried up to max_retries."""
        client = _make_mock_client()
        request = Request(client, max_retries=3)
        request._transaction = MagicMock()
        request._transaction.generate_transaction_id = MagicMock(return_value="tx123")
        request._guest_token = "guest"
        request._cookie = {"ct0": "test"}

        call_count = 0
        success_response = _make_success_response()

        async def mock_request(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Connection refused")
            return success_response

        request._session = MagicMock()
        request._session.request = mock_request

        result = await request.__get_response__(
            method="GET", url="https://api.x.com/test"
        )

        assert call_count == 3
        assert result == {"data": {"result": "ok"}}

    @pytest.mark.asyncio
    async def test_network_error_exhausts_retries(self):
        """After max_retries, should raise the last error."""
        client = _make_mock_client()
        request = Request(client, max_retries=3)
        request._transaction = MagicMock()
        request._transaction.generate_transaction_id = MagicMock(return_value="tx123")
        request._guest_token = "guest"
        request._cookie = {"ct0": "test"}

        async def mock_request(**kwargs):
            raise ConnectionError("Connection refused")

        request._session = MagicMock()
        request._session.request = mock_request

        with pytest.raises(ConnectionError):
            await request.__get_response__(
                method="GET", url="https://api.x.com/test"
            )


class TestUpdateRateLimit:
    """Tests for _update_rate_limit header parsing."""

    @pytest.mark.asyncio
    async def test_stores_rate_limit_info(self):
        client = _make_mock_client()
        request = Request(client, max_retries=3)

        now_epoch = int(time.time())
        response = MagicMock()
        response.url = MagicMock()
        response.url.path = "/1.1/friends/create.json"
        response.headers = {
            'x-rate-limit-reset': str(now_epoch + 900),
            'x-rate-limit-remaining': '14',
        }

        await request._update_rate_limit(response, "follow_user")

        assert "follow_user" in request._limits
        assert request._limits["follow_user"]["limit_remaining"] == 14
        assert request._limits["follow_user"]["limit_reset"] == now_epoch + 900

    @pytest.mark.asyncio
    async def test_no_headers_no_store(self):
        client = _make_mock_client()
        request = Request(client, max_retries=3)

        response = MagicMock()
        response.url = "/test"
        response.headers = {}

        await request._update_rate_limit(response, "test_func")
        assert "test_func" not in request._limits
