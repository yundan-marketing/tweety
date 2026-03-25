"""Tests for tweety exception types and error hierarchy."""

import pickle
import pytest
from tweety.exceptions import (
    TwitterError,
    RateLimitReached,
    AutomationDetected,
    InvalidCredentials,
    DeniedLogin,
    UserNotFound,
    LockedAccount,
    SuspendedAccount,
    UserProtected,
    InvalidTweetIdentifier,
    TWITTER_ERRORS,
)


class TestTwitterError:
    """Tests for the base TwitterError exception."""

    def test_basic_creation(self):
        err = TwitterError(88, "RateLimitExceeded", None, "Rate limit hit")
        assert err.error_code == 88
        assert err.error_name == "RateLimitExceeded"
        assert "Rate limit hit" in str(err)

    def test_string_response_formats_message(self):
        err = TwitterError(226, "TieredActionTweetSpammer", "some response text", "original msg")
        assert "[226]" in str(err)
        assert "some response text" in str(err)

    def test_is_exception(self):
        assert issubclass(TwitterError, Exception)

    def test_404_message(self):
        err = TwitterError("404", "NotFound", None, "not found")
        assert "404" in str(err.error_code)


class TestRateLimitReached:
    """Tests for RateLimitReached exception."""

    def test_inherits_twitter_error(self):
        assert issubclass(RateLimitReached, TwitterError)

    def test_retry_after(self):
        err = RateLimitReached(88, "RateLimitExceeded", None, retry_after=120)
        assert err.retry_after == 120

    def test_retry_after_default_none(self):
        err = RateLimitReached(88, "RateLimitExceeded", None)
        assert err.retry_after is None

    def test_default_message(self):
        err = RateLimitReached(88, "RateLimitExceeded", None)
        assert "Rate Limit" in str(err)


class TestAutomationDetected:
    """Tests for the new AutomationDetected exception."""

    def test_inherits_twitter_error(self):
        assert issubclass(AutomationDetected, TwitterError)

    def test_default_values(self):
        err = AutomationDetected()
        assert err.error_code == 226
        assert err.error_name == "TieredActionTweetSpammer"
        assert err.retry_after == 300  # 5 min default

    def test_custom_retry_after(self):
        err = AutomationDetected(retry_after=600)
        assert err.retry_after == 600

    def test_custom_error_code(self):
        err = AutomationDetected(error_code=225, error_name="TieredActionFollowSpammer")
        assert err.error_code == 225

    def test_message_content(self):
        err = AutomationDetected()
        assert "automated" in str(err).lower()

    def test_pickle_roundtrip(self):
        """AutomationDetected should survive pickle serialization (needed for Celery)."""
        err = AutomationDetected()
        pickled = pickle.dumps(err)
        restored = pickle.loads(pickled)
        assert isinstance(restored, AutomationDetected)
        assert restored.error_code == 226

    def test_catch_as_twitter_error(self):
        """AutomationDetected should be catchable as TwitterError."""
        with pytest.raises(TwitterError):
            raise AutomationDetected()


class TestTwitterErrorCodes:
    """Tests for the TWITTER_ERRORS mapping."""

    def test_226_exists(self):
        assert 226 in TWITTER_ERRORS
        assert TWITTER_ERRORS[226] == "TieredActionTweetSpammer"

    def test_225_exists(self):
        assert 225 in TWITTER_ERRORS
        assert TWITTER_ERRORS[225] == "TieredActionFollowSpammer"

    def test_88_exists(self):
        assert 88 in TWITTER_ERRORS
        assert TWITTER_ERRORS[88] == "RateLimitExceeded"

    def test_344_exists(self):
        assert 344 in TWITTER_ERRORS
        assert TWITTER_ERRORS[344] == "UserActionRateLimitExceeded"

    def test_total_error_count(self):
        assert len(TWITTER_ERRORS) >= 400  # At least 400 error codes defined
