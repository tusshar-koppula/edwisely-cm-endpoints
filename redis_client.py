import os
import redis

_pool = redis.ConnectionPool(
    host=os.environ.get('REDIS_HOST', 'localhost'),
    port=int(os.environ.get('REDIS_PORT', 6379)),
    password=os.environ.get('REDIS_PASSWORD') or None,
    db=0,
    decode_responses=True
)

redis_client = redis.Redis(connection_pool=_pool)
