from dataclasses import asdict
import datetime
import json
from typing import List
from rich.console import Console
from rich.table import Table

from .models import TargetSummary

console = Console()


def render_terminal_summary(summaries: List[TargetSummary]) -> None:
    table = Table(title="⚡ LLM SSE Streaming Telemetry & Gateway Audit", show_lines=True)
    table.add_column("Target / Channel", style="bold cyan")
    table.add_column("Model", style="white")
    table.add_column("Success (429s)", justify="center")
    table.add_column("Goodput (SLO)", justify="right", style="green")
    table.add_column("P50 TTFT", justify="right")
    table.add_column("P95 TTFT", justify="right", style="yellow")
    table.add_column("Mean TPOT", justify="right")
    table.add_column("Throughput", justify="right", style="bold green")
    table.add_column("Stream Health (Jitter)", justify="center")
    table.add_column("Cache Hit", justify="right", style="magenta")

    for s in summaries:
        succ_str = f"{s.success_count}/{s.total_requests} ({s.rate_limited_429})"
        table.add_row(
            s.target_name,
            s.model,
            succ_str,
            f"{s.goodput_pct:.1f}%",
            f"{s.ttft_p50:.0f} ms",
            f"{s.ttft_p95:.0f} ms",
            f"{s.tpot_mean:.1f} ms",
            f"{s.tps_mean:.1f} tok/s",
            s.stream_health_label,
            f"{s.cache_hit_pct:.1f}%",
        )

    console.print()
    console.print(table)
    for s in summaries:
        if s.ratelimit_snapshot:
            console.print(f"  [dim]• {s.target_name} Upstream Quota Header Snapshot: {s.ratelimit_snapshot}[/dim]")
        if s.sample_error:
            console.print(f"  [bold red]• {s.target_name} Sample Error:[/bold red] {s.sample_error}")
    console.print()


def export_markdown_report(summaries: List[TargetSummary], filepath: str) -> None:
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"### 📊 LLM Streaming Benchmark Report ({now})",
        "",
        "| Target / Upstream | Model | Success | Goodput (SLO) | P50 TTFT | P95 TTFT | Mean TPOT | Mean TPS | Stream Health (Jitter) | Cache Hit |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for s in summaries:
        succ_pct = (s.success_count / max(s.total_requests, 1)) * 100.0
        lines.append(
            f"| **{s.target_name}** | `{s.model}` | {succ_pct:.0f}% | {s.goodput_pct:.1f}% | "
            f"{s.ttft_p50:.0f} ms | {s.ttft_p95:.0f} ms | {s.tpot_mean:.1f} ms | "
            f"{s.tps_mean:.1f} /s | `{s.stream_health_label}` | {s.cache_hit_pct:.1f}% |"
        )

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    console.print(f"[bold green]✔ Markdown report exported to:[/bold green] {filepath}")


def export_json_report(summaries: List[TargetSummary], filepath: str) -> None:
    payload = {
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "results": [asdict(s) for s in summaries],
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    console.print(f"[bold green]✔ JSON telemetry exported to:[/bold green] {filepath}")
