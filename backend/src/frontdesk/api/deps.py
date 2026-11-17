"""What the HTTP application needs from the outside. No model provider is among them."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from frontdesk.channels.webchat import PostgresNotifications
from frontdesk.db.session import SessionFactory
from frontdesk.queue.port import TriggerQueue


@dataclass(frozen=True)
class ApiDeps:
    sessions: SessionFactory
    queue: TriggerQueue
    notifications: PostgresNotifications
    webchat_secret: str
    clock: Callable[[], datetime]
