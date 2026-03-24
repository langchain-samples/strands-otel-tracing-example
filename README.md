Tracing for Strands Agents

This project demonstrates how to instrument and trace an example strands agent to LangSmith using OpenTelemetry, enabling you to monitor model & agent performance, latency, and token usage.

🛠 Setup
Clone the repo

### Clone the repo

```
git clone https://github.com/langchain-ai/strands-otel-tracing-example
```

### Create an environment variables file

```
$ cd strands-example
# Copy the .env.example file to .env
cp .env.example .env
```

Fill in fields such as OTel endpoint, headers (project and API key), and AWS credentials

### Package Installation

Ensure you have a recent version of `uv` installed

```
$ uv sync
```

### Run the agent

```
$ uv run otel_strands_share.py
```

You can then see an example [trace](https://smith.langchain.com/public/82ddaf82-66bc-417d-ad2f-5d5649303586/r) in the LangSmith project specified!

### Using in your own project

Copy `langsmith_exporter.py` into your project, then call `setup_langsmith_telemetry()` before creating your agent:

```python
from langsmith_exporter import setup_langsmith_telemetry
from strands import Agent

setup_langsmith_telemetry()
```

This replaces the standard `StrandsTelemetry().setup_otlp_exporter()` call. It wraps the OTLP exporter with a transformation layer that:

- **Flattens span events into attributes** — Strands emits messages as span events (`gen_ai.user.message`, `gen_ai.choice`, etc.), but LangSmith expects them as `gen_ai.prompt` / `gen_ai.completion` span attributes.
- **Converts content blocks** — Translates Bedrock/Converse-shaped blocks (`{"text": "..."}`, `{"toolUse": {...}}`) into LangSmith's format (`{"type": "text", "text": "..."}`, `{"type": "tool_use", ...}`).
- **Maps run types** — Sets `langsmith.span.kind` based on `gen_ai.operation.name` so spans render as the correct type in LangSmith (`chain` for agent invocations, `llm` for model calls, `tool` for tool executions).

The exporter reads endpoint and auth configuration from the standard `OTEL_EXPORTER_OTLP_*` environment variables in this repo's `.env.example` file.
