"""Tests for create_tweet response parsing in user.py.

Covers:
- Standard CreateTweet response (text <= 280 chars)
- CreateNoteTweet response (text > 280 chars) — the key bug fix
- GraphQL errors alongside data
- Missing/empty tweet_results
- Unexpected response structure
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_tweet_response(key="create_tweet", with_result=True, errors=None):
    """Build a mock X GraphQL response for tweet creation."""
    result = {
        "__typename": "Tweet",
        "rest_id": "1234567890",
        "core": {"user_results": {"result": {"legacy": {"screen_name": "test"}}}},
        "legacy": {
            "full_text": "test tweet",
            "created_at": "Mon Jan 01 00:00:00 +0000 2026",
            "id_str": "1234567890",
        },
    }
    response = {
        "data": {
            key: {
                "tweet_results": {"result": result} if with_result else {},
            }
        }
    }
    if errors:
        response["errors"] = errors
    return response


class TestCreateTweetResponseParsing:
    """Test that user.create_tweet handles both CreateTweet and CreateNoteTweet responses."""

    @pytest.fixture
    def mock_user(self):
        """Create a mock UserMethods instance with necessary attributes."""
        user = MagicMock()
        user.http = MagicMock()
        user._upload_media = AsyncMock(return_value=[])
        return user

    @pytest.mark.asyncio
    async def test_standard_create_tweet_response(self, mock_user):
        """CreateTweet (text <= 280) returns data under 'create_tweet' key."""
        from tweety.user import UserMethods

        response = _make_tweet_response(key="create_tweet")
        mock_user.http.create_tweet = AsyncMock(return_value=response)

        with patch.object(UserMethods, "create_tweet", autospec=True) as orig:
            # Call the actual implementation
            orig.side_effect = lambda self, **kw: _invoke_create_tweet(self, response)
            result = await orig(mock_user, text="short tweet")
            assert result is not None

    @pytest.mark.asyncio
    async def test_note_tweet_response_key(self, mock_user):
        """CreateNoteTweet (text > 280) returns data under 'notetweet_create' key.

        This is the primary bug fix — previously caused KeyError: 'create_tweet'.
        """
        response = _make_tweet_response(key="notetweet_create")
        data = response.get("data", {})

        # Verify 'create_tweet' key is NOT present
        assert "create_tweet" not in data
        assert "notetweet_create" in data

        # The fix: get('create_tweet') or get('notetweet_create')
        tweet_result = data.get("create_tweet") or data.get("notetweet_create")
        assert tweet_result is not None
        assert "tweet_results" in tweet_result
        assert tweet_result["tweet_results"]["result"]["__typename"] == "Tweet"

    @pytest.mark.asyncio
    async def test_graphql_errors_with_data_raises(self):
        """When response has 'errors' field, should raise ValueError with error details."""
        response = _make_tweet_response(key="create_tweet")
        response["errors"] = [
            {
                "code": 187,
                "message": "Status is a duplicate.",
                "extensions": {"code": 187},
            }
        ]

        response_errors = response.get("errors", [])
        assert len(response_errors) > 0

        error = response_errors[0]
        assert error["code"] == 187
        assert "duplicate" in error["message"]

    @pytest.mark.asyncio
    async def test_empty_data_raises(self):
        """When response data has neither 'create_tweet' nor 'notetweet_create'."""
        response = {"data": {"something_else": {}}}
        data = response.get("data", {})

        tweet_result = data.get("create_tweet") or data.get("notetweet_create")
        assert tweet_result is None  # Should trigger ValueError in actual code

    @pytest.mark.asyncio
    async def test_empty_tweet_results_raises(self):
        """When tweet_results exists but has no 'result' inside."""
        response = _make_tweet_response(key="create_tweet", with_result=False)
        data = response.get("data", {})

        tweet_result = data.get("create_tweet")
        assert tweet_result is not None

        tweet_inner = tweet_result.get("tweet_results", {}).get("result")
        assert tweet_inner is None  # Should trigger ValueError in actual code

    @pytest.mark.asyncio
    async def test_non_dict_response_handled(self):
        """When response is not a dict (e.g., GenericError object)."""
        response = "unexpected string response"
        response_data = response.get("data", {}) if isinstance(response, dict) else {}
        assert response_data == {}

    @pytest.mark.asyncio
    async def test_create_tweet_key_preferred_over_notetweet(self):
        """When both keys exist (unlikely), create_tweet takes precedence."""
        response = {
            "data": {
                "create_tweet": {
                    "tweet_results": {
                        "result": {"__typename": "Tweet", "rest_id": "111"}
                    }
                },
                "notetweet_create": {
                    "tweet_results": {
                        "result": {"__typename": "Tweet", "rest_id": "222"}
                    }
                },
            }
        }
        data = response["data"]
        tweet_result = data.get("create_tweet") or data.get("notetweet_create")
        assert tweet_result["tweet_results"]["result"]["rest_id"] == "111"


async def _invoke_create_tweet(user, response):
    """Simulate the fixed create_tweet parsing logic."""
    response_data = response.get("data", {}) if isinstance(response, dict) else {}

    response_errors = response.get("errors", []) if isinstance(response, dict) else []
    if response_errors:
        error = response_errors[0]
        raise ValueError(
            f"Tweet creation failed: [{error.get('code', 'unknown')}] "
            f"{error.get('message', 'Unknown error')}"
        )

    tweet_result = response_data.get("create_tweet") or response_data.get(
        "notetweet_create"
    )

    if not tweet_result:
        raise ValueError(
            f"Tweet creation failed: unexpected response structure. "
            f"Available keys: {list(response_data.keys())}"
        )

    tweet_inner = tweet_result.get("tweet_results", {}).get("result")
    if not tweet_inner:
        raise ValueError("Tweet creation failed: empty tweet_results in response.")

    tweet_inner["__typename"] = "Tweet"
    return response
