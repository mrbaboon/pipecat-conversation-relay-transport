"""End-to-end tests running a full pipecat Pipeline with ConversationRelayTransport.

Unlike test_integration.py which manually calls internal methods on the input/output
transports, these tests wire up a real Pipeline + PipelineRunner and verify that
CR messages injected into the WebSocket produce the expected outbound payloads.
"""

import asyncio
import json
from unittest.mock import AsyncMock, PropertyMock

import pytest
from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TextFrame,
    TranscriptionFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from starlette.websockets import WebSocketState

from pipecat_conversation_relay import (
    ConversationRelayCallbacks,
    ConversationRelayTransport,
    SetupEventData,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class EchoProcessor(FrameProcessor):
    """Echoes TranscriptionFrames back as TextFrames.

    Produces the same frame sequence a real LLM would:
    LLMFullResponseStartFrame -> TextFrame(s) -> LLMFullResponseEndFrame
    """

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            await self.push_frame(LLMFullResponseStartFrame())
            await self.push_frame(TextFrame(text=f"echo: {frame.text}"))
            await self.push_frame(LLMFullResponseEndFrame())
        else:
            await self.push_frame(frame, direction)


def make_pipeline_ws(messages: list[dict], settle_secs: float = 0.5) -> AsyncMock:
    """Mock WebSocket that yields *messages* inbound and captures outbound via send_json.

    After all messages are yielded the mock sleeps for *settle_secs* before the
    iterator ends — giving the pipeline time to flush frames before the
    disconnect-induced CancelFrame stops everything.
    """
    ws = AsyncMock()
    type(ws).client_state = PropertyMock(return_value=WebSocketState.CONNECTED)
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()

    async def iter_text():
        for msg in messages:
            yield json.dumps(msg)
        await asyncio.sleep(settle_secs)

    ws.iter_text = iter_text
    return ws


def sent_messages(ws: AsyncMock) -> list[dict]:
    """Extract the list of JSON payloads sent to the WebSocket."""
    return [call[0][0] for call in ws.send_json.call_args_list]


def text_messages(ws: AsyncMock) -> list[dict]:
    """Extract only type=text payloads."""
    return [m for m in sent_messages(ws) if m.get("type") == "text"]


async def run_pipeline(transport: ConversationRelayTransport, *processors: FrameProcessor):
    """Build a pipeline around *transport* with the given middle processors and run it."""
    pipeline = Pipeline([transport.input(), *processors, transport.output()])
    task = PipelineTask(pipeline, params=PipelineParams(enable_metrics=False))
    runner = PipelineRunner(handle_sigint=False)
    await asyncio.wait_for(runner.run(task), timeout=10)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPipelineEndToEnd:
    @pytest.mark.asyncio
    async def test_echo_single_prompt(self):
        """Setup + single prompt -> one echo response over the WebSocket."""
        ws = make_pipeline_ws(
            [
                {"type": "setup", "sessionId": "VX123", "callSid": "CA456"},
                {"type": "prompt", "voicePrompt": "Hello, world!", "lang": "en-US", "last": True},
            ]
        )

        transport = ConversationRelayTransport(websocket=ws)
        await run_pipeline(transport, EchoProcessor())

        msgs = text_messages(ws)
        assert len(msgs) == 2

        assert msgs[0]["token"] == "echo: Hello, world!"
        assert msgs[0]["last"] is False
        assert msgs[0]["interruptible"] is True

        assert msgs[1]["token"] == ""
        assert msgs[1]["last"] is True
        assert msgs[1]["interruptible"] is False

    @pytest.mark.asyncio
    async def test_echo_multiple_prompts(self):
        """Each final prompt produces its own echo response."""
        ws = make_pipeline_ws(
            [
                {"type": "setup", "sessionId": "VX123", "callSid": "CA456"},
                {"type": "prompt", "voicePrompt": "First", "lang": "en-US", "last": True},
                {"type": "prompt", "voicePrompt": "Second", "lang": "en-US", "last": True},
            ]
        )

        transport = ConversationRelayTransport(websocket=ws)
        await run_pipeline(transport, EchoProcessor())

        msgs = text_messages(ws)
        tokens = [m["token"] for m in msgs if not m["last"]]
        lasts = [m for m in msgs if m["last"]]

        assert tokens == ["echo: First", "echo: Second"]
        assert len(lasts) == 2

    @pytest.mark.asyncio
    async def test_interim_prompts_ignored(self):
        """Interim prompts (last=false) are dropped; only the final prompt gets a response."""
        ws = make_pipeline_ws(
            [
                {"type": "setup", "sessionId": "VX123", "callSid": "CA456"},
                {"type": "prompt", "voicePrompt": "Hel", "lang": "en-US", "last": False},
                {"type": "prompt", "voicePrompt": "Hello", "lang": "en-US", "last": False},
                {"type": "prompt", "voicePrompt": "Hello there", "lang": "en-US", "last": True},
            ]
        )

        transport = ConversationRelayTransport(websocket=ws)
        await run_pipeline(transport, EchoProcessor())

        tokens = [m["token"] for m in text_messages(ws) if not m["last"]]
        assert tokens == ["echo: Hello there"]

    @pytest.mark.asyncio
    async def test_setup_callback_fires(self):
        """on_setup callback receives the correct event data during a pipeline run."""
        setup_events: list[SetupEventData] = []

        async def on_setup(event: SetupEventData):
            setup_events.append(event)

        ws = make_pipeline_ws(
            [
                {
                    "type": "setup",
                    "sessionId": "VX-SESS",
                    "callSid": "CA-CALL",
                    "from": "+15551234567",
                    "customParameters": {"key": "val"},
                },
                {"type": "prompt", "voicePrompt": "Hi", "lang": "en-US", "last": True},
            ]
        )

        callbacks = ConversationRelayCallbacks(on_setup=on_setup)
        transport = ConversationRelayTransport(websocket=ws, callbacks=callbacks)
        await run_pipeline(transport, EchoProcessor())

        assert len(setup_events) == 1
        assert setup_events[0].session_id == "VX-SESS"
        assert setup_events[0].call_sid == "CA-CALL"
        assert setup_events[0].from_number == "+15551234567"
        assert setup_events[0].custom_parameters == {"key": "val"}

    @pytest.mark.asyncio
    async def test_interruptible_false(self):
        """Transport-level interruptible=False is forwarded on outbound text tokens."""
        ws = make_pipeline_ws(
            [
                {"type": "setup", "sessionId": "VX123", "callSid": "CA456"},
                {"type": "prompt", "voicePrompt": "Test", "lang": "en-US", "last": True},
            ]
        )

        transport = ConversationRelayTransport(websocket=ws, interruptible=False)
        await run_pipeline(transport, EchoProcessor())

        token_msg = next(m for m in text_messages(ws) if m["token"] != "")
        assert token_msg["interruptible"] is False
