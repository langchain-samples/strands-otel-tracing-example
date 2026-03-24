"""Custom OTLP span exporter that transforms Strands OTEL spans into LangSmith-compatible formats.

This module wraps the standard OTLPSpanExporter and intercepts spans before export,
remapping attributes, span names, and structure to align with LangSmith's expected
OTEL ingest schema.

Strands emits GenAI message data as span events (gen_ai.user.message,
gen_ai.assistant.message, gen_ai.choice, etc.), which is non-standard — the OTEL
GenAI semantic conventions define these as Log Events, not span events.  This
exporter flattens those span events into span attributes (gen_ai.prompt,
gen_ai.completion) that LangSmith's server-side OTEL ingest can consume directly.
"""

import json
import logging
from typing import Any, Sequence

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from strands.telemetry import StrandsTelemetry

logger = logging.getLogger(__name__)


class LangSmithSpanExporter(SpanExporter):
    """Span exporter that reformats Strands OTEL spans for LangSmith compatibility.

    Wraps a delegate exporter (typically OTLPSpanExporter pointed at LangSmith's
    OTEL endpoint) and transforms each span before forwarding it.

    Args:
        delegate: The underlying SpanExporter to forward transformed spans to.
    """

    def __init__(self, delegate: SpanExporter) -> None:
        self._delegate = delegate

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Transform spans and forward them to the delegate exporter.

        Args:
            spans: The batch of spans to export.

        Returns:
            The result from the delegate exporter.
        """
        transformed = []
        for span in spans:
            try:
                transformed.append(self._transform_span(span))
            except Exception:
                logger.warning(
                    "Failed to transform span %r, exporting original",
                    span.name,
                    exc_info=True,
                )
                transformed.append(span)
        return self._delegate.export(transformed)

    def shutdown(self) -> None:
        """Shut down the delegate exporter."""
        self._delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Force flush the delegate exporter.

        Args:
            timeout_millis: Maximum time to wait for flush to complete.

        Returns:
            True if flush succeeded.
        """
        return self._delegate.force_flush(timeout_millis)

    # -- gen_ai.operation.name → langsmith.span.kind mapping ---------------

    _OPERATION_TO_RUN_TYPE: dict[str, str] = {
        "chat": "llm",
        "invoke_agent": "chain",
        "execute_tool": "tool",
    }

    # -- Event name → role mapping ----------------------------------------

    _EVENT_ROLE_MAP: dict[str, str] = {
        "gen_ai.user.message": "user",
        "gen_ai.assistant.message": "assistant",
        "gen_ai.system.message": "system",
        "gen_ai.tool.message": "tool",
        "gen_ai.choice": "assistant",
    }

    _MESSAGE_EVENTS: set[str] = {
        "gen_ai.user.message",
        "gen_ai.system.message",
        "gen_ai.tool.message",
        "gen_ai.assistant.message",
        "gen_ai.choice",
    }

    # ----------------------------------------------------------------------

    def _transform_span(self, span: ReadableSpan) -> ReadableSpan:
        """Flatten span events into ``gen_ai.prompt`` / ``gen_ai.completion`` attributes.

        Strands attaches GenAI message data as span events.  LangSmith expects
        them as JSON-serialized span attributes instead.  Each message object
        gets a ``role`` field injected when one can be inferred from the event
        name and isn't already present in the payload.

        All conversation history (user, system, tool, and intermediate assistant
        messages) is placed into ``gen_ai.prompt``.  Only the final
        ``gen_ai.choice`` event — the model's actual response — goes into
        ``gen_ai.completion``.

        Args:
            span: The original Strands span.

        Returns:
            A new ReadableSpan with the message attributes added.
        """
        input_messages: list[dict[str, Any]] = []
        output_messages: list[dict[str, Any]] = []
        remaining_events: list[Any] = []

        for event in span.events:
            name = event.name
            attrs = dict(event.attributes) if event.attributes else {}

            if name == "gen_ai.choice":
                # The final model response is the only true output
                output_messages.append(self._event_to_message(name, attrs))
            elif name in self._MESSAGE_EVENTS:
                # Everything else (user, system, tool, intermediate assistant)
                # is conversation history → input
                input_messages.append(self._event_to_message(name, attrs))
            else:
                # Preserve non-message events as-is
                remaining_events.append(event)

        # Merge new attributes with the originals.
        # LangSmith's server-side OTEL ingest expects inputs under "gen_ai.prompt"
        # and outputs under "gen_ai.completion" (matching the attribute names used
        # by LangSmith's own OTELExporter).
        new_attrs: dict[str, Any] = dict(span.attributes) if span.attributes else {}
        if input_messages:
            new_attrs["gen_ai.prompt"] = json.dumps({"messages": input_messages})
        if output_messages:
            new_attrs["gen_ai.completion"] = json.dumps({"messages": output_messages})

        # Map gen_ai.operation.name to langsmith.span.kind (run type)
        operation = new_attrs.get("gen_ai.operation.name", "")
        run_type = self._OPERATION_TO_RUN_TYPE.get(operation)
        if run_type:
            new_attrs["langsmith.span.kind"] = run_type

        # Strands hardcodes gen_ai.system to "strands-agents" regardless of
        # backend, but LangSmith uses it for ls_provider.
        new_attrs["gen_ai.system"] = "amazon_bedrock"

        return ReadableSpan(
            name=span.name,
            context=span.context,
            parent=span.parent,
            resource=span.resource,
            attributes=new_attrs,
            events=remaining_events,
            links=span.links,
            kind=span.kind,
            status=span.status,
            start_time=span.start_time,
            end_time=span.end_time,
            instrumentation_scope=span.instrumentation_scope,
        )

    def _event_to_message(
        self, event_name: str, attrs: dict[str, Any]
    ) -> dict[str, Any]:
        """Convert a single span event into a message dict, injecting ``role`` if missing.

        For ``gen_ai.choice`` events the content lives under the ``message``
        key; for all other events it lives under ``content``.  In both cases
        the value may be a JSON-encoded string that we parse back so the final
        attribute is cleanly nested.

        Args:
            event_name: The OTEL event name (e.g. ``gen_ai.user.message``).
            attrs: The event's attribute dict.

        Returns:
            A message dict with at least ``role`` and ``content`` keys.
        """
        role = self._EVENT_ROLE_MAP.get(event_name, "unknown")

        # gen_ai.choice stores content in "message", others in "content"
        if event_name == "gen_ai.choice":
            raw = attrs.get("message", "[]")
        else:
            raw = attrs.get("content", "[]")

        # Parse the JSON string back into a list so the final serialized
        # attribute isn't double-encoded.
        try:
            content = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            content = raw

        # Convert Bedrock-shaped content blocks to LangSmith-shaped blocks
        if isinstance(content, list):
            content = [self._convert_content_block(block) for block in content]

        msg: dict[str, Any] = {"role": role, "content": content}

        # Carry over finish_reason for choice events
        if "finish_reason" in attrs:
            msg["finish_reason"] = attrs["finish_reason"]

        return msg

    @staticmethod
    def _convert_content_block(block: Any) -> Any:
        """Convert a single Bedrock/Converse content block to LangSmith format.

        Bedrock uses implicit typing (the key name *is* the type)::

            {"text": "hello"}
            {"toolUse": {"toolUseId": "x", "name": "f", "input": {...}}}
            {"toolResult": {"toolUseId": "x", "status": "success", "content": [...]}}

        LangSmith expects explicit ``type`` fields::

            {"type": "text", "text": "hello"}
            {"type": "tool_use", "id": "x", "name": "f", "input": {...}}
            {"type": "tool_result", "tool_use_id": "x", "status": "success", "content": [...]}

        Unrecognised blocks are returned as-is.
        """
        if not isinstance(block, dict):
            return block

        if "text" in block and len(block) == 1:
            return {"type": "text", "text": block["text"]}

        if "toolUse" in block:
            tu = block["toolUse"]
            return {
                "type": "tool_use",
                "id": tu.get("toolUseId", ""),
                "name": tu.get("name", ""),
                "input": tu.get("input", {}),
            }

        if "toolResult" in block:
            tr = block["toolResult"]
            converted: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": tr.get("toolUseId", ""),
            }
            if "status" in tr:
                converted["status"] = tr["status"]
            if "content" in tr:
                # Recursively convert nested content blocks
                nested = tr["content"]
                if isinstance(nested, list):
                    nested = [
                        LangSmithSpanExporter._convert_content_block(b) for b in nested
                    ]
                converted["content"] = nested
            return converted

        # Unknown block shape — pass through unchanged
        return block


# ---------------------------------------------------------------------------
# Convenience wiring
# ---------------------------------------------------------------------------


def create_langsmith_exporter(**otlp_kwargs) -> LangSmithSpanExporter:
    """Create a LangSmithSpanExporter wrapping a standard OTLPSpanExporter.

    Keyword arguments are forwarded to OTLPSpanExporter (endpoint, headers, etc.).
    If not provided, the exporter will fall back to the standard OTEL_EXPORTER_OTLP_*
    environment variables.

    Returns:
        A ready-to-use LangSmithSpanExporter instance.
    """
    delegate = OTLPSpanExporter(**otlp_kwargs)
    return LangSmithSpanExporter(delegate=delegate)


def setup_langsmith_telemetry() -> None:
    """Wire up Strands telemetry with the LangSmith-compatible exporter.

    Call this instead of (or in addition to) the standard
    ``StrandsTelemetry().setup_otlp_exporter()`` flow.
    """
    telemetry = StrandsTelemetry()
    exporter = create_langsmith_exporter()
    telemetry.tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
