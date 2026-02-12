from unittest.mock import AsyncMock

import pytest
from conftest import make_ws_with_messages
from pipecat.frames.frames import (
    CancelFrame,
    ErrorFrame,
    TranscriptionFrame,
)
from pipecat.transports.base_transport import TransportParams

from pipecat_conversation_relay.input_transport import ConversationRelayInputTransport
from pipecat_conversation_relay.types import ConversationRelayCallbacks, ErrorEventData


def make_input_transport(ws, callbacks=None):
    params = TransportParams(
        audio_in_enabled=False,
        audio_out_enabled=False,
        video_in_enabled=False,
        video_out_enabled=False,
    )
    return ConversationRelayInputTransport(
        websocket=ws,
        params=params,
        callbacks=callbacks,
    )


class TestSetupMessage:
    @pytest.mark.asyncio
    async def test_setup_extracts_session_and_call(self):
        setup_msg = {
            "type": "setup",
            "sessionId": "VX123",
            "callSid": "CA456",
            "accountSid": "AC789",
            "from": "+18005550100",
            "to": "+18005550101",
            "direction": "inbound",
            "callStatus": "RINGING",
            "callType": "PSTN",
            "callerName": "Test",
            "forwardedFrom": "+18005550102",
            "parentCallSid": "",
            "customParameters": {"agent_id": "42"},
        }

        on_setup = AsyncMock()
        callbacks = ConversationRelayCallbacks(on_setup=on_setup)
        ws = make_ws_with_messages([setup_msg])
        transport = make_input_transport(ws, callbacks=callbacks)

        # Capture pushed frames
        pushed_frames = []
        transport.push_frame = AsyncMock(side_effect=lambda f, *a, **kw: pushed_frames.append(f))

        await transport._receive_messages()

        assert transport.session_id == "VX123"
        assert transport.call_sid == "CA456"
        on_setup.assert_awaited_once()

        event = on_setup.call_args[0][0]
        assert event.session_id == "VX123"
        assert event.call_sid == "CA456"
        assert event.account_sid == "AC789"
        assert event.from_number == "+18005550100"
        assert event.to_number == "+18005550101"
        assert event.direction == "inbound"
        assert event.custom_parameters == {"agent_id": "42"}


class TestPromptMessage:
    @pytest.mark.asyncio
    async def test_final_prompt_emits_transcription_frame(self):
        prompt_msg = {
            "type": "prompt",
            "voicePrompt": "Hello, how are you?",
            "lang": "en-US",
            "last": True,
        }

        ws = make_ws_with_messages([prompt_msg])
        transport = make_input_transport(ws)

        pushed_frames = []
        transport.push_frame = AsyncMock(side_effect=lambda f, *a, **kw: pushed_frames.append(f))

        await transport._receive_messages()

        # Should have TranscriptionFrame + CancelFrame (from disconnect)
        transcription_frames = [f for f in pushed_frames if isinstance(f, TranscriptionFrame)]
        assert len(transcription_frames) == 1
        assert transcription_frames[0].text == "Hello, how are you?"
        assert transcription_frames[0].user_id == ""
        assert transcription_frames[0].language == "en-US"

    @pytest.mark.asyncio
    async def test_interim_prompt_is_ignored(self):
        prompt_msg = {
            "type": "prompt",
            "voicePrompt": "Hello",
            "lang": "en-US",
            "last": False,
        }

        ws = make_ws_with_messages([prompt_msg])
        transport = make_input_transport(ws)

        pushed_frames = []
        transport.push_frame = AsyncMock(side_effect=lambda f, *a, **kw: pushed_frames.append(f))

        await transport._receive_messages()

        transcription_frames = [f for f in pushed_frames if isinstance(f, TranscriptionFrame)]
        assert len(transcription_frames) == 0

    @pytest.mark.asyncio
    async def test_empty_prompt_is_ignored(self):
        prompt_msg = {
            "type": "prompt",
            "voicePrompt": "   ",
            "lang": "en-US",
            "last": True,
        }

        ws = make_ws_with_messages([prompt_msg])
        transport = make_input_transport(ws)

        pushed_frames = []
        transport.push_frame = AsyncMock(side_effect=lambda f, *a, **kw: pushed_frames.append(f))

        await transport._receive_messages()

        transcription_frames = [f for f in pushed_frames if isinstance(f, TranscriptionFrame)]
        assert len(transcription_frames) == 0

    @pytest.mark.asyncio
    async def test_null_voice_prompt_is_ignored(self):
        prompt_msg = {
            "type": "prompt",
            "voicePrompt": None,
            "lang": "en-US",
            "last": True,
        }

        ws = make_ws_with_messages([prompt_msg])
        transport = make_input_transport(ws)

        pushed_frames = []
        transport.push_frame = AsyncMock(side_effect=lambda f, *a, **kw: pushed_frames.append(f))

        await transport._receive_messages()

        transcription_frames = [f for f in pushed_frames if isinstance(f, TranscriptionFrame)]
        assert len(transcription_frames) == 0


