from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from glass_sim.trace import iter_trace


def main() -> None:
    parser = argparse.ArgumentParser(description="Print a compact trace profile.")
    parser.add_argument("trace_path")
    parser.add_argument("--max-requests", type=int)
    args = parser.parse_args()

    count = 0
    total_bytes = 0
    io_types: Counter[str] = Counter()
    first_arrival = 0.0
    last_arrival = 0.0
    min_size = None
    max_size = 0

    for request in iter_trace(Path(args.trace_path), args.max_requests):
        count += 1
        total_bytes += request.size_bytes
        io_types[request.io_type] += 1
        last_arrival = request.arrival_s
        min_size = request.size_bytes if min_size is None else min(min_size, request.size_bytes)
        max_size = max(max_size, request.size_bytes)

    span = last_arrival - first_arrival
    print(f"requests={count}")
    print(f"arrival_span_s={span:.6f}")
    print(f"io_types={dict(io_types)}")
    print(f"total_mib={total_bytes / (1024 * 1024):.3f}")
    print(f"size_bytes_min={min_size or 0}")
    print(f"size_bytes_max={max_size}")


if __name__ == "__main__":
    main()
