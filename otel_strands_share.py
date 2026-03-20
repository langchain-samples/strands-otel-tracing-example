from dotenv import load_dotenv
from opentelemetry import trace
from strands import Agent
from strands.models import BedrockModel
from strands.telemetry import StrandsTelemetry
from strands_tools import file_read, file_write, journal, python_repl, shell

load_dotenv()

# logging.getLogger("strands").setLevel(logging.INFO)


# Set up an OTEL exporter that will send traces to LangSmith
strands_telemetry = StrandsTelemetry()
strands_telemetry.setup_otlp_exporter()
strands_telemetry.setup_console_exporter()
strands_telemetry.setup_meter(enable_console_exporter=False, enable_otlp_exporter=False)


# Create and invoke strands agent
def create_model():
    return BedrockModel(model_id="global.anthropic.claude-sonnet-4-5-20250929-v1:0")


def review_file(agent, file_path):
    prompt = f"Do a short review of otel_strands_share.py. Focus on key functionality."
    return agent(prompt)


def main():
    agent = Agent(
        tools=[file_read, file_write, python_repl, shell, journal],
        system_prompt="You are an Expert Software Developer specializing in web frameworks. Your task is to analyze project structures and identify mappings.",
        model="global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    )

    # Invocation
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("call_strands") as span:
        input = (
            "Do a short review of otel_strands_share.py. Focus on key functionality."
        )
        span.set_attribute(f"gen_ai.prompt.0.content", input)
        span.set_attribute(f"gen_ai.prompt.0.role", "user")
        response = agent(input)
        output_text = getattr(response, "output", str(response))
        span.set_attribute(f"gen_ai.completion.0.content", output_text)
        span.set_attribute(f"gen_ai.completion.0.role", "ai")


if __name__ == "__main__":
    main()
