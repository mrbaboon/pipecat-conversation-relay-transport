from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field


@dataclass
class SetupEventData:
    session_id: str
    call_sid: str
    account_sid: str | None = None
    from_number: str | None = None
    to_number: str | None = None
    direction: str | None = None
    call_status: str | None = None
    call_type: str | None = None
    caller_name: str | None = None
    forwarded_from: str | None = None
    parent_call_sid: str | None = None
    custom_parameters: dict[str, str] = field(default_factory=dict)


@dataclass
class InterruptEventData:
    utterance_until_interrupt: str | None = None
    duration_until_interrupt_ms: int | None = None


@dataclass
class DTMFEventData:
    digit: str


@dataclass
class ErrorEventData:
    description: str


@dataclass
class ConversationRelayCallbacks:
    on_setup: Callable[[SetupEventData], Awaitable[None]] | None = None
    on_interrupt: Callable[[InterruptEventData], Awaitable[None]] | None = None
    on_dtmf: Callable[[DTMFEventData], Awaitable[None]] | None = None
    on_error: Callable[[ErrorEventData], Awaitable[None]] | None = None
