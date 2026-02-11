from unittest.mock import AsyncMock

import pytest
from conftest import make_ws_with_messages
from pipecat.transports.base_transport import TransportParams

from pipecat_conversation_relay.input_transport import ConversationRelayInputTransport
from pipecat_conversation_relay.types import (
    ConversationRelayCallbacks,
    ErrorEventData,
)


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


class TestCallbackInvocation:
    @pytest.mark.asyncio
    async def test_all_callbacks_invoked_in_sequence(self):
        """Test that setup, dtmf, and interrupt callbacks fire in order."""
        messages = [
            {
                "type": "setup",
                "sessionId": "VX1",
                "callSid": "CA1",
                "customParameters": {},
            },
            {"type": "dtmf", "digit": "5"},
            {
                "type": "interrupt",
                "utteranceUntilInterrupt": "Hello",
                "durationUntilInterruptMs": 200,
            },
        ]

        call_order = []

        async def on_setup(event):
            call_order.append(("setup", event.session_id))

        async def on_dtmf(event):
            call_order.append(("dtmf", event.digit))

        async def on_interrupt(event):
            call_order.append(("interrupt", event.utterance_until_interrupt))

        callbacks = ConversationRelayCallbacks(
            on_setup=on_setup,
            on_interrupt=on_interrupt,
            on_dtmf=on_dtmf,
        )

        ws = make_ws_with_messages(messages)
        transport = make_input_transport(ws, callbacks=callbacks)
        transport.push_frame = AsyncMock()

        await transport._receive_messages()

        assert call_order == [
            ("setup", "VX1"),
            ("dtmf", "5"),
            ("interrupt", "Hello"),
        ]


class TestNoCallbacks:
    @pytest.mark.asyncio
    async def test_no_callback_no_error(self):
        """Messages should be processed without error even with no callbacks registered."""
        messages = [
            {
                "type": "setup",
                "sessionId": "VX1",
                "callSid": "CA1",
                "customParameters": {},
            },
            {"type": "dtmf", "digit": "1"},
            {"type": "interrupt"},
        ]

        ws = make_ws_with_messages(messages)
        transport = make_input_transport(ws)
        transport.push_frame = AsyncMock()

        # Should not raise
        await transport._receive_messages()

        assert transport.session_id == "VX1"


class TestErrorCallback:
    @pytest.mark.asyncio
    async def test_error_callback_invoked(self):
        messages = [{"type": "error", "description": "Bad things happened"}]

        on_error = AsyncMock()
        callbacks = ConversationRelayCallbacks(on_error=on_error)
        ws = make_ws_with_messages(messages)
        transport = make_input_transport(ws, callbacks=callbacks)
        transport.push_frame = AsyncMock()

        await transport._receive_messages()

        on_error.assert_awaited_once()
        event = on_error.call_args[0][0]
        assert isinstance(event, ErrorEventData)
        assert event.description == "Bad things happened"
