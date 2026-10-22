"""Bounded, thread-safe, single-process authentication throttling."""
from collections import deque
import math
from threading import Lock
import time


class RateLimited(Exception):
    def __init__(self, retry_after):
        self.retry_after = max(1, math.ceil(retry_after))
        super().__init__('Too many attempts.')


class AttemptLimiter:
    def __init__(self, limit=5, window=900, max_keys=2048, clock=time.monotonic):
        self.limit = limit
        self.window = window
        self.max_keys = max_keys
        self.clock = clock
        self.attempts = {}
        self.lock = Lock()

    def check(self, key):
        with self.lock:
            now = self.clock()
            bucket = self.attempts.get(key)
            if bucket is not None:
                while bucket and bucket[0] <= now - self.window:
                    bucket.popleft()
            if bucket is None:
                if len(self.attempts) >= self.max_keys:
                    for old_key in list(self.attempts):
                        old = self.attempts[old_key]
                        while old and old[0] <= now - self.window:
                            old.popleft()
                        if not old:
                            del self.attempts[old_key]
                    if len(self.attempts) >= self.max_keys:
                        earliest = min(values[0] for values in self.attempts.values())
                        raise RateLimited(earliest + self.window - now)
                bucket = self.attempts[key] = deque()
            if len(bucket) >= self.limit:
                raise RateLimited(bucket[0] + self.window - now)
            bucket.append(now)
