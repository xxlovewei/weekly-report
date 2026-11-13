import asyncio
import logging
from contextlib import asynccontextmanager

from psycopg import AsyncConnection

from .db import engine

logger = logging.getLogger(__name__)

# 一个 API 进程共享一个 PostgreSQL 监听连接，每个标签页只占用一个异步事件。
subscribers: dict[asyncio.Event, tuple[int, bool]] = {}


async def listen_for_notifications(ready: asyncio.Event):
    dsn = engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    while True:
        try:
            async with await AsyncConnection.connect(dsn, autocommit=True, connect_timeout=5) as conn:
                await conn.execute("LISTEN zhoubao_messages")
                ready.set()
                for event in subscribers:
                    event.set()
                async for message in conn.notifies():
                    for event, (user_id, admin) in subscribers.items():
                        if admin or str(user_id) == message.payload:
                            event.set()
        except Exception:
            logger.warning("消息监听连接暂不可用，稍后重连")
        await asyncio.sleep(2)


@asynccontextmanager
async def notification_lifespan(app):
    app.state.notifications_ready = asyncio.Event()
    listener = asyncio.create_task(listen_for_notifications(app.state.notifications_ready))
    try:
        yield
    finally:
        listener.cancel()
        await asyncio.gather(listener, return_exceptions=True)
