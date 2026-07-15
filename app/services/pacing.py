import time


class GroupedCallPacer:
    """Spaces API calls and pauses before each new group."""

    def __init__(
            self,
            *,
            calls_per_group: int = 3,
            request_interval_seconds: int = 20,
            cooldown_seconds: int = 60,
            sleep_fn=time.sleep,
            log_prefix: str = "API",
    ):
        self.calls_per_group = calls_per_group
        self.request_interval_seconds = request_interval_seconds
        self.cooldown_seconds = cooldown_seconds
        self.sleep_fn = sleep_fn
        self.log_prefix = log_prefix
        self.call_count = 0

    def before_call(self) -> None:
        if self.call_count and self.call_count % self.calls_per_group == 0:
            print(f"{self.log_prefix}_COOLDOWN_SECONDS={self.cooldown_seconds}")
            self.sleep_fn(self.cooldown_seconds)
        elif self.call_count:
            print(
                f"{self.log_prefix}_REQUEST_INTERVAL_SECONDS="
                f"{self.request_interval_seconds}"
            )
            self.sleep_fn(self.request_interval_seconds)

        self.call_count += 1
        print(f"{self.log_prefix}_API_CALL={self.call_count}")
