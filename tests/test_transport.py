from unittest.mock import AsyncMock, PropertyMock

import pytest
from pipecat.transports.base_transport import TransportParams
from starlette.websockets import WebSocketState

from pipecat_conversation_relay import (
    ConversationRelayCallbacks,
    ConversationRelayInputTransport,
    ConversationRelayOutputTransport,
    ConversationRelayTransport,
)


@pytest.fixture
def ws():
    mock = AsyncMock()
    type(mock).client_state = PropertyMock(return_value=WebSocketState.CONNECTED)
    return mock


class TestConversationRelayTransport:
    def test_creates_input_and_output(self, ws):
        transport = ConversationRelayTransport(websocket=ws)
        assert isinstance(transport.input(), ConversationRelayInputTransport)
        assert isinstance(transport.output(), ConversationRelayOutputTransport)

    def test_input_output_are_stable_references(self, ws):
        transport = ConversationRelayTransport(websocket=ws)
        assert transport.input() is transport.input()
        assert transport.output() is transport.output()

    def test_audio_video_always_disabled(self, ws):
        params = TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            video_in_enabled=True,
            video_out_enabled=True,
        )
        transport = ConversationRelayTransport(websocket=ws, params=params)
        # The transport should force these off
        assert transport._params.audio_in_enabled is False
        assert transport._params.audio_out_enabled is False
        assert transport._params.video_in_enabled is False
        assert transport._params.video_out_enabled is False

    def test_default_params_created_when_none(self, ws):
        transport = ConversationRelayTransport(websocket=ws)
        assert transport._params is not None
        assert transport._params.audio_in_enabled is False

    def test_callbacks_passed_to_input(self, ws):
        cb = ConversationRelayCallbacks(on_setup=AsyncMock())
        transport = ConversationRelayTransport(websocket=ws, callbacks=cb)
        assert transport.input()._callbacks is cb

    def test_interruptible_passed_to_output(self, ws):
        transport = ConversationRelayTransport(websocket=ws, interruptible=False)
        assert transport.output()._interruptible is False

    def test_names_passed_through(self, ws):
        transport = ConversationRelayTransport(
            websocket=ws, input_name="my-input", output_name="my-output"
        )
        assert transport.input().name == "my-input"
        assert transport.output().name == "my-output"
