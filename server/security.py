from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_token() -> str:
    return "mn_" + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_pairing_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))


def hash_pairing_code(code: str, pepper: str) -> str:
    normalized = code.strip().upper().encode("utf-8")
    return hmac.new(pepper.encode("utf-8"), normalized, hashlib.sha256).hexdigest()


def extract_bearer(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    value = value.strip()
    return value or None


class AttemptLimiter:
    """Small in-memory limiter for the pairing endpoint."""

    def __init__(self, limit: int = 10, window_seconds: float = 300) -> None:
        self.limit = limit
        self.window = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._attempts[key]
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True

    def clear(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)
