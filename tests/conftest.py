import json
from unittest.mock import AsyncMock, PropertyMock

import pytest
from starlette.websockets import WebSocketState


@pytest.fixture
def mock_websocket():
    """Create a mock FastAPI WebSocket with standard behavior."""
    ws = AsyncMock()
    # Default to connected state
    type(ws).client_state = PropertyMock(return_value=WebSocketState.CONNECTED)
    ws.send_json = AsyncMock()
    ws.send_text = AsyncMock()
    ws.close = AsyncMock()
    return ws


def make_ws_with_messages(messages: list[dict]):
    """Create a mock WebSocket that yields the given messages via iter_text(), then disconnects."""
    ws = AsyncMock()
    type(ws).client_state = PropertyMock(return_value=WebSocketState.CONNECTED)
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()

    text_messages = [json.dumps(m) for m in messages]

    async def iter_text():
        for msg in text_messages:
            yield msg

    ws.iter_text = iter_text
    return ws
