"""Tests for session management."""

import json
import os
import tempfile
from unittest.mock import MagicMock, AsyncMock
import pytest
from tweety.session import Session, FileSession


class TestSession:
    """Tests for base Session class."""

    @pytest.mark.asyncio
    async def test_save_session(self):
        client = MagicMock()
        session = Session(client)
        assert session.logged_in is False

        cookies = {"ct0": "test_csrf", "auth_token": "test_auth"}
        user = {"id": "123", "username": "testuser"}
        await session.save_session(cookies, user)

        assert session.logged_in is True
        assert session.cookies == cookies
        assert session.user == user

    @pytest.mark.asyncio
    async def test_save_session_preserves_existing_cookies(self):
        client = MagicMock()
        session = Session(client)
        await session.save_session({"ct0": "original"}, {"id": "1"})

        # Save again with None cookies — should preserve
        await session.save_session(None, {"id": "2"})
        assert session.cookies == {"ct0": "original"}
        assert session.user == {"id": "2"}

    @pytest.mark.asyncio
    async def test_save_session_cookies_dict(self):
        """When cookies have to_dict method (like httpx cookies), convert."""
        client = MagicMock()
        session = Session(client)

        mock_cookies = MagicMock()
        mock_cookies.to_dict = MagicMock(return_value={"ct0": "from_dict"})

        await session.save_session(mock_cookies, None)
        assert session.cookies == {"ct0": "from_dict"}

    def test_cookies_dict_returns_dict(self):
        client = MagicMock()
        session = Session(client)
        session.cookies = {"ct0": "val", "auth_token": "tok"}
        assert session.cookies_dict() == {"ct0": "val", "auth_token": "tok"}

    def test_str_representation(self):
        client = MagicMock()
        session = Session(client)
        session.cookies = {"ct0": "abc"}
        result = str(session)
        assert isinstance(result, str)


class TestFileSession:
    """Tests for FileSession persistence."""

    @pytest.mark.asyncio
    async def test_save_and_load(self):
        """Session should persist to file and load back."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_path = os.path.join(tmpdir, "test_user")
            client = MagicMock()
            session = FileSession(client, session_path)

            cookies = {"ct0": "csrf123", "auth_token": "auth456"}
            user = {"id": "789", "username": "testuser"}
            await session.save_session(cookies, user)

            # Verify file exists
            session_file = os.path.join(tmpdir, "test_user.tw_session")
            assert os.path.exists(session_file)

            # Load in new session instance
            client2 = MagicMock()
            session2 = FileSession(client2, session_path)
            assert session2.logged_in is True
            assert session2.cookies == cookies

    @pytest.mark.asyncio
    async def test_nonexistent_session_not_logged_in(self):
        """New session with no saved file should not be logged in."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_path = os.path.join(tmpdir, "nobody")
            client = MagicMock()
            session = FileSession(client, session_path)
            assert session.logged_in is False

    def test_cookies_dict_method(self):
        """cookies_dict should return the cookies dictionary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_path = os.path.join(tmpdir, "test")
            client = MagicMock()
            session = FileSession(client, session_path)
            session.cookies = {"ct0": "test_val", "auth_token": "test_auth"}
            result = session.cookies_dict()
            assert result == {"ct0": "test_val", "auth_token": "test_auth"}

    @pytest.mark.asyncio
    async def test_session_file_path(self):
        """Session file should be created in the directory of the session_name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_path = os.path.join(tmpdir, "myuser")
            client = MagicMock()
            session = FileSession(client, session_path)
            assert session.session_file_path == os.path.join(tmpdir, "myuser.tw_session")

    @pytest.mark.asyncio
    async def test_save_overwrites(self):
        """Saving twice should overwrite the file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_path = os.path.join(tmpdir, "overwrite_test")
            client = MagicMock()
            session = FileSession(client, session_path)

            await session.save_session({"ct0": "first"}, {"id": "1"})
            await session.save_session({"ct0": "second"}, {"id": "2"})

            # Reload
            session2 = FileSession(MagicMock(), session_path)
            assert session2.cookies == {"ct0": "second"}
