import asyncio
import time
from typing import List, Optional
import httpx
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from .models import RequestTelemetry
from .protocols import build_request_spec, parse_sse_line


def extract_ratelimit_headers(headers: httpx.Headers) -> tuple[Optional[str], Optional[str]]:
    req_rem = (
        headers.get("x-ratelimit-remaining-requests")
        or headers.get("anthropic-ratelimit-requests-remaining")
    )
    tok_rem = (
        headers.get("x-ratelimit-remaining-tokens")
        or headers.get("anthropic-ratelimit-tokens-remaining")
        or headers.get("anthropic-ratelimit-output-tokens-remaining")
    )
    return req_rem, tok_rem


async def probe_single_stream(
    client: httpx.AsyncClient,
    target_name: str,
    protocol: str,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    semaphore: asyncio.Semaphore,
    progress: Optional[Progress] = None,
    task_id: Optional[int] = None,
) -> RequestTelemetry:
    url, headers, payload = build_request_spec(
        protocol=protocol,
        base_url=base_url,
        api_key=api_key,
        model=model,
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    telemetry = RequestTelemetry(
        target_name=target_name,
        model=model,
        protocol=protocol,
        status_code=0,
    )

    async with semaphore:
        t0 = time.perf_counter()
        t_first_token: Optional[float] = None
        t_prev_token: Optional[float] = None

        try:
            async with client.stream("POST", url, headers=headers, json=payload, timeout=90.0) as resp:
                telemetry.status_code = resp.status_code
                req_rem, tok_rem = extract_ratelimit_headers(resp.headers)
                telemetry.ratelimit_remaining_req = req_rem
                telemetry.ratelimit_remaining_tok = tok_rem

                if resp.status_code != 200:
                    err_bytes = await resp.aread()
                    telemetry.total_ms = (time.perf_counter() - t0) * 1000.0
                    telemetry.error = err_bytes.decode("utf-8", errors="ignore")[:160].strip()
                    return telemetry

                async for raw_line in resp.aiter_lines():
                    frame = parse_sse_line(protocol, raw_line)
                    if frame is None:
                        continue

                    now = time.perf_counter()

                    if frame.input_tokens > 0:
                        telemetry.input_tokens = frame.input_tokens
                    if frame.output_tokens > 0:
                        telemetry.output_tokens = frame.output_tokens
                    if frame.cached_tokens > 0:
                        telemetry.cached_tokens = frame.cached_tokens

                    if frame.has_reasoning_token:
                        telemetry.reasoning_chunks += 1
                        if telemetry.ttfrt_ms is None:
                            telemetry.ttfrt_ms = (now - t0) * 1000.0

                    if frame.has_content_token or frame.has_reasoning_token:
                        telemetry.chunk_count += 1
                        if t_first_token is None:
                            t_first_token = now
                            telemetry.ttft_ms = (now - t0) * 1000.0
                        else:
                            delta_ms = (now - (t_prev_token or now)) * 1000.0
                            telemetry.itl_deltas_ms.append(delta_ms)
                        t_prev_token = now

                    if frame.is_done:
                        break

            t_end = time.perf_counter()
            telemetry.total_ms = (t_end - t0) * 1000.0

            if t_first_token is not None and telemetry.chunk_count > 0:
                gen_duration_s = max(t_end - t_first_token, 0.001)
                effective_tokens = telemetry.output_tokens or telemetry.chunk_count
                telemetry.tpot_ms = (gen_duration_s * 1000.0) / max(effective_tokens - 1, 1)
                telemetry.tps = effective_tokens / gen_duration_s
            else:
                telemetry.error = "Stream closed with 0 content tokens"

        except Exception as exc:
            telemetry.total_ms = (time.perf_counter() - t0) * 1000.0
            telemetry.error = f"{type(exc).__name__}: {str(exc)[:120]}"
        finally:
            if progress and task_id is not None:
                progress.advance(task_id)

        return telemetry


async def run_target_benchmark(
    target_name: str,
    protocol: str,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    requests_count: int,
    concurrency: int,
    max_tokens: int,
    temperature: float,
) -> List[RequestTelemetry]:
    semaphore = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_keepalive_connections=concurrency, max_connections=concurrency * 2)

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}% ({task.completed}/{task.total})"),
        TimeElapsedColumn(),
    ) as progress:
        task_id = progress.add_task(f"Profiling {target_name} [{model}]", total=requests_count)
        async with httpx.AsyncClient(limits=limits, http2=True) as client:
            tasks = [
                probe_single_stream(
                    client=client,
                    target_name=target_name,
                    protocol=protocol,
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    semaphore=semaphore,
                    progress=progress,
                    task_id=task_id,
                )
                for _ in range(requests_count)
            ]
            return await asyncio.gather(*tasks)
