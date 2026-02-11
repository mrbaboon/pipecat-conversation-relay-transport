# pipecat-conversation-relay

A Pipecat transport for Twilio ConversationRelay WebSocket integration.

## Install

```bash
pip install pipecat-conversation-relay
```

With TwiML generation support:

```bash
pip install pipecat-conversation-relay[twilio]
```

## Quick Usage

A minimal FastAPI WebSocket endpoint with a ConversationRelay transport and Pipecat pipeline:

```python
from fastapi import FastAPI, WebSocket
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.frames.frames import StartFrame
from pipecat.services.anthropic.llm import AnthropicLLMService, AnthropicLLMContext
from pipecat_conversation_relay import ConversationRelayTransport

app = FastAPI()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    # Create transport
    transport = ConversationRelayTransport(
        websocket=websocket,
        interruptible=True,
    )

    # Create LLM
    llm = AnthropicLLMService(
        api_key="sk-...",
        model="claude-sonnet-4-20250514",
    )
    context = AnthropicLLMContext(
        messages=[{"role": "system", "content": "You are a helpful assistant."}]
    )
    context_aggregator = llm.create_context_aggregator(context)

    # Build pipeline
    pipeline = Pipeline([
        transport.input(),
        context_aggregator.user(),
        llm,
        transport.output(),
        context_aggregator.assistant(),
    ])

    task = PipelineTask(pipeline, params=PipelineParams(
        allow_interruptions=True,
        enable_metrics=True,
    ))

    runner = PipelineRunner(handle_sigint=False, handle_sigterm=False)
    await task.queue_frame(StartFrame())
    await runner.run(task)
```

## Documentation

See the full [specification](specs/SPEC.md) for detailed API reference, event callbacks, TwiML generation, and more examples.
