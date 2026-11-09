"""Redis when reachable, otherwise a small in-process cache with the same interface."""

import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

from .settings import get_settings

log = logging.getLogger("agentkit.cache")


class MemoryCache:
    backend = "memory"

    def __init__(self) -> None:
        self._d: Dict[str, Tuple[Any, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            v = self._d.get(key)
            if not v:
                return None
            if v[1] and v[1] < time.time():
                self._d.pop(key, None)
                return None
            return v[0]

    def set(self, key: str, value: str, ttl: int = 0) -> None:
        with self._lock:
            self._d[key] = (value, time.time() + ttl if ttl else 0)
            if len(self._d) > 20000:  # crude bound
                for k in list(self._d)[:5000]:
                    self._d.pop(k, None)

    def incr(self, key: str, ttl: int) -> int:
        with self._lock:
            v = self._d.get(key)
            now = time.time()
            if not v or (v[1] and v[1] < now):
                self._d[key] = (1, now + ttl)
                return 1
            self._d[key] = (v[0] + 1, v[1])
            return v[0] + 1

    def ping(self) -> bool:
        return True


class RedisCache:
    backend = "redis"

    def __init__(self, client) -> None:
        self.r = client

    def get(self, key: str) -> Optional[str]:
        try:
            return self.r.get(key)
        except Exception:
            return None

    def set(self, key: str, value: str, ttl: int = 0) -> None:
        try:
            self.r.set(key, value, ex=ttl or None)
        except Exception:
            pass

    def incr(self, key: str, ttl: int) -> int:
        try:
            p = self.r.pipeline()
            p.incr(key)
            p.expire(key, ttl, nx=True)
            return int(p.execute()[0])
        except Exception:
            return 0  # fail open: a cache outage must not block users

    def ping(self) -> bool:
        try:
            return bool(self.r.ping())
        except Exception:
            return False


_cache = None


def get_cache():
    global _cache
    if _cache is not None:
        return _cache
    url = get_settings().redis_url
    if url:
        try:
            import redis

            client = redis.from_url(url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
            client.ping()
            _cache = RedisCache(client)
            log.info("cache: redis connected")
            return _cache
        except Exception as exc:
            log.warning("cache: redis unavailable (%s); using in-process memory", type(exc).__name__)
    _cache = MemoryCache()
    return _cache


def rate_limited(key: str, limit: int, window: int = 60) -> bool:
    """True when the caller has used up its budget for this window."""
    n = get_cache().incr(f"rl:{key}:{int(time.time() // window)}", window + 1)
    return n > limit
