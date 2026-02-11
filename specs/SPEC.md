# pipecat-conversation-relay: Specification

A standalone Pipecat transport for Twilio ConversationRelay WebSocket integration.

## Overview

This module provides a Pipecat-native transport that bridges Twilio's [ConversationRelay](https://www.twilio.com/docs/voice/conversationrelay/) WebSocket protocol with Pipecat's frame-based pipeline architecture. It enables **text-only** Pipecat pipelines where Twilio handles all STT and TTS, while Pipecat handles LLM orchestration, tool calling, and conversation management.

### Key Design Principle

ConversationRelay offloads STT/TTS to Twilio's managed infrastructure. The Pipecat pipeline never processes audio — it receives transcribed text from Twilio and sends text tokens back for Twilio to synthesize. This reduces latency, simplifies the pipeline, and eliminates the need for STT/TTS service configuration in Pipecat.

```
Phone Call → Twilio (STT/TTS via ConversationRelay)
                    ↕ WebSocket (text only)
             Pipecat Pipeline
    [InputTransport] → [UserAgg] → [LLM] → [OutputTransport] → [AssistantAgg]
```

## Package

- **Name**: `pipecat-conversation-relay`
- **Install**: `pip install pipecat-conversation-relay`
- **Import**: `from pipecat_conversation_relay import ConversationRelayTransport`
- **Python**: `>=3.10,<3.14` (constrained by pipecat-ai)

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `pipecat-ai` | `>=0.0.95` | Core Pipecat framework (frames, transports, pipeline) |
| `fastapi` | `>=0.100` | WebSocket type (used for the WS connection) |

> **Note**: `fastapi` is needed for the `WebSocket` type. A future version could abstract this behind a protocol to support other WebSocket implementations (e.g., raw `websockets` library).

### Optional Dependencies

| Extra | Packages | Purpose |
|-------|----------|---------|
| `twilio` | `twilio>=9.0.0` | TwiML helper for generating `<Connect><ConversationRelay>` XML |

## Public API

### Module Exports

```python
from pipecat_conversation_relay import (
    # Core transport
    ConversationRelayTransport,
    ConversationRelayInputTransport,
    ConversationRelayOutputTransport,

    # Event/callback types
    ConversationRelayCallbacks,
    SetupEventData,
    PromptEventData,
    InterruptEventData,
    DTMFEventData,

    # TwiML helper (requires `twilio` extra)
    ConversationRelayTwiMLGenerator,
)
```

---

## Core Classes

### `ConversationRelayTransport`

The main transport class. Implements Pipecat's `BaseTransport` and provides paired `input()` / `output()` processors for use in a Pipeline.

```python
class ConversationRelayTransport(BaseTransport):
    def __init__(
        self,
        websocket: WebSocket,
        params: TransportParams | None = None,
        callbacks: ConversationRelayCallbacks | None = None,
        interruptible: bool = True,
        input_name: str | None = None,
        output_name: str | None = None,
    ): ...

    def input(self) -> ConversationRelayInputTransport: ...
    def output(self) -> ConversationRelayOutputTransport: ...
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `websocket` | `WebSocket` | required | The WebSocket connection from Twilio ConversationRelay |
| `params` | `TransportParams \| None` | `None` | Pipecat transport params. Audio/video are always disabled internally. |
| `callbacks` | `ConversationRelayCallbacks \| None` | `None` | Optional callbacks for ConversationRelay events (setup, interrupt, dtmf) |
| `interruptible` | `bool` | `True` | Whether agent speech can be interrupted by the caller. Sent on every `text` message to Twilio. |
| `input_name` | `str \| None` | `None` | Optional name for the input processor (for pipeline debugging) |
| `output_name` | `str \| None` | `None` | Optional name for the output processor |

#### Usage

```python
transport = ConversationRelayTransport(websocket=ws, interruptible=True)

