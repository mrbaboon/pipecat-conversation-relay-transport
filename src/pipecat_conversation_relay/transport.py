from fastapi import WebSocket
from pipecat.transports.base_transport import BaseTransport, TransportParams

from .input_transport import ConversationRelayInputTransport
from .output_transport import ConversationRelayOutputTransport
from .types import ConversationRelayCallbacks


class ConversationRelayTransport(BaseTransport):
    def __init__(
        self,
        websocket: WebSocket,
        params: TransportParams | None = None,
        callbacks: ConversationRelayCallbacks | None = None,
        interruptible: bool = True,
        input_name: str | None = None,
        output_name: str | None = None,
    ):
        super().__init__(input_name=input_name, output_name=output_name)

        self._params = params or TransportParams(
            audio_in_enabled=False,
            audio_out_enabled=False,
            video_in_enabled=False,
            video_out_enabled=False,
        )
        # Ensure audio/video are always disabled for this text-only transport
        self._params.audio_in_enabled = False
        self._params.audio_out_enabled = False
        self._params.video_in_enabled = False
        self._params.video_out_enabled = False

        self._input = ConversationRelayInputTransport(
            websocket=websocket,
            params=self._params,
            callbacks=callbacks,
            name=self._input_name,
        )

        self._output = ConversationRelayOutputTransport(
            websocket=websocket,
            params=self._params,
            interruptible=interruptible,
            name=self._output_name,
        )

    def input(self) -> ConversationRelayInputTransport:
        return self._input

    def output(self) -> ConversationRelayOutputTransport:
        return self._output
