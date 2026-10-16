"""Production time adapter; tests can inject a controllable clock."""

import time


class SystemClock:
    def now(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float):
        time.sleep(seconds)
