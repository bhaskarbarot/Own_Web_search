"""In-process request metrics: counts, errors, latency percentiles, in-flight gauge, Prometheus text format."""
import threading
import time
from collections import deque

BUCKETS = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)


def percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.started = time.time()
        self.endpoints = {}
        self.inflight = 0
        self.by_agent = {}

    def begin(self):
        with self.lock:
            self.inflight += 1

    def end(self, endpoint, status, ms, agent=None):
        with self.lock:
            self.inflight -= 1
            e = self.endpoints.get(endpoint)
            if e is None:
                e = self.endpoints[endpoint] = {"count": 0, "errors_4xx": 0, "errors_5xx": 0, "total_ms": 0.0,
                                                "recent": deque(maxlen=4096), "buckets": [0] * (len(BUCKETS) + 1)}
            e["count"] += 1
            e["total_ms"] += ms
            e["recent"].append(ms)
            if 400 <= status < 500:
                e["errors_4xx"] += 1
            elif status >= 500:
                e["errors_5xx"] += 1
            for i, b in enumerate(BUCKETS):
                if ms <= b:
                    e["buckets"][i] += 1
                    break
            else:
                e["buckets"][-1] += 1
            if agent:
                self.by_agent[agent] = self.by_agent.get(agent, 0) + 1

    def summary(self):
        with self.lock:
            out = {"uptime_s": round(time.time() - self.started, 1), "inflight": self.inflight,
                   "requests_by_agent": dict(self.by_agent), "endpoints": {}}
            for name, e in self.endpoints.items():
                vals = sorted(e["recent"])
                out["endpoints"][name] = {
                    "count": e["count"], "errors_4xx": e["errors_4xx"], "errors_5xx": e["errors_5xx"],
                    "avg_ms": round(e["total_ms"] / e["count"], 2) if e["count"] else None,
                    "p50_ms": round(percentile(vals, 50), 2) if vals else None,
                    "p95_ms": round(percentile(vals, 95), 2) if vals else None,
                    "p99_ms": round(percentile(vals, 99), 2) if vals else None,
                }
            return out

    def prometheus(self, extra=None):
        lines = ["# TYPE ownsearch_requests_total counter", "# TYPE ownsearch_request_ms histogram",
                 f"ownsearch_inflight {self.inflight}", f"ownsearch_uptime_seconds {time.time() - self.started:.0f}"]
        with self.lock:
            for name, e in self.endpoints.items():
                lab = f'endpoint="{name}"'
                lines.append(f"ownsearch_requests_total{{{lab}}} {e['count']}")
                lines.append(f"ownsearch_errors_total{{{lab},class=\"4xx\"}} {e['errors_4xx']}")
                lines.append(f"ownsearch_errors_total{{{lab},class=\"5xx\"}} {e['errors_5xx']}")
                cum = 0
                for b, n in zip(BUCKETS, e["buckets"]):
                    cum += n
                    lines.append(f"ownsearch_request_ms_bucket{{{lab},le=\"{b}\"}} {cum}")
                lines.append(f"ownsearch_request_ms_bucket{{{lab},le=\"+Inf\"}} {e['count']}")
                lines.append(f"ownsearch_request_ms_sum{{{lab}}} {e['total_ms']:.1f}")
                lines.append(f"ownsearch_request_ms_count{{{lab}}} {e['count']}")
        for k, v in (extra or {}).items():
            lines.append(f"ownsearch_{k} {v}")
        return "\n".join(lines) + "\n"