pipeline = Pipeline([
    transport.input(),
    context_aggregator.user(),
    llm_service,
    transport.output(),
    context_aggregator.assistant(),
])
```

---

### `ConversationRelayInputTransport`

Extends `BaseInputTransport`. Listens for WebSocket messages from Twilio and emits Pipecat frames downstream.

**Not instantiated directly** — obtained via `ConversationRelayTransport.input()`.

#### Behavior

1. On `StartFrame`: Spawns background WebSocket listener task.
2. On `EndFrame` / `CancelFrame`: Stops listener, closes WebSocket.
3. WebSocket disconnect: Pushes `CancelFrame` to stop the pipeline.

#### Inbound Message Handling

| Twilio Message Type | Pipecat Frame Emitted | Notes |
|--------------------|-----------------------|-------|
| `setup` | *(none — event callback only)* | Extracts `sessionId`, `callSid`, caller info. Invokes `on_setup` callback. |
| `prompt` (`last=true`) | `TranscriptionFrame` | User's final transcribed speech pushed downstream to LLM. |
| `prompt` (`last=false`) | *(none)* | Interim/partial transcription. Ignored by default. |
| `interrupt` | *(none — event callback only)* | Invokes `on_interrupt` callback. Future: emit `UserStartedSpeakingFrame`. |
| `dtmf` | *(none — event callback only)* | Invokes `on_dtmf` callback with the pressed digit. |
| `error` | `ErrorFrame` | Pushes error downstream. |

#### Properties

| Property | Type | Description |
|----------|------|-------------|
| `session_id` | `str \| None` | Twilio session ID from the `setup` message. `None` until setup received. |
| `call_sid` | `str \| None` | Twilio Call SID from the `setup` message. |

---

### `ConversationRelayOutputTransport`

Extends `BaseOutputTransport`. Intercepts downstream frames and sends them to Twilio via WebSocket.

**Not instantiated directly** — obtained via `ConversationRelayTransport.output()`.

#### Outbound Frame Handling

| Pipecat Frame | WebSocket Message Sent | Notes |
|---------------|----------------------|-------|
| `TextFrame` | `{"type": "text", "token": "...", "last": false, "interruptible": ...}` | Streams LLM response tokens to Twilio for TTS |
| `LLMFullResponseEndFrame` | `{"type": "text", "token": "", "last": true, "interruptible": false}` | Signals end of current response turn |

#### Methods

```python
async def send_end_session(self, handoff_data: str | None = None) -> None:
    """
    Send end session message to ConversationRelay.
    Tells Twilio to end the call and optionally passes handoff data
    back to the Twilio action callback URL.
    """

async def send_play(
    self,
    source: str,
    loop: int = 1,
    interruptible: bool | None = None,
    preemptible: bool = False,
) -> None:
    """
    Send a play media message to ConversationRelay.
    Twilio will play the audio file at `source` URL to the caller.
    """

async def send_digits(self, digits: str) -> None:
    """
    Send DTMF digits to the caller.
    Characters: 0-9, w (500ms pause), #, *.
    """

async def send_language(
    self,
    tts_language: str | None = None,
    transcription_language: str | None = None,
) -> None:
    """
    Change the TTS and/or STT language mid-session.
    At least one of tts_language or transcription_language must be provided.
    """
```

---

### `ConversationRelayCallbacks`

Dataclass for registering callbacks on ConversationRelay events that don't map directly to Pipecat frames.

```python
@dataclass
class ConversationRelayCallbacks:
    on_setup: Callable[[SetupEventData], Awaitable[None]] | None = None
    on_interrupt: Callable[[InterruptEventData], Awaitable[None]] | None = None
    on_dtmf: Callable[[DTMFEventData], Awaitable[None]] | None = None
    on_error: Callable[[str], Awaitable[None]] | None = None
```

#### Event Data Types

```python
@dataclass
class SetupEventData:
    session_id: str
    call_sid: str
    account_sid: str | None
    from_number: str | None      # "from" field in the message
    to_number: str | None        # "to" field in the message
    direction: str | None        # "inbound" or "outbound"
    call_status: str | None
    call_type: str | None        # "PSTN", "SIP", etc.
    caller_name: str | None
    forwarded_from: str | None
    parent_call_sid: str | None
    custom_parameters: dict[str, str]  # From <Parameter> elements in TwiML

