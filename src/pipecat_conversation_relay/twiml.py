class ConversationRelayTwiMLGenerator:
    @staticmethod
    def generate(
        websocket_url: str,
        # TTS configuration
        tts_provider: str = "google",
        voice: str = "Google.en-US-Neural2-A",
        tts_language: str | None = None,
        # STT configuration
        transcription_provider: str = "deepgram",
        speech_model: str | None = None,
        transcription_language: str = "en-US",
        hints: str | None = None,
        # Behavior
        welcome_greeting: str | None = None,
        welcome_greeting_interruptible: bool | None = None,
        interruptible: bool = True,
        interrupt_sensitivity: str | None = None,
        preemptible: bool | None = None,
        dtmf_detection: bool = False,
        report_input_during_agent_speech: bool | None = None,
        # ElevenLabs-specific
        elevenlabs_text_normalization: str | None = None,
        # Custom parameters
        custom_parameters: dict[str, str] | None = None,
    ) -> str:
        try:
            from twilio.twiml.voice_response import Connect, VoiceResponse
        except ImportError as e:
            raise ImportError(
                "The 'twilio' package is required for TwiML generation. "
                "Install it with: pip install pipecat-conversation-relay[twilio]"
            ) from e

        response = VoiceResponse()
        connect = Connect()

        attrs = {
            "url": websocket_url,
            "tts_provider": tts_provider,
            "voice": voice,
            "transcription_provider": transcription_provider,
            "transcription_language": transcription_language,
            "interruptible": str(interruptible).lower(),
            "dtmf_detection": str(dtmf_detection).lower(),
        }

        if tts_language is not None:
            attrs["tts_language"] = tts_language
        if speech_model is not None:
            attrs["speech_model"] = speech_model
        if hints is not None:
            attrs["hints"] = hints
        if welcome_greeting is not None:
            attrs["welcome_greeting"] = welcome_greeting
        if welcome_greeting_interruptible is not None:
            attrs["welcome_greeting_interruptible"] = str(welcome_greeting_interruptible).lower()
        if interrupt_sensitivity is not None:
            attrs["interrupt_sensitivity"] = interrupt_sensitivity
        if preemptible is not None:
            attrs["preemptible"] = str(preemptible).lower()
        if report_input_during_agent_speech is not None:
            attrs["report_input_during_agent_speech"] = str(
                report_input_during_agent_speech
            ).lower()
        if elevenlabs_text_normalization is not None:
            attrs["elevenlabs_text_normalization"] = elevenlabs_text_normalization

        conversation_relay = connect.conversation_relay(**attrs)

        if custom_parameters:
            for name, value in custom_parameters.items():
                conversation_relay.parameter(name=name, value=value)

        response.append(connect)
        return str(response)
