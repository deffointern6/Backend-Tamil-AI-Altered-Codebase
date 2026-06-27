import sys
import os

# Add current directory to path so we can import utils correctly
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.metrics import calculate_metrics

def print_section(title, data):
    print("=" * 65)
    print(f" {title.upper()} ")
    print("=" * 65)
    
    if not data or data.get("total_requests", 0) == 0:
        print("  No requests recorded in this window.")
        print()
        return

    print(f"  Total Requests: {data['total_requests']}")
    print(f"  Failed Requests: {data['failed_requests']['total']}")
    
    if data['failed_requests']['per_model']:
        print("  Failures by Model:")
        for model, count in data['failed_requests']['per_model'].items():
            print(f"    - {model}: {count}")

    print("  Requests & Latency:")
    for model, count in data['requests_per_model'].items():
        p95 = data['p95_latency_per_model'].get(model, 0.0)
        print(f"    - {model}: {count} requests (P95 Latency: {p95:.3f}s)")

    if data['space_wake_up_delays']:
        print("  Space Wake-Up Delays:")
        for model, info in data['space_wake_up_delays'].items():
            print(f"    - {model}: {info['count']} wake-ups")
            print(f"      Total delay: {info['total_delay_seconds']:.2f}s")
            print(f"      Average delay: {info['avg_delay_seconds']:.2f}s")
            print(f"      Max delay: {info['max_delay_seconds']:.2f}s")
    print()

def main():
    try:
        metrics = calculate_metrics()
    except Exception as e:
        print(f"Error calculating metrics: {e}")
        sys.exit(1)

    print("\n" + "*" * 65)
    print(" TAMIL AI BACKEND - DEPLOYMENT METRICS SUMMARY ")
    print("*" * 65)
    q_depth = metrics['queue_depth']
    q_depth_str = str(q_depth) if q_depth >= 0 else "Error fetching"
    print(f"  Current Live Queue Depth: {q_depth_str}")
    print()

    print_section("Last 1 Minute (Real-time)", metrics["last_1_min"])
    print_section("Last 5 Minutes (Deployment Verification Window)", metrics["last_5_min"])
    print_section("Last 1 Hour", metrics["last_1_hour"])
    print_section("Last 24 Hours", metrics["last_24_hours"])
    print_section("All Time", metrics["all_time"])

if __name__ == "__main__":
    main()