@dataclass
class InterruptEventData:
    utterance_until_interrupt: str | None   # Text spoken before interruption
    duration_until_interrupt_ms: int | None # Milliseconds spoken before interruption

@dataclass
class DTMFEventData:
    digit: str  # The DTMF digit pressed ("0"-"9", "#", "*")
```

---

### `ConversationRelayTwiMLGenerator`

Helper class for generating the TwiML needed to connect an incoming Twilio call to a ConversationRelay WebSocket endpoint. Requires the `twilio` optional extra.

```python
class ConversationRelayTwiMLGenerator:
    @staticmethod
    def generate(
        websocket_url: str,
        # TTS configuration
        tts_provider: str = "google",
        voice: str = "Google.en-US-Neural2-A",
        tts_language: str | None = None,
        # STT configuration
        transcription_provider: str = "deepgram",
        speech_model: str | None = None,
        transcription_language: str = "en-US",
        hints: str | None = None,
        # Behavior
        welcome_greeting: str | None = None,
        welcome_greeting_interruptible: bool | None = None,
        interruptible: bool = True,
        interrupt_sensitivity: str | None = None,
        preemptible: bool | None = None,
        dtmf_detection: bool = False,
        report_input_during_agent_speech: bool | None = None,
        # ElevenLabs-specific
        elevenlabs_text_normalization: str | None = None,
        # Custom parameters passed to WebSocket setup message
        custom_parameters: dict[str, str] | None = None,
    ) -> str:
        """
        Generate TwiML XML string for ConversationRelay.

        Returns:
            Complete TwiML XML string ready to return as HTTP response.
        """
```

#### Generated TwiML Structure

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <ConversationRelay url="wss://example.com/ws"
                           ttsProvider="elevenlabs"
                           voice="UgBBYS2sOqTuMpoF3BR0"
                           transcriptionProvider="deepgram"
                           speechModel="nova-3-general"
                           transcriptionLanguage="en-US"
                           interruptible="true"
                           welcomeGreeting="Hello, how can I help?">
            <Parameter name="agent_id" value="42"/>
        </ConversationRelay>
    </Connect>
</Response>
```

---

## Protocol Reference

### Messages FROM Twilio (Inbound)

#### `setup`

Sent once immediately after WebSocket connection is established.

```json
{
  "type": "setup",
  "sessionId": "VX00000000000000000000000000000000",
  "accountSid": "ACXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
  "callSid": "CA00000000000000000000000000000000",
  "from": "+18005550100",
  "to": "+18005550101",
  "forwardedFrom": "+18005550102",
  "parentCallSid": "",
  "callType": "PSTN",
  "callerName": "",
  "direction": "inbound",
  "callStatus": "RINGING",
  "customParameters": {
    "agent_id": "42"
  }
}
```

#### `prompt`

Sent when the caller speaks. `voicePrompt` contains transcribed text. `last=true` indicates final transcription for this utterance.

```json
{
  "type": "prompt",
  "voicePrompt": "Hi! Can you tell me about life?",
  "lang": "en-US",
  "last": true
}
```

#### `interrupt`

Sent when the caller interrupts agent TTS playback by speaking.

```json
{
  "type": "interrupt",
  "utteranceUntilInterrupt": "Life is a complex set of",
  "durationUntilInterruptMs": 460
}
```

#### `dtmf`

Sent when DTMF detection is enabled and the caller presses a key.

```json
{
  "type": "dtmf",
  "digit": "1"
}
```

#### `error`

Sent when an error occurs during the ConversationRelay session.

```json
{
  "type": "error",
  "description": "Invalid message received: { \"foo\" : \"bar\" }"
}
```

### Messages TO Twilio (Outbound)

#### `text`

