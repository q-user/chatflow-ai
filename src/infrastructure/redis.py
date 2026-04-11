from redis.asyncio import ConnectionPool, Redis

from infrastructure.config import settings

# Singleton connection pool — shared across the application
_pool = ConnectionPool.from_url(settings.redis_url, decode_responses=False)

# Redis client using the shared pool
redis = Redis(connection_pool=_pool)
