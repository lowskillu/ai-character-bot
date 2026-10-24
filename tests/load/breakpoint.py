"""Breakpoint test: raise the arrival rate until the bot stops keeping up.

Answers "where is the actual ceiling", as opposed to the fixed-rate run in
driver.py which only shows that a given target is met.

The signal to watch is not throughput but **latency growth**. The stub LLM has a
~5s median, so as long as end-to-end p50 stays near 5s the bot is keeping pace.
Once p50 climbs above that, requests are queueing somewhere inside the bot and
the ceiling has been passed.

    python -m tests.load.breakpoint
"""

import argparse
import json
import subprocess
import sys

RATES = [8, 24, 48, 96, 160]


def run_one(rate: float, users: int, duration: int, drain: int) -> dict:
    cmd = [
        sys.executable, "-m", "tests.load.driver",
        "--users", str(users),
        "--rate", str(rate),
        "--duration", str(duration),
        "--drain", str(drain),
        # Exact reply/send pairing; see the note in driver.run().
        "--unique-users",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    start = out.stdout.find("{")
    if start < 0:
        return {"error": (out.stdout + out.stderr)[-500:]}
    return json.loads(out.stdout[start:])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=500)
    ap.add_argument("--duration", type=int, default=30)
    ap.add_argument("--drain", type=int, default=120)
    args = ap.parse_args()

    rows = []
    for rate in RATES:
        print(f"\n=== {rate} msg/s ===", flush=True)
        r = run_one(rate, args.users, args.duration, args.drain)
        if "error" in r:
            print("  FAILED:", r["error"], flush=True)
            rows.append((rate, None))
            continue
        delivered = r["replies_delivered"]
        sent = r["updates_sent"]
        print(
            f"  delivered {delivered}/{sent} "
            f"({100 * delivered / sent:.1f}%)  "
            f"p50={r['latency_p50']}s p95={r['latency_p95']}s  "
            f"pg={r['pg_connections_max']} idle_tx={r['idle_in_transaction_max']}  "
            f"http_err={r['http_errors']}",
            flush=True,
        )
        rows.append((rate, r))

    print("\n" + "=" * 78)
    print(f"{'rate':>6} {'delivered':>12} {'p50':>8} {'p95':>8} {'pg':>4} {'idle_tx':>8} {'errors':>7}")
    print("=" * 78)
    for rate, r in rows:
        if r is None:
            print(f"{rate:>6} {'RUN FAILED':>12}")
            continue
        pct = 100 * r["replies_delivered"] / r["updates_sent"]
        print(
            f"{rate:>6} {r['replies_delivered']:>5}/{r['updates_sent']:<6} "
            f"{pct:>4.0f}% {str(r['latency_p50']):>7} {str(r['latency_p95']):>8} "
            f"{r['pg_connections_max']:>4} {r['idle_in_transaction_max']:>8} {r['http_errors']:>7}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