Stream text tokens to Twilio for TTS synthesis. Tokens should be sent as soon as available (don't wait for complete sentences). Use `last=true` on the final token of a response turn.

```json
{
  "type": "text",
  "token": "Hello world!",
  "last": false,
  "interruptible": true,
  "preemptible": false
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `string` | yes | Must be `"text"` |
| `token` | `string` | yes | Text for TTS. Preserve natural spacing between tokens. |
| `last` | `bool` | no | `true` for the final token of the current response. Default `false`. |
| `interruptible` | `bool` | no | Whether caller can interrupt. Overrides TwiML-level setting. |
| `preemptible` | `bool` | no | Whether subsequent text/play messages stop this playback. |
| `lang` | `string` | no | Language for this specific token. |

#### `play`

Play an audio file to the caller.

```json
{
  "type": "play",
  "source": "https://example.com/audio.mp3",
  "loop": 1,
  "preemptible": false,
  "interruptible": true
}
```

#### `sendDigits`

Send DTMF tones to the caller.

```json
{
  "type": "sendDigits",
  "digits": "9www4085551212"
}
```

#### `language`

Change STT/TTS language mid-session.

```json
{
  "type": "language",
  "ttsLanguage": "sv-SE",
  "transcriptionLanguage": "en-US"
}
```

#### `end`

End the ConversationRelay session and return call control to Twilio.

```json
{
  "type": "end",
  "handoffData": "{\"reasonCode\":\"live-agent-handoff\"}"
}
```

---

## Pipecat Frame Mapping

### Inbound (Twilio → Pipeline)

| Twilio Message | Condition | Pipecat Frame | Frame Fields |
|---------------|-----------|---------------|--------------|
| `prompt` | `last=true` and non-empty `voicePrompt` | `TranscriptionFrame` | `text=voicePrompt`, `user_id=""`, `timestamp=now()`, `language=lang` |
| `error` | always | `ErrorFrame` | `error=description` |
| WS disconnect | unexpected | `CancelFrame` | *(terminates pipeline)* |

### Outbound (Pipeline → Twilio)

| Pipecat Frame | Twilio Message | Behavior |
|---------------|---------------|----------|
| `TextFrame` | `text` token | `token=frame.text`, `last=false`, `interruptible=<config>` |
| `LLMFullResponseEndFrame` | `text` end marker | `token=""`, `last=true`, `interruptible=false` |

---

## Usage Examples

### Minimal Pipeline

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

### With Event Callbacks

```python
from pipecat_conversation_relay import (
    ConversationRelayTransport,
    ConversationRelayCallbacks,
    SetupEventData,
    DTMFEventData,
    InterruptEventData,
)

async def on_setup(event: SetupEventData):
    print(f"Call started: {event.call_sid} from {event.from_number}")
    # Store session info, log to database, etc.

async def on_interrupt(event: InterruptEventData):
    print(f"User interrupted after {event.duration_until_interrupt_ms}ms")

async def on_dtmf(event: DTMFEventData):
    print(f"DTMF digit pressed: {event.digit}")
    if event.digit == "0":
        # Transfer to operator
        await transport.output().send_end_session(
            handoff_data='{"reason": "operator_transfer"}'
        )

callbacks = ConversationRelayCallbacks(
    on_setup=on_setup,
    on_interrupt=on_interrupt,
    on_dtmf=on_dtmf,
)

transport = ConversationRelayTransport(
    websocket=websocket,
    callbacks=callbacks,
    interruptible=True,
)
```

### With TwiML Generation

```python
from fastapi import FastAPI, Request
from fastapi.responses import Response
from pipecat_conversation_relay import ConversationRelayTwiMLGenerator

app = FastAPI()

@app.get("/twiml/{agent_id}")
async def get_twiml(request: Request, agent_id: int):
    host = request.headers.get("host", "localhost:8000")
    protocol = "wss" if "localhost" not in host else "ws"
    ws_url = f"{protocol}://{host}/ws"

    twiml = ConversationRelayTwiMLGenerator.generate(
        websocket_url=ws_url,
        tts_provider="elevenlabs",
        voice="UgBBYS2sOqTuMpoF3BR0",
        transcription_provider="deepgram",
        speech_model="nova-3-general",
        transcription_language="en-US",
        welcome_greeting="Hello! How can I help you today?",
        interruptible=True,
        dtmf_detection=True,
        custom_parameters={"agent_id": str(agent_id)},
    )

    return Response(content=twiml, media_type="application/xml")
```

### With LLM Tool Calling

```python
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema

# Define tool
weather_tool = FunctionSchema(
    name="get_weather",
    description="Get the current weather",
    properties={
        "location": {"type": "string", "description": "City name"},
    },
    required=["location"],
)

# Register handler
async def weather_handler(params):
    location = params.arguments["location"]
    result = {"temperature": 72, "condition": "sunny"}
    await params.result_callback(result)

llm.register_function("get_weather", weather_handler)

# Context with tools
context = AnthropicLLMContext(
    messages=[{"role": "system", "content": "You help with weather."}],
    tools=ToolsSchema(standard_tools=[weather_tool]),
)

# Pipeline is identical — tool calling is handled by the LLM service,
# not by the transport. The transport just streams the final text response.
```

---

## Project Structure

```
pipecat-conversation-relay/
├── pyproject.toml
├── README.md
├── LICENSE
├── src/
│   └── pipecat_conversation_relay/
│       ├── __init__.py              # Public exports
│       ├── transport.py             # ConversationRelayTransport (main class)
│       ├── input_transport.py       # ConversationRelayInputTransport
│       ├── output_transport.py      # ConversationRelayOutputTransport
│       ├── types.py                 # Event data types, callbacks dataclass
│       └── twiml.py                 # TwiML generator (optional twilio dep)
└── tests/
    ├── conftest.py                  # Shared fixtures (mock WebSocket, etc.)
    ├── test_transport.py            # Transport init, input/output pairing
    ├── test_input_transport.py      # WebSocket message → frame conversion
    ├── test_output_transport.py     # Frame → WebSocket message conversion
    ├── test_callbacks.py            # Event callback invocation
    ├── test_twiml.py                # TwiML generation
    └── test_integration.py          # Full pipeline integration tests
```

---

## Scope

### In Scope

- WebSocket message parsing (Twilio → Pipecat frames)
- WebSocket message sending (Pipecat frames → Twilio)
- Proper Pipecat transport lifecycle (`start`, `stop`, `cancel`, `cleanup`)
- Event callbacks for ConversationRelay-specific events
- Outbound helpers: `send_end_session`, `send_play`, `send_digits`, `send_language`
- TwiML generation helper for `<Connect><ConversationRelay>`
- WebSocket disconnect handling and pipeline shutdown
- `interruptible` flag propagation on every outbound text message

### Out of Scope

- LLM service configuration (use pipecat-ai services directly)
- Tool/function calling execution (use pipecat-ai's built-in mechanism)
- Audio processing (the entire point is that Twilio handles STT/TTS)
- Twilio webhook signature validation (application responsibility)
- FastAPI server scaffolding (application responsibility)
- Session persistence / call logging (application responsibility)
- Multi-tenant routing (application responsibility)

---

## Design Decisions

### Why `TranscriptionFrame` (not `TextFrame`) for inbound prompts?

Pipecat's context aggregators expect `TranscriptionFrame` for user input. Using `TextFrame` would not trigger the user aggregator, breaking the conversation context flow. The `TranscriptionFrame` includes metadata fields (`user_id`, `timestamp`, `language`) that map naturally to ConversationRelay's prompt message.

### Why no audio frames?

ConversationRelay manages STT and TTS on Twilio's infrastructure. The WebSocket protocol is text-only. Including audio processing would defeat the purpose of using ConversationRelay and add unnecessary latency.

### Why callbacks instead of frames for setup/interrupt/dtmf?

These events don't have natural Pipecat frame equivalents and don't flow through the LLM pipeline. Callbacks give applications direct control over handling these events (e.g., logging call metadata, implementing DTMF menus, tracking interruption analytics) without polluting the frame pipeline.

### Why `TransportParams` with audio/video disabled?

Pipecat's `BaseInputTransport` and `BaseOutputTransport` constructors require `TransportParams`. By explicitly disabling audio/video, we prevent any accidental audio processing initialization and clearly signal that this is a text-only transport.

### Why FastAPI `WebSocket` type?

The current implementation uses FastAPI's `WebSocket` for `iter_text()`, `send_json()`, and `close()`. This couples the transport to FastAPI. A future version could introduce a `WebSocketProtocol` ABC to support other WebSocket libraries, but FastAPI is the dominant choice for Pipecat servers today.
