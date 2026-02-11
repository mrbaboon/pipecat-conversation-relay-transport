from unittest.mock import AsyncMock, PropertyMock

import pytest
from conftest import make_ws_with_messages
from pipecat.frames.frames import (
    LLMFullResponseEndFrame,
    TextFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from starlette.websockets import WebSocketState

from pipecat_conversation_relay import (
    ConversationRelayCallbacks,
    ConversationRelayTransport,
    SetupEventData,
)


class TestFullFlow:
    """Integration tests simulating realistic message flows."""

    @pytest.mark.asyncio
    async def test_setup_then_prompt_flow(self):
        """Simulate: Twilio sends setup, then a user prompt."""
        setup_msg = {
            "type": "setup",
            "sessionId": "VX123",
            "callSid": "CA456",
            "customParameters": {"agent_id": "1"},
        }
        prompt_msg = {
            "type": "prompt",
            "voicePrompt": "What is the weather today?",
            "lang": "en-US",
            "last": True,
        }

        setup_received = []

        async def on_setup(event: SetupEventData):
            setup_received.append(event)

        ws = make_ws_with_messages([setup_msg, prompt_msg])
        callbacks = ConversationRelayCallbacks(on_setup=on_setup)
        transport = ConversationRelayTransport(websocket=ws, callbacks=callbacks)
        input_transport = transport.input()

        pushed_frames = []
        input_transport.push_frame = AsyncMock(
            side_effect=lambda f, *a, **kw: pushed_frames.append(f)
        )

        await input_transport._receive_messages()

        # Verify setup was processed
        assert len(setup_received) == 1
        assert setup_received[0].session_id == "VX123"
        assert setup_received[0].custom_parameters == {"agent_id": "1"}

        # Verify transcription frame was emitted
        transcription_frames = [f for f in pushed_frames if isinstance(f, TranscriptionFrame)]
        assert len(transcription_frames) == 1
        assert transcription_frames[0].text == "What is the weather today?"

    @pytest.mark.asyncio
    async def test_output_streaming_tokens(self):
        """Simulate: Pipeline sends multiple TextFrames then LLMFullResponseEndFrame."""
        ws = AsyncMock()
        type(ws).client_state = PropertyMock(return_value=WebSocketState.CONNECTED)
        ws.send_json = AsyncMock()

        transport = ConversationRelayTransport(websocket=ws)
        output = transport.output()
        output.push_frame = AsyncMock()

        # Simulate LLM streaming tokens
        tokens = ["The ", "weather ", "is ", "sunny ", "today."]
        for token in tokens:
            await output.process_frame(TextFrame(text=token), FrameDirection.DOWNSTREAM)

        # Signal end of response
        await output.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)

        # Verify all tokens were sent
        calls = ws.send_json.call_args_list
        assert len(calls) == len(tokens) + 1  # tokens + last

        # Check token messages
        for i, token in enumerate(tokens):
            msg = calls[i][0][0]
            assert msg["type"] == "text"
            assert msg["token"] == token
            assert msg["last"] is False
            assert msg["interruptible"] is True

        # Check last message
        last_msg = calls[-1][0][0]
        assert last_msg["type"] == "text"
        assert last_msg["token"] == ""
        assert last_msg["last"] is True
        assert last_msg["interruptible"] is False

    @pytest.mark.asyncio
    async def test_send_helpers(self):
        """Test output transport helper methods."""
        ws = AsyncMock()
        type(ws).client_state = PropertyMock(return_value=WebSocketState.CONNECTED)
        ws.send_json = AsyncMock()

        transport = ConversationRelayTransport(websocket=ws)
        output = transport.output()

        # End session
        await output.send_end_session(handoff_data='{"reason": "transfer"}')
        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "end"
        assert msg["handoffData"] == '{"reason": "transfer"}'

        ws.send_json.reset_mock()

        # Send digits
        await output.send_digits("1234")
        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "sendDigits"
        assert msg["digits"] == "1234"

        ws.send_json.reset_mock()

        # Change language
        await output.send_language(tts_language="es-ES")
        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "language"
        assert msg["ttsLanguage"] == "es-ES"
