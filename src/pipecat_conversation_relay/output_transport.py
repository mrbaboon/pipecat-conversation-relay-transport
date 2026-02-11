from typing import Any

from fastapi import WebSocket
from loguru import logger
from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    TextFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.transports.base_transport import TransportParams
from starlette.websockets import WebSocketState


class ConversationRelayOutputTransport(BaseOutputTransport):
    def __init__(
        self,
        websocket: WebSocket,
        params: TransportParams,
        interruptible: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(params, **kwargs)
        self._websocket = websocket
        self._interruptible = interruptible

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        # Intercept text frames before they reach the base class's audio/video
        # routing. Send to Twilio and push downstream for the context aggregator.
        if isinstance(frame, LLMFullResponseEndFrame):
            await self._send_last_token()
            await self.push_frame(frame, direction)
        elif isinstance(frame, TextFrame):
            await self._send_text_token(frame.text)
            await self.push_frame(frame, direction)
        else:
            await super().process_frame(frame, direction)

    async def _send_text_token(self, token: str) -> None:
        message = {
            "type": "text",
            "token": token,
            "last": False,
            "interruptible": self._interruptible,
        }
        await self._send_json(message)

    async def _send_last_token(self) -> None:
        message = {
            "type": "text",
            "token": "",
            "last": True,
            "interruptible": False,
        }
        await self._send_json(message)

    async def send_end_session(self, handoff_data: str | None = None) -> None:
        message: dict[str, Any] = {"type": "end"}
        if handoff_data is not None:
            message["handoffData"] = handoff_data
        await self._send_json(message)

    async def send_play(
        self,
        source: str,
        loop: int = 1,
        interruptible: bool | None = None,
        preemptible: bool = False,
    ) -> None:
        message: dict[str, Any] = {
            "type": "play",
            "source": source,
            "loop": loop,
            "preemptible": preemptible,
        }
        if interruptible is not None:
            message["interruptible"] = interruptible
        else:
            message["interruptible"] = self._interruptible
        await self._send_json(message)

    async def send_digits(self, digits: str) -> None:
        message = {"type": "sendDigits", "digits": digits}
        await self._send_json(message)

    async def send_language(
        self,
        tts_language: str | None = None,
        transcription_language: str | None = None,
    ) -> None:
        if tts_language is None and transcription_language is None:
            raise ValueError(
                "At least one of tts_language or transcription_language must be provided"
            )

        message: dict[str, str] = {"type": "language"}
        if tts_language is not None:
            message["ttsLanguage"] = tts_language
        if transcription_language is not None:
            message["transcriptionLanguage"] = transcription_language
        await self._send_json(message)

    async def _send_json(self, message: dict[str, Any]) -> None:
        try:
            if self._websocket.client_state == WebSocketState.CONNECTED:
                await self._websocket.send_json(message)
        except Exception as e:
            logger.error(f"{self} error sending {message.get('type', 'unknown')} message: {e}")
