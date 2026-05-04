from threading import Lock as ThreadLock

from redis.asyncio import ConnectionPool, Redis
from typing import Optional

from infrastructure.config import settings

_pool: Optional[ConnectionPool] = None
_redis_client: Optional[Redis] = None
_redis_init_lock = ThreadLock()


def get_redis() -> Redis:
    """Get the singleton Redis client with lazy initialization (thread-safe)."""
    global _pool, _redis_client
    if _redis_client is None:
        with _redis_init_lock:
            if _redis_client is None:
                if not settings.redis_url:
                    raise RuntimeError("REDIS_URL is not configured in settings")
                _pool = ConnectionPool.from_url(
                    settings.redis_url, decode_responses=False
                )
                _redis_client = Redis(connection_pool=_pool)
    return _redis_client


# For backward compatibility with existing imports, use a proxy or change imports.
# However, creating 'redis' as a call to get_redis() at import time
# still triggers the init.
# To be truly lazy, all code should call get_redis().
# But since existing code uses 'from infrastructure.redis import redis',
# let's use a wrapper class.


class RedisProxy(Redis):
    """Lazy Redis proxy — delegates all calls to the real client on first access."""

    def __init__(self) -> None:
        # Do NOT call super().__init__() — we defer connection until first use
        pass

    def __getattr__(self, name):
        client = get_redis()
        return getattr(client, name)


redis = RedisProxy()
