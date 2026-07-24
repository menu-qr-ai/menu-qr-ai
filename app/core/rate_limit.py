import math
import threading
import time
from collections import deque
from collections.abc import Callable


class LoginRateLimiter:
    def __init__(
        self,
        *,
        pair_attempts: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.pair_attempts = pair_attempts
        self.email_attempts = pair_attempts * 2
        self.ip_attempts = pair_attempts * 4
        self.window_seconds = window_seconds
        self.clock = clock
        self._attempts: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def retry_after(self, ip: str, email: str) -> int:
        now = self.clock()
        with self._lock:
            self._prune_all(now)
            waits = [
                self._bucket_wait(
                    self._pair_key(ip, email),
                    self.pair_attempts,
                    now,
                ),
                self._bucket_wait(
                    self._email_key(email),
                    self.email_attempts,
                    now,
                ),
                self._bucket_wait(
                    self._ip_key(ip),
                    self.ip_attempts,
                    now,
                ),
            ]
        return max(waits)

    def record_failure(self, ip: str, email: str) -> None:
        now = self.clock()
        with self._lock:
            self._prune_all(now)
            for key in (
                self._pair_key(ip, email),
                self._email_key(email),
                self._ip_key(ip),
            ):
                self._attempts.setdefault(key, deque()).append(now)

    def clear_success(self, ip: str, email: str) -> None:
        with self._lock:
            self._attempts.pop(self._pair_key(ip, email), None)
            self._attempts.pop(self._email_key(email), None)

    def reset(self) -> None:
        with self._lock:
            self._attempts.clear()

    def _bucket_wait(
        self,
        key: str,
        limit: int,
        now: float,
    ) -> int:
        values = self._attempts.get(key)
        if values is None or len(values) < limit:
            return 0
        return max(
            1,
            math.ceil(values[0] + self.window_seconds - now),
        )

    def _prune_all(self, now: float) -> None:
        threshold = now - self.window_seconds
        for key, values in list(self._attempts.items()):
            while values and values[0] <= threshold:
                values.popleft()
            if not values:
                self._attempts.pop(key, None)

    @staticmethod
    def _pair_key(ip: str, email: str) -> str:
        return f"pair:{ip}:{email}"

    @staticmethod
    def _email_key(email: str) -> str:
        return f"email:{email}"

    @staticmethod
    def _ip_key(ip: str) -> str:
        return f"ip:{ip}"
