"""Errors shared across use cases and adapters without transport dependencies."""


class ProviderError(Exception):
    def __init__(self, message: str, retryable: bool = False, retry_after: float = 0):
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


class ReviewCancelled(Exception):
    """Cooperative cancellation; never cache or publish the partial result."""
