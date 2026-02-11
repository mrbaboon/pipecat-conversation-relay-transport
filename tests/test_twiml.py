import importlib.util

import pytest

from pipecat_conversation_relay.twiml import ConversationRelayTwiMLGenerator

HAS_TWILIO = importlib.util.find_spec("twilio") is not None


@pytest.mark.skipif(not HAS_TWILIO, reason="twilio not installed")
class TestTwiMLGenerator:
    def test_basic_generation(self):
        twiml = ConversationRelayTwiMLGenerator.generate(
            websocket_url="wss://example.com/ws",
            tts_provider="google",
            voice="Google.en-US-Neural2-A",
            transcription_provider="deepgram",
            transcription_language="en-US",
        )

        assert "<Response>" in twiml
        assert "<Connect>" in twiml
        assert "wss://example.com/ws" in twiml

    def test_custom_parameters(self):
        twiml = ConversationRelayTwiMLGenerator.generate(
            websocket_url="wss://example.com/ws",
            custom_parameters={"agent_id": "42", "session_type": "support"},
        )

        assert "agent_id" in twiml
        assert "42" in twiml
        assert "session_type" in twiml

    def test_welcome_greeting(self):
        twiml = ConversationRelayTwiMLGenerator.generate(
            websocket_url="wss://example.com/ws",
            welcome_greeting="Hello, how can I help?",
        )

        assert "Hello, how can I help?" in twiml

    def test_elevenlabs_config(self):
        twiml = ConversationRelayTwiMLGenerator.generate(
            websocket_url="wss://example.com/ws",
            tts_provider="elevenlabs",
            voice="UgBBYS2sOqTuMpoF3BR0",
            speech_model="nova-3-general",
        )

        assert "elevenlabs" in twiml
        assert "UgBBYS2sOqTuMpoF3BR0" in twiml

    def test_dtmf_detection(self):
        twiml = ConversationRelayTwiMLGenerator.generate(
            websocket_url="wss://example.com/ws",
            dtmf_detection=True,
        )

        assert "true" in twiml.lower()


class TestTwiMLImportError:
    """These tests run regardless of twilio installation."""

    @pytest.mark.skipif(HAS_TWILIO, reason="twilio is installed")
    def test_generate_raises_import_error_without_twilio(self):
        """Verify the error message is helpful when twilio is missing."""
        with pytest.raises(ImportError, match="twilio"):
            ConversationRelayTwiMLGenerator.generate(websocket_url="wss://example.com/ws")
