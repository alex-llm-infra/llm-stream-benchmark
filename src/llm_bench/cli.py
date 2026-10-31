import argparse
import asyncio
import os
import sys
import yaml
from rich.console import Console

from .engine import run_target_benchmark
from .models import aggregate_telemetry
from .reporter import export_json_report, export_markdown_report, render_terminal_summary

console = Console()

DEFAULT_PROMPT = (
    "Explain the architecture of HTTP/2 multiplexing and how it prevents "
    "head-of-line blocking at the application layer in 3 concise paragraphs."
)


async def cmd_run(args: argparse.Namespace) -> None:
    api_key = args.api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[bold red]Error:[/bold red] Missing API Key. Pass --api-key or set LLM_API_KEY.")
        sys.exit(1)

    records = await run_target_benchmark(
        target_name=args.name,
        protocol=args.protocol,
        base_url=args.url,
        api_key=api_key,
        model=args.model,
        prompt=args.prompt,
        requests_count=args.requests,
        concurrency=args.concurrency,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )
    summary = aggregate_telemetry(
        target_name=args.name,
        model=args.model,
        protocol=args.protocol,
        records=records,
        slo_ttft_ms=args.slo_ttft,
        slo_tpot_ms=args.slo_tpot,
    )
    render_terminal_summary([summary])

    if args.export_md:
        export_markdown_report([summary], args.export_md)
    if args.export_json:
        export_json_report([summary], args.export_json)


async def cmd_matrix(args: argparse.Namespace) -> None:
    with open(args.config, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    defaults = cfg.get("defaults", {})
    summaries = []

    for tgt in cfg.get("targets", []):
        name = tgt["name"]
        protocol = tgt.get("protocol", "openai")
        base_url = tgt["base_url"]
        model = tgt["model"]
        key_env = tgt.get("api_key_env", "LLM_API_KEY")
        api_key = tgt.get("api_key") or os.getenv(key_env, "")

        if not api_key:
            console.print(f"[yellow]Skipping {name}: environment variable {key_env} not set.[/yellow]")
            continue

        records = await run_target_benchmark(
            target_name=name,
            protocol=protocol,
            base_url=base_url,
            api_key=api_key,
            model=model,
            prompt=tgt.get("prompt", defaults.get("prompt", DEFAULT_PROMPT)),
            requests_count=tgt.get("requests", defaults.get("requests", 10)),
            concurrency=tgt.get("concurrency", defaults.get("concurrency", 5)),
            max_tokens=tgt.get("max_tokens", defaults.get("max_tokens", 256)),
            temperature=tgt.get("temperature", defaults.get("temperature", 0.2)),
        )
        summaries.append(
            aggregate_telemetry(
                target_name=name,
                model=model,
                protocol=protocol,
                records=records,
                slo_ttft_ms=defaults.get("slo_ttft_ms", 1000.0),
                slo_tpot_ms=defaults.get("slo_tpot_ms", 25.0),
            )
        )

    if summaries:
        render_terminal_summary(summaries)
        if args.export_md:
            export_markdown_report(summaries, args.export_md)
        if args.export_json:
            export_json_report(summaries, args.export_json)


def main() -> None:
    parser = argparse.ArgumentParser(prog="llm-bench", description="Production LLM SSE Streaming Profiler")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_p = subparsers.add_parser("run", help="Profile a single LLM API endpoint")
    run_p.add_argument("--name", default="Primary-Upstream", help="Display label for target")
    run_p.add_argument("--protocol", choices=["openai", "anthropic"], default="openai")
    run_p.add_argument("--url", default=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"))
    run_p.add_argument("--api-key", default=None)
    run_p.add_argument("--model", required=True)
    run_p.add_argument("--requests", type=int, default=10)
    run_p.add_argument("--concurrency", type=int, default=5)
    run_p.add_argument("--max-tokens", type=int, default=256)
    run_p.add_argument("--temperature", type=float, default=0.2)
    run_p.add_argument("--slo-ttft", type=float, default=1000.0, help="TTFT SLO threshold in ms")
    run_p.add_argument("--slo-tpot", type=float, default=25.0, help="TPOT SLO threshold in ms")
    run_p.add_argument("--prompt", default=DEFAULT_PROMPT)
    run_p.add_argument("--export-md", default=None, help="Export Markdown table to file")
    run_p.add_argument("--export-json", default=None, help="Export JSON telemetry to file")

    mat_p = subparsers.add_parser("matrix", help="Run multi-provider matrix benchmark from YAML")
    mat_p.add_argument("--config", required=True, help="Path to matrix YAML configuration")
    mat_p.add_argument("--export-md", default=None)
    mat_p.add_argument("--export-json", default=None)

    args = parser.parse_args()
    if args.command == "run":
        asyncio.run(cmd_run(args))
    elif args.command == "matrix":
        asyncio.run(cmd_matrix(args))


if __name__ == "__main__":
    main()
