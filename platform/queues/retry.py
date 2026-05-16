class RetryPolicy:
    def __init__(self, max_attempts: int = 3, base_delay_seconds: int = 5) -> None:
        self.max_attempts = max_attempts
        self.base_delay_seconds = base_delay_seconds

    def next_delay(self, attempts: int) -> int:
        return self.base_delay_seconds * (2 ** max(0, attempts - 1))

    def should_retry(self, attempts: int) -> bool:
        return attempts < self.max_attempts
