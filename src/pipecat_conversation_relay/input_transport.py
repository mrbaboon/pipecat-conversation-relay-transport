import asyncio
import json
import time
from typing import Any

from fastapi import WebSocket
from loguru import logger
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    StartFrame,
    TranscriptionFrame,
)
from pipecat.transports.base_input import BaseInputTransport
from pipecat.transports.base_transport import TransportParams
from starlette.websockets import WebSocketState

from .types import (
    ConversationRelayCallbacks,
    DTMFEventData,
    ErrorEventData,
    InterruptEventData,
    SetupEventData,
)


class ConversationRelayInputTransport(BaseInputTransport):
    def __init__(
        self,
        websocket: WebSocket,
        params: TransportParams,
        callbacks: ConversationRelayCallbacks | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(params, **kwargs)
        self._websocket = websocket
        self._callbacks = callbacks or ConversationRelayCallbacks()
        self._receive_task: asyncio.Task[None] | None = None
        self._session_id: str | None = None
        self._call_sid: str | None = None
        self._initialized = False

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def call_sid(self) -> str | None:
        return self._call_sid

    async def start(self, frame: StartFrame) -> None:
        await super().start(frame)

        if self._initialized:
            return

        self._initialized = True

        if not self._receive_task:
            self._receive_task = self.create_task(self._receive_messages())

    async def stop(self, frame: EndFrame) -> None:
        await super().stop(frame)
        await self._stop_tasks()
        await self._close_websocket()

    async def cancel(self, frame: CancelFrame) -> None:
        await super().cancel(frame)
        await self._stop_tasks()
        await self._close_websocket()

    async def _stop_tasks(self) -> None:
        if self._receive_task:
            await self.cancel_task(self._receive_task)
            self._receive_task = None

    async def _close_websocket(self) -> None:
        try:
            if self._websocket.client_state == WebSocketState.CONNECTED:
                await self._websocket.close()
        except Exception as e:
            logger.error(f"{self} error closing websocket: {e}")

    async def _receive_messages(self) -> None:
        try:
            async for text in self._websocket.iter_text():
                try:
                    message = json.loads(text)
                except json.JSONDecodeError:
                    logger.warning(f"{self} received non-JSON message: {text[:100]}")
                    continue

                msg_type = message.get("type")
                if msg_type == "setup":
                    await self._handle_setup(message)
                elif msg_type == "prompt":
                    await self._handle_prompt(message)
                elif msg_type == "interrupt":
                    await self._handle_interrupt(message)
                elif msg_type == "dtmf":
                    await self._handle_dtmf(message)
                elif msg_type == "error":
                    await self._handle_error(message)
                else:
                    logger.warning(f"{self} unknown message type: {msg_type}")

        except Exception as e:
            logger.info(f"{self} WebSocket disconnected: {e}")

        # WebSocket disconnected unexpectedly — push CancelFrame to stop the pipeline
        await self.push_frame(CancelFrame())

    async def _handle_setup(self, message: dict[str, Any]) -> None:
        self._session_id = message.get("sessionId")
        self._call_sid = message.get("callSid")

        logger.info(
            f"{self} ConversationRelay setup: session={self._session_id}, call={self._call_sid}"
        )

        if self._callbacks.on_setup:
            event = SetupEventData(
                session_id=message.get("sessionId", ""),
                call_sid=message.get("callSid", ""),
                account_sid=message.get("accountSid"),
                from_number=message.get("from"),
                to_number=message.get("to"),
                direction=message.get("direction"),
                call_status=message.get("callStatus"),
                call_type=message.get("callType"),
                caller_name=message.get("callerName"),
                forwarded_from=message.get("forwardedFrom"),
                parent_call_sid=message.get("parentCallSid"),
                custom_parameters=message.get("customParameters", {}),
            )
            await self._callbacks.on_setup(event)

    async def _handle_prompt(self, message: dict[str, Any]) -> None:
        last = message.get("last", False)
        voice_prompt = message.get("voicePrompt", "")
        lang = message.get("lang")

        if not last:
            return

        if not voice_prompt.strip():
            return

        frame = TranscriptionFrame(
            text=voice_prompt,
            user_id="",
            timestamp=str(time.time()),
            language=lang,
        )
        await self.push_frame(frame)

    async def _handle_interrupt(self, message: dict[str, Any]) -> None:
        if self._callbacks.on_interrupt:
            event = InterruptEventData(
                utterance_until_interrupt=message.get("utteranceUntilInterrupt"),
                duration_until_interrupt_ms=message.get("durationUntilInterruptMs"),
            )
            await self._callbacks.on_interrupt(event)

    async def _handle_dtmf(self, message: dict[str, Any]) -> None:
        if self._callbacks.on_dtmf:
            event = DTMFEventData(digit=message.get("digit", ""))
            await self._callbacks.on_dtmf(event)

    async def _handle_error(self, message: dict[str, Any]) -> None:
        description = message.get("description", "Unknown error")
        logger.error(f"{self} ConversationRelay error: {description}")

        if self._callbacks.on_error:
            event = ErrorEventData(description=description)
            await self._callbacks.on_error(event)

        await self.push_frame(ErrorFrame(error=description))
