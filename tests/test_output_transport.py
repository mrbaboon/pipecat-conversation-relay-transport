from unittest.mock import AsyncMock, PropertyMock

import pytest
from pipecat.frames.frames import (
    LLMFullResponseEndFrame,
    TextFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.transports.base_transport import TransportParams
from starlette.websockets import WebSocketState

from pipecat_conversation_relay.output_transport import ConversationRelayOutputTransport


def make_output_transport(ws, interruptible=True):
    params = TransportParams(
        audio_in_enabled=False,
        audio_out_enabled=False,
        video_in_enabled=False,
        video_out_enabled=False,
    )
    return ConversationRelayOutputTransport(
        websocket=ws,
        params=params,
        interruptible=interruptible,
    )


@pytest.fixture
def ws():
    mock = AsyncMock()
    type(mock).client_state = PropertyMock(return_value=WebSocketState.CONNECTED)
    mock.send_json = AsyncMock()
    return mock


class TestTextFrameHandling:
    @pytest.mark.asyncio
    async def test_text_frame_sends_token(self, ws):
        transport = make_output_transport(ws)
        transport.push_frame = AsyncMock()

        frame = TextFrame(text="Hello")
        await transport.process_frame(frame, FrameDirection.DOWNSTREAM)

        ws.send_json.assert_awaited_once_with(
            {
                "type": "text",
                "token": "Hello",
                "last": False,
                "interruptible": True,
            }
        )

    @pytest.mark.asyncio
    async def test_text_frame_pushes_downstream(self, ws):
        transport = make_output_transport(ws)
        pushed = []
        transport.push_frame = AsyncMock(side_effect=lambda f, *a, **kw: pushed.append(f))

        frame = TextFrame(text="Hello")
        await transport.process_frame(frame, FrameDirection.DOWNSTREAM)

        assert any(isinstance(f, TextFrame) and f.text == "Hello" for f in pushed)

    @pytest.mark.asyncio
    async def test_interruptible_false(self, ws):
        transport = make_output_transport(ws, interruptible=False)
        transport.push_frame = AsyncMock()

        frame = TextFrame(text="Hi")
        await transport.process_frame(frame, FrameDirection.DOWNSTREAM)

        ws.send_json.assert_awaited_once()
        sent = ws.send_json.call_args[0][0]
        assert sent["interruptible"] is False


class TestLLMFullResponseEndFrame:
    @pytest.mark.asyncio
    async def test_end_frame_sends_last_token(self, ws):
        transport = make_output_transport(ws)
        transport.push_frame = AsyncMock()

        frame = LLMFullResponseEndFrame()
        await transport.process_frame(frame, FrameDirection.DOWNSTREAM)

        ws.send_json.assert_awaited_once_with(
            {
                "type": "text",
                "token": "",
                "last": True,
                "interruptible": False,
            }
        )

    @pytest.mark.asyncio
    async def test_end_frame_pushes_downstream(self, ws):
        transport = make_output_transport(ws)
        pushed = []
        transport.push_frame = AsyncMock(side_effect=lambda f, *a, **kw: pushed.append(f))

        frame = LLMFullResponseEndFrame()
        await transport.process_frame(frame, FrameDirection.DOWNSTREAM)

        assert any(isinstance(f, LLMFullResponseEndFrame) for f in pushed)


class TestSendEndSession:
    @pytest.mark.asyncio
    async def test_send_end_session_no_handoff(self, ws):
        transport = make_output_transport(ws)
        await transport.send_end_session()
        ws.send_json.assert_awaited_once_with({"type": "end"})

    @pytest.mark.asyncio
    async def test_send_end_session_with_handoff(self, ws):
        transport = make_output_transport(ws)
        await transport.send_end_session(handoff_data='{"reason": "transfer"}')
        ws.send_json.assert_awaited_once_with(
            {
                "type": "end",
                "handoffData": '{"reason": "transfer"}',
            }
        )


class TestSendPlay:
    @pytest.mark.asyncio
    async def test_send_play_default(self, ws):
        transport = make_output_transport(ws)
        await transport.send_play(source="https://example.com/audio.mp3")
        ws.send_json.assert_awaited_once_with(
            {
                "type": "play",
                "source": "https://example.com/audio.mp3",
                "loop": 1,
                "preemptible": False,
                "interruptible": True,
            }
        )

    @pytest.mark.asyncio
    async def test_send_play_with_options(self, ws):
        transport = make_output_transport(ws)
        await transport.send_play(
            source="https://example.com/audio.mp3",
            loop=3,
            interruptible=False,
            preemptible=True,
        )
        ws.send_json.assert_awaited_once_with(
            {
                "type": "play",
                "source": "https://example.com/audio.mp3",
                "loop": 3,
                "preemptible": True,
                "interruptible": False,
            }
        )


class TestSendDigits:
    @pytest.mark.asyncio
    async def test_send_digits(self, ws):
        transport = make_output_transport(ws)
        await transport.send_digits("9www4085551212")
        ws.send_json.assert_awaited_once_with(
            {
                "type": "sendDigits",
                "digits": "9www4085551212",
            }
        )


class TestSendLanguage:
    @pytest.mark.asyncio
    async def test_send_language_both(self, ws):
        transport = make_output_transport(ws)
        await transport.send_language(tts_language="sv-SE", transcription_language="en-US")
        ws.send_json.assert_awaited_once_with(
            {
                "type": "language",
                "ttsLanguage": "sv-SE",
                "transcriptionLanguage": "en-US",
            }
        )

    @pytest.mark.asyncio
    async def test_send_language_tts_only(self, ws):
        transport = make_output_transport(ws)
        await transport.send_language(tts_language="sv-SE")
        ws.send_json.assert_awaited_once_with(
            {
                "type": "language",
                "ttsLanguage": "sv-SE",
            }
        )

    @pytest.mark.asyncio
    async def test_send_language_neither_raises(self, ws):
        transport = make_output_transport(ws)
        with pytest.raises(ValueError):
            await transport.send_language()


class TestDisconnectedWebSocket:
    @pytest.mark.asyncio
    async def test_no_send_when_disconnected(self, ws):
        type(ws).client_state = PropertyMock(return_value=WebSocketState.DISCONNECTED)
        transport = make_output_transport(ws)
        await transport._send_json({"type": "text", "token": "hi"})
        ws.send_json.assert_not_awaited()
