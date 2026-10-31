from dataclasses import dataclass, field
import math
import statistics
from typing import List, Optional


@dataclass
class RequestTelemetry:
    target_name: str
    model: str
    protocol: str
    status_code: int
    total_ms: float = 0.0
    ttft_ms: Optional[float] = None
    ttfrt_ms: Optional[float] = None  # Time to First Reasoning Token
    tpot_ms: Optional[float] = None
    tps: Optional[float] = None
    itl_deltas_ms: List[float] = field(default_factory=list)
    chunk_count: int = 0
    reasoning_chunks: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    ratelimit_remaining_req: Optional[str] = None
    ratelimit_remaining_tok: Optional[str] = None
    error: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return self.status_code == 200 and self.ttft_ms is not None and self.chunk_count > 0

    @property
    def itl_cv(self) -> float:
        """Coefficient of Variation (StdDev / Mean) of Inter-Token Latency to detect proxy buffering."""
        if len(self.itl_deltas_ms) < 4:
            return 0.0
        mean_itl = statistics.mean(self.itl_deltas_ms)
        if mean_itl <= 0.001:
            return 9.99
        return statistics.stdev(self.itl_deltas_ms) / mean_itl


def calc_percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * (p / 100.0)
    f = math.floor(k)
    c = min(f + 1, len(ordered) - 1)
    return ordered[f] + (k - f) * (ordered[c] - ordered[f])


@dataclass
class TargetSummary:
    target_name: str
    model: str
    protocol: str
    total_requests: int
    success_count: int
    failed_count: int
    rate_limited_429: int
    goodput_pct: float
    ttft_p50: float
    ttft_p95: float
    ttft_p99: float
    ttft_mean: float
    tpot_p50: float
    tpot_p95: float
    tpot_mean: float
    tps_mean: float
    jitter_cv_mean: float
    stream_health_label: str
    cache_hit_pct: float
    sample_error: Optional[str] = None
    ratelimit_snapshot: Optional[str] = None


def aggregate_telemetry(
    target_name: str,
    model: str,
    protocol: str,
    records: List[RequestTelemetry],
    slo_ttft_ms: float = 1000.0,
    slo_tpot_ms: float = 25.0,
) -> TargetSummary:
    ok = [r for r in records if r.is_success]
    failed = [r for r in records if not r.is_success]
    r429 = sum(1 for r in records if r.status_code == 429)

    if not ok:
        err_msg = failed[0].error if failed else "No valid stream chunks received"
        return TargetSummary(
            target_name=target_name,
            model=model,
            protocol=protocol,
            total_requests=len(records),
            success_count=0,
            failed_count=len(failed),
            rate_limited_429=r429,
            goodput_pct=0.0,
            ttft_p50=0.0,
            ttft_p95=0.0,
            ttft_p99=0.0,
            ttft_mean=0.0,
            tpot_p50=0.0,
            tpot_p95=0.0,
            tpot_mean=0.0,
            tps_mean=0.0,
            jitter_cv_mean=0.0,
            stream_health_label="FAILED",
            cache_hit_pct=0.0,
            sample_error=err_msg,
        )

    ttfts = [r.ttft_ms for r in ok if r.ttft_ms is not None]
    tpots = [r.tpot_ms for r in ok if r.tpot_ms is not None]
    tpss = [r.tps for r in ok if r.tps is not None]
    cvs = [r.itl_cv for r in ok]

    slo_met = sum(
        1
        for r in ok
        if (r.ttft_ms or 999999) <= slo_ttft_ms and (r.tpot_ms or 999999) <= slo_tpot_ms
    )
    goodput_pct = (slo_met / len(records)) * 100.0

    mean_cv = statistics.mean(cvs) if cvs else 0.0
    if mean_cv > 1.85:
        health = f"Buffered (CV={mean_cv:.2f})"
    elif mean_cv > 1.15:
        health = f"Jittery (CV={mean_cv:.2f})"
    else:
        health = f"Smooth (CV={mean_cv:.2f})"

    total_in = sum(r.input_tokens for r in ok)
    total_cached = sum(r.cached_tokens for r in ok)
    cache_pct = (total_cached / total_in * 100.0) if total_in > 0 else 0.0

    rl_snap = None
    for r in reversed(ok):
        if r.ratelimit_remaining_tok or r.ratelimit_remaining_req:
            rl_snap = f"Req:{r.ratelimit_remaining_req or '?'} | Tok:{r.ratelimit_remaining_tok or '?'}"
            break

    return TargetSummary(
        target_name=target_name,
        model=model,
        protocol=protocol,
        total_requests=len(records),
        success_count=len(ok),
        failed_count=len(failed),
        rate_limited_429=r429,
        goodput_pct=goodput_pct,
        ttft_p50=calc_percentile(ttfts, 50),
        ttft_p95=calc_percentile(ttfts, 95),
        ttft_p99=calc_percentile(ttfts, 99),
        ttft_mean=statistics.mean(ttfts),
        tpot_p50=calc_percentile(tpots, 50),
        tpot_p95=calc_percentile(tpots, 95),
        tpot_mean=statistics.mean(tpots),
        tps_mean=statistics.mean(tpss),
        jitter_cv_mean=mean_cv,
        stream_health_label=health,
        cache_hit_pct=cache_pct,
        sample_error=failed[0].error if failed else None,
        ratelimit_snapshot=rl_snap,
    )
