"""Tests for GenericError exception mapping and retry_after calculation."""

import datetime
from unittest.mock import MagicMock
import pytest
from tweety.types.n_types import GenericError
from tweety.exceptions import (
    RateLimitReached,
    AutomationDetected,
    InvalidCredentials,
    SuspendedAccount,
    LockedAccount,
    InvalidTweetIdentifier,
    TwitterError,
)


def _make_response(status_code=200, headers=None, error_code=None, error_message=None):
    """Create a mock httpx Response."""
    response = MagicMock()
    response.status_code = status_code
    response.headers = headers or {}
    return response


class TestGenericErrorExceptionMapping:
    """Tests that GenericError maps error codes to correct exception types."""

    def test_88_raises_rate_limit(self):
        response = _make_response(headers={})
        with pytest.raises(RateLimitReached) as exc_info:
            GenericError(response, 88, "Rate limit exceeded")
        assert exc_info.value.error_code == 88

    def test_226_raises_automation_detected(self):
        response = _make_response(headers={})
        with pytest.raises(AutomationDetected) as exc_info:
            GenericError(response, 226, "Automated behavior detected")
        assert exc_info.value.error_code == 226

    def test_225_raises_automation_detected(self):
        response = _make_response(headers={})
        with pytest.raises(AutomationDetected):
            GenericError(response, 225, "Follow spammer")

    def test_227_raises_automation_detected(self):
        response = _make_response(headers={})
        with pytest.raises(AutomationDetected):
            GenericError(response, 227, "Follow creeper")

    def test_228_raises_automation_detected(self):
        response = _make_response(headers={})
        with pytest.raises(AutomationDetected):
            GenericError(response, 228, "Tweet creeper")

    def test_344_raises_rate_limit(self):
        response = _make_response(headers={})
        with pytest.raises(RateLimitReached):
            GenericError(response, 344, "Daily limit reached")

    def test_477_raises_rate_limit(self):
        response = _make_response(headers={})
        with pytest.raises(RateLimitReached):
            GenericError(response, 477, "Rate limited")

    def test_32_raises_invalid_credentials(self):
        response = _make_response(headers={})
        with pytest.raises(InvalidCredentials):
            GenericError(response, 32, "Could not authenticate you")

    def test_64_raises_suspended(self):
        response = _make_response(headers={})
        with pytest.raises(SuspendedAccount):
            GenericError(response, 64, "Account suspended")

    def test_326_raises_locked(self):
        response = _make_response(headers={})
        with pytest.raises(LockedAccount):
            GenericError(response, 326, "Account locked")

    def test_144_raises_invalid_tweet(self):
        response = _make_response(headers={})
        with pytest.raises(InvalidTweetIdentifier):
            GenericError(response, 144, "Status not found")

    def test_unknown_code_raises_twitter_error(self):
        """Error codes not in EXCEPTIONS should raise generic TwitterError."""
        response = _make_response(headers={})
        with pytest.raises(TwitterError):
            GenericError(response, 999, "Unknown error")


class TestGenericErrorRetryAfter:
    """Tests for retry_after calculation from response headers."""

    def test_retry_after_from_headers(self):
        now_epoch = int(datetime.datetime.now().timestamp())
        future_epoch = now_epoch + 300  # 5 minutes from now
        response = _make_response(
            headers={
                'x-rate-limit-reset': str(future_epoch),
                'x-rate-limit-remaining': '0',
            }
        )
        with pytest.raises(RateLimitReached) as exc_info:
            GenericError(response, 88, "Rate limit exceeded")

        # retry_after should be approximately 300 seconds (allow some tolerance)
        assert 295 <= exc_info.value.retry_after <= 305

    def test_retry_after_zero_when_no_headers(self):
        response = _make_response(headers={})
        with pytest.raises(RateLimitReached) as exc_info:
            GenericError(response, 88, "Rate limit exceeded")
        assert exc_info.value.retry_after == 0

    def test_retry_after_passed_to_automation_detected(self):
        now_epoch = int(datetime.datetime.now().timestamp())
        future_epoch = now_epoch + 600
        response = _make_response(
            headers={
                'x-rate-limit-reset': str(future_epoch),
                'x-rate-limit-remaining': '0',
            }
        )
        with pytest.raises(AutomationDetected) as exc_info:
            GenericError(response, 226, "Automation detected")
        assert 595 <= exc_info.value.retry_after <= 605
