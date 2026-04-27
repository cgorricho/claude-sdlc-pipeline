#!/usr/bin/env python3
"""
Fibonacci payload for subagent timeout validation.

Produces one fibonacci number every 30 seconds for a given duration.
Prints timestamped output so the orchestrator can verify actual runtime.

Usage:
    python3 payload.py <duration_minutes> [--start-index N]

The --start-index flag allows resuming from a previous fibonacci index
after a mid-run checkpoint. The payload continues from fib(N) onward.

Examples:
    python3 payload.py 15                # Run for 15 min from fib(0)
    python3 payload.py 52 --start-index 30  # Resume from fib(30) for 52 min
"""

import sys
import time
from datetime import datetime, timezone


def fibonacci(n: int) -> int:
    """Compute the nth fibonacci number iteratively."""
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Usage: python3 payload.py <duration_minutes> [--start-index N]",
            file=sys.stderr,
        )
        sys.exit(1)

    duration_minutes = int(sys.argv[1])
    duration_seconds = duration_minutes * 60
    interval_seconds = 30

    # Parse optional --start-index
    start_index = 0
    if "--start-index" in sys.argv:
        idx = sys.argv.index("--start-index")
        if idx + 1 < len(sys.argv):
            start_index = int(sys.argv[idx + 1])

    start_time = time.monotonic()
    start_wall = datetime.now(timezone.utc).isoformat()
    fib_index = start_index

    print(f"PAYLOAD_START: {start_wall}")
    print(f"PAYLOAD_DURATION: {duration_minutes} minutes ({duration_seconds} seconds)")
    print(f"PAYLOAD_INTERVAL: {interval_seconds} seconds")
    print(f"PAYLOAD_START_INDEX: {start_index}")
    print("---")

    while True:
        elapsed = time.monotonic() - start_time
        if elapsed >= duration_seconds:
            break

        fib_value = fibonacci(fib_index)
        now = datetime.now(timezone.utc).isoformat()
        print(
            f"TICK {fib_index:04d} | elapsed={int(elapsed):5d}s | "
            f"fib({fib_index})={fib_value} | {now}"
        )
        sys.stdout.flush()

        fib_index += 1
        time.sleep(interval_seconds)

    end_wall = datetime.now(timezone.utc).isoformat()
    total_elapsed = int(time.monotonic() - start_time)
    max_fib_idx = fib_index - 1 if fib_index > start_index else start_index
    max_fib = fibonacci(max_fib_idx)

    print("---")
    print(f"PAYLOAD_END: {end_wall}")
    print(f"PAYLOAD_ELAPSED: {total_elapsed} seconds")
    print(f"PAYLOAD_TICKS: {fib_index - start_index}")
    print(f"PAYLOAD_MAX_FIB_INDEX: {max_fib_idx}")
    print(f"PAYLOAD_MAX_FIB_VALUE: {max_fib}")
    print("PAYLOAD_STATUS: COMPLETE")


if __name__ == "__main__":
    main()

