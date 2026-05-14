"""Per-source rate limiting via Redis token bucket.

Lua script ensures atomic check-and-decrement. Blocks until a token is
available or `timeout` elapses (whichever comes first).
"""
from __future__ import annotations

import time

import redis

from shared.config import get_settings
from shared.logging import get_logger

log = get_logger("scraper.ratelimit")

# atomic token bucket
_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local capacity = tonumber(ARGV[3])

local bucket = redis.call('HMGET', key, 'tokens', 'updated')
local tokens = tonumber(bucket[1])
local updated = tonumber(bucket[2])

if tokens == nil then
  tokens = capacity
  updated = now
end

local delta = math.max(0, now - updated)
tokens = math.min(capacity, tokens + delta * rate)

if tokens >= 1 then
  tokens = tokens - 1
  redis.call('HMSET', key, 'tokens', tokens, 'updated', now)
  redis.call('EXPIRE', key, 600)
  return 1
end

redis.call('HMSET', key, 'tokens', tokens, 'updated', now)
redis.call('EXPIRE', key, 600)
return 0
"""


class TokenBucket:
    def __init__(self, name: str, rate_per_sec: float, capacity: float | None = None) -> None:
        self.name = name
        self.rate = float(rate_per_sec)
        self.capacity = float(capacity if capacity is not None else max(rate_per_sec * 3, 3.0))
        self._redis = redis.from_url(get_settings().redis_url)
        self._script = self._redis.register_script(_LUA)

    def acquire(self, timeout_s: float = 30.0, poll_s: float = 0.1) -> None:
        """Block until a token is acquired or timeout elapses."""
        deadline = time.monotonic() + timeout_s
        key = f"rl:{self.name}"
        while True:
            ok = int(
                self._script(
                    keys=[key],
                    args=[time.time(), self.rate, self.capacity],
                )
            )
            if ok:
                return
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Rate-limit acquire timeout for {self.name}")
            time.sleep(poll_s)
