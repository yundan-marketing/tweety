import asyncio
from tweety.types import ShortUser
from .twDataTypes import User, Tweet
from ..exceptions import RateLimitReached
from ..utils import find_objects, parse_wait_time


class BaseGeneratorClass(dict):

    @staticmethod
    def _get_cursor_(response, cursor_key="Bottom"):
        cursor = find_objects(response, "cursorType", cursor_key, recursive=False, none_value={})
        return cursor.get("value", None)

    def _has_next_page(self, new_cursor):
        if new_cursor == self.cursor or new_cursor is None or not new_cursor:
            return False

        self.cursor = new_cursor
        return True

    @staticmethod
    def _get_entries(response, key_value="TimelineAddEntries"):
        entry = find_objects(response, "type", key_value)

        if not entry:
            return []

        return entry.get('entries', [])

    async def get_next_page(self, cursor=0):
        if cursor == 0 and not self.is_next_page:
            return []

        cursor = cursor if cursor != 0 else self.cursor

        results, cursor, cursor_top = await self.get_page(cursor)
        self.is_next_page = self._has_next_page(cursor)
        self.cursor, self.cursor_top = cursor, cursor_top
        _result_attr = self._RESULT_ATTR
        getattr(self, _result_attr).extend(results)
        self[_result_attr] = getattr(self, _result_attr)
        self['cursor'], self['cursor_top'], self['is_next_page'] = self.cursor, self.cursor_top, self.is_next_page

        for result in results:
            if isinstance(result, (User, ShortUser)):
                self.client._cached_users[str(result.username).lower()] = result.id
            elif isinstance(result, Tweet):
                self.client._cached_users[str(result.author.username).lower()] = result.author.id

                for user in result.user_mentions:
                    self.client._cached_users[str(user.username).lower()] = user.id

                if result.is_retweet and result.retweeted_tweet:
                    self.client._cached_users[str(result.retweeted_tweet.author.username).lower()] = result.retweeted_tweet.author.id

        return results

    async def generator(self):
        this_page = 0
        _rate_limit_retries = 0
        _max_rate_limit_retries = 3
        while this_page != int(self.pages):
            try:
                results = await self.get_next_page()
                _rate_limit_retries = 0  # Reset on success

                if len(results) == 0:
                    break

                yield self, results

                if not self.is_next_page:
                    break

                this_page += 1

                if this_page != self.pages:
                    this_wait_time = parse_wait_time(self.wait_time)
                    await asyncio.sleep(this_wait_time)
            except RateLimitReached as e:
                _rate_limit_retries += 1
                if _rate_limit_retries > _max_rate_limit_retries:
                    raise

                retry_after = getattr(e, 'retry_after', None)
                if retry_after and 0 < retry_after <= 900:  # Wait up to 15 minutes
                    await asyncio.sleep(retry_after + 1)
                else:
                    await asyncio.sleep(60 * _rate_limit_retries)  # Fallback: 60s, 120s, 180s
                # Don't increment this_page — retry the same page
            except asyncio.CancelledError:
                break

    def __repr__(self):
        class_name = self.__class__.__name__
        return "{}(user_id={}, count={})".format(
            class_name, self.user_id, self.__len__()
        )

    def __getitem__(self, index):
        if isinstance(index, str):
            return getattr(self, index)

        return getattr(self, self._RESULT_ATTR)[index]

    def __iter__(self):
        for i in getattr(self, self._RESULT_ATTR):
            yield i

    def __len__(self):
        return len(getattr(self, self._RESULT_ATTR))