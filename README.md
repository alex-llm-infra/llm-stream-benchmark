<div align="center">

# ⚡ llm-stream-benchmark

**Production-Grade SSE Streaming Profiler, Jitter Analyzer & Multi-Provider Benchmark Suite for LLM Gateways**

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](#)
[![HTTP/2 Async](https://img.shields.io/badge/Transport-HTTP%2F2_Async-00ADD8?style=flat-square)](#)
[![Protocols](https://img.shields.io/badge/Protocols-OpenAI_%7C_Anthropic_Native-orange?style=flat-square)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg?style=flat-square)](#)

<!-- TELEMETRY-STAMP:START -->![Last Probe](https://img.shields.io/badge/Last_Upstream_Probe-Passing-brightgreen?style=flat-square)<!-- TELEMETRY-STAMP:END -->

</div>

---

## 📖 Overview

`llm-stream-benchmark` (`llm-bench`) is an asynchronous telemetry and load-testing CLI purpose-built for **AI Infrastructure Engineers** and **LLM Gateway Operators**.

While general tools only measure end-to-end request duration, `llm-bench` operates at the **raw SSE (Server-Sent Events) frame layer**. It measures exact millisecond arrival deltas across every chunk to expose **upstream rate-limit throttling**, **reverse-proxy buffering (fake streaming)**, **reasoning-phase bottlenecks**, and **Prompt Caching efficiency**.

---

## ✨ Core Capabilities

- **🧬 Dual-Protocol Native Engine**: Zero-dependency SSE state machines for both **OpenAI (`/v1/chat/completions`)** and **Anthropic Native (`/v1/messages`)** protocols (fully compatible with Claude Code and extended thinking payloads).
- **🧠 Reasoning vs. Content Isolation**: Separates **TTFRT** (*Time to First Reasoning Token*) from **TTFCT** (*Time to First Content Token*) for hybrid reasoning models (`claude-3-7-sonnet`, `deepseek-reasoner`, `o3`/`o4-mini`).
- **🕵️ Proxy Buffering & Fake-Stream Detector**: Calculates **ITL (Inter-Token Latency) Coefficient of Variation (CV)** and burst ratios to detect whether an upstream proxy is silently buffering chunks or simulating streams.
- **💰 Prompt Cache & Rate-Limit Auditing**: Inspects response headers (`x-ratelimit-remaining-tokens`, `anthropic-ratelimit-*`) and final usage chunks to verify **Prompt Cache Read Hit Rates (%)**.
- **🎯 SLO Goodput Evaluation**: Calculates the exact percentage of requests meeting strict production Service Level Objectives (e.g., `TTFT < 1000ms` and `TPOT < 25ms`).
- **📊 Multi-Target Matrix & Auto-Export**: Run head-to-head comparisons across Direct Tier-5, AWS Bedrock, GCP Vertex, and custom gateways via YAML, exporting clean **Markdown tables** and **JSON telemetry**.

---

## 🏗️ Telemetry Timeline Architecture

```text
Request Dispatched (t0)
  │
  ├─► [TLS / Edge Handshake] ──► HTTP 200 Headers Received (Rate-Limit Headers Captured)
  │
  ├─► [Prefill & Queueing]   ──► First Reasoning Delta (t_reason) ──► TTFRT = t_reason - t0
  │
  ├─► [Thinking Phase]       ──► First Content Delta   (t_first)  ──► TTFT  = t_first  - t0
  │
  ├─► [SSE Generation]       ──► Chunk_2 ... Chunk_N   (Δt_i)     ──► ITL / TPOT & Jitter CV
  │
  └─► [Stream EOF `[DONE]`]  ──► Usage Audit (Cache Hit % & Total TPS)
```

---

## 🚀 Installation

```bash
git clone [https://github.com/YOUR_USERNAME/llm-stream-benchmark.git](https://github.com/YOUR_USERNAME/llm-stream-benchmark.git)
cd llm-stream-benchmark
pip install -e .
```

---

## 💻 Usage Examples

### 1. Single Endpoint Deep Profile (OpenAI or Compatible Gateway)
```bash
export LLM_API_KEY="sk-..."

llm-bench run \
  --url "[https://api.openai.com/v1](https://api.openai.com/v1)" \
  --model "gpt-4o" \
  --requests 20 \
  --concurrency 5 \
  --slo-ttft 800 \
  --slo-tpot 20 \
  --export-md report_gpt4o.md
```

### 2. Native Anthropic Protocol Profile (with Prompt Caching & Thinking Audit)
```bash
export ANTHROPIC_API_KEY="sk-ant-..."

llm-bench run \
  --protocol anthropic \
  --url "[https://api.anthropic.com/v1](https://api.anthropic.com/v1)" \
  --model "claude-3-7-sonnet-20250219" \
  --requests 10 \
  --concurrency 4
```

### 3. Multi-Provider Matrix Comparison (YAML Driven)
Compare multiple upstreams (e.g., Official Direct vs. AWS Bedrock vs. Internal Gateway) in one run:
```bash
llm-bench matrix --config configs/matrix.example.yaml --export-md benchmark_matrix.md
```

---

## 📊 Sample Terminal & Markdown Output

| Target / Upstream | Model | Success | Goodput (SLO) | P50 TTFT | P95 TTFT | Mean TPOT | Mean TPS | Stream Health (Jitter) | Cache Hit |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **OpenAI-Tier5-Direct** | `gpt-4o` | 100% | 95.0% | 398 ms | 642 ms | 11.4 ms | 87.7 /s | `Smooth (CV=0.31)` | 78.4% |
| **Anthropic-Direct** | `claude-3-7-sonnet` | 100% | 90.0% | 675 ms | 1,090 ms | 13.9 ms | 71.9 /s | `Smooth (CV=0.38)` | 88.2% |
| **Cloudflare-Edge-Gateway** | `claude-3-7-sonnet` | 100% | 90.0% | 688 ms | 1,105 ms | 14.1 ms | 70.9 /s | `Smooth (CV=0.40)` | 88.2% |
| **Misconfigured-Nginx-Proxy** | `gpt-4o` | 100% | 15.0% | 2,840 ms | 4,120 ms | 3.2 ms* | 312.5 /s* | `⚠️ Buffered (CV=2.85)` | 0.0% |

> **Note on Stream Health**: A high Coefficient of Variation (`CV > 1.8`) combined with abnormally low TPOT indicates **upstream proxy chunk buffering** (chunks are held in buffer and flushed in batches rather than streamed token-by-token).

---

## 📐 Metric Definitions

| Metric | Full Name | Formula / Definition |
| :--- | :--- | :--- |
| **TTFT** | Time to First Token | `t_first_token - t_request_start` (ms). Includes network RTT, prompt prefill, and queue wait. |
| **TTFRT** | Time to First Reasoning Token | `t_first_reasoning_chunk - t_request_start` (ms) for reasoning models. |
| **TPOT** | Time Per Output Token | `(t_last_token - t_first_token) / (output_chunks - 1)` (ms). Generation pace excluding TTFT. |
| **ITL Jitter (CV)** | Inter-Token Latency Variance | `StdDev(ITL) / Mean(ITL)`. Measures streaming smoothness vs. proxy buffering stalls. |
| **Goodput %** | SLO Compliance Rate | Percentage of completed requests satisfying both `TTFT <= SLO_TTFT` and `TPOT <= SLO_TPOT`. |

---

## 📄 License
MIT License.
