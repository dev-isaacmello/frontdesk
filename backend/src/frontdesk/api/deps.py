"""What the HTTP application needs from the outside.

The model provider among them is used by one route only: checking the owner's rules when
they are saved. Nothing on the path of a customer message calls a model here.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from frontdesk.agent.graph import AgentDeps
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
    agent: AgentDeps
