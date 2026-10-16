"""Default cancellation policy for synchronous callers."""


class NeverCancelled:
    def cancelled(self) -> bool:
        return False
