from tweety import TwitterAsync
import asyncio


async def token_auth():
    app = TwitterAsync("test.tw_session")
    await app.load_auth_token("50c3ec893ae46bccf1968a7327d45f1b82653819")
    print(app.me.username)


if __name__ == '__main__':
    asyncio.run(token_auth())