class TestInterruptMessage:
    @pytest.mark.asyncio
    async def test_interrupt_invokes_callback(self):
        interrupt_msg = {
            "type": "interrupt",
            "utteranceUntilInterrupt": "Life is a complex set of",
            "durationUntilInterruptMs": 460,
        }

        on_interrupt = AsyncMock()
        callbacks = ConversationRelayCallbacks(on_interrupt=on_interrupt)
        ws = make_ws_with_messages([interrupt_msg])
        transport = make_input_transport(ws, callbacks=callbacks)
        transport.push_frame = AsyncMock()

        await transport._receive_messages()

        on_interrupt.assert_awaited_once()
        event = on_interrupt.call_args[0][0]
        assert event.utterance_until_interrupt == "Life is a complex set of"
        assert event.duration_until_interrupt_ms == 460


class TestDTMFMessage:
    @pytest.mark.asyncio
    async def test_dtmf_invokes_callback(self):
        dtmf_msg = {"type": "dtmf", "digit": "1"}

        on_dtmf = AsyncMock()
        callbacks = ConversationRelayCallbacks(on_dtmf=on_dtmf)
        ws = make_ws_with_messages([dtmf_msg])
        transport = make_input_transport(ws, callbacks=callbacks)
        transport.push_frame = AsyncMock()

        await transport._receive_messages()

        on_dtmf.assert_awaited_once()
        event = on_dtmf.call_args[0][0]
        assert event.digit == "1"


class TestErrorMessage:
    @pytest.mark.asyncio
    async def test_error_pushes_error_frame(self):
        error_msg = {"type": "error", "description": "Something went wrong"}

        on_error = AsyncMock()
        callbacks = ConversationRelayCallbacks(on_error=on_error)
        ws = make_ws_with_messages([error_msg])
        transport = make_input_transport(ws, callbacks=callbacks)

        pushed_frames = []
        transport.push_frame = AsyncMock(side_effect=lambda f, *a, **kw: pushed_frames.append(f))

        await transport._receive_messages()

        error_frames = [f for f in pushed_frames if isinstance(f, ErrorFrame)]
        assert len(error_frames) == 1
        assert error_frames[0].error == "Something went wrong"

        on_error.assert_awaited_once()
        event = on_error.call_args[0][0]
        assert isinstance(event, ErrorEventData)
        assert event.description == "Something went wrong"


class TestDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_pushes_cancel_frame(self):
        ws = make_ws_with_messages([])  # No messages, immediate disconnect
        transport = make_input_transport(ws)

        pushed_frames = []
        transport.push_frame = AsyncMock(side_effect=lambda f, *a, **kw: pushed_frames.append(f))

        await transport._receive_messages()

        cancel_frames = [f for f in pushed_frames if isinstance(f, CancelFrame)]
        assert len(cancel_frames) == 1
