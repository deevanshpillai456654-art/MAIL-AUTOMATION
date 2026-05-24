"""
Email Intelligence Engine
=====================

Conversation threading:
- Conversation DAG
- Semantic threading
- Contact graph
- Reply prediction
- Action extraction
"""

import logging
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("intelligence")


class EmailRelation(Enum):
    REPLY = "reply"
    FORWARD = "forward"
    REFERENCE = "reference"
    IN_REPLY_TO = "in_reply_to"


@dataclass
class MessageNode:
    """Email message node"""
    message_id: str
    subject: str
    sender: str
    recipients: List[str]
    in_reply_to: Optional[str] = None
    references: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@dataclass
class Conversation:
    """Conversation thread"""
    thread_id: str
    root_message_id: str
    participants: Set[str] = field(default_factory=set)
    messages: List[str] = field(default_factory=list)
    actions: List[Dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)


@dataclass
class ContactProfile:
    """Contact intelligence"""
    email: str
    display_name: str
    thread_count: int = 0
    email_count: int = 0
    last_contact: float = 0
    keywords: Set[str] = field(default_factory=set)
    inferred_intents: List[str] = field(default_factory=list)


@dataclass
class ReplyIntent:
    """Reply intent prediction"""
    intent_id: str
    message_id: str
    predicted_intent: str
    confidence: float = 0.0
    suggested_recipients: List[str] = field(default_factory=list)
    suggested_reply: Optional[str] = None


class ConversationGraph:
    """Conversation threading graph"""

    def __init__(self):
        self._nodes: Dict[str, MessageNode] = {}
        self._threads: Dict[str, Conversation] = {}
        self._edges: Dict[str, List[str]] = defaultdict(list)
        self._lock = threading.RLock()

        logger.info("Conversation graph initialized")

    def add_message(self,
                   message_id: str,
                   subject: str,
                   sender: str,
                   recipients: List[str],
                   in_reply_to: Optional[str] = None,
                   references: Optional[List[str]] = None,
                   timestamp: Optional[float] = None):
        """Add message to graph"""
        with self._lock:
            node = MessageNode(
                message_id=message_id,
                subject=subject,
                sender=sender,
                recipients=recipients,
                in_reply_to=in_reply_to,
                references=references or [],
                timestamp=timestamp or time.time()
            )

            self._nodes[message_id] = node

            thread_id = self._find_thread(in_reply_to, references)

            if thread_id:
                if thread_id not in self._threads:
                    self._threads[thread_id] = Conversation(
                        thread_id=thread_id,
                        root_message_id=message_id
                    )

                thread = self._threads[thread_id]
                thread.messages.append(message_id)
                thread.participants.add(sender)
                for r in recipients:
                    thread.participants.add(r)
                thread.last_updated = time.time()
            else:
                thread_id = message_id
                self._threads[thread_id] = Conversation(
                    thread_id=thread_id,
                    root_message_id=message_id
                )

            if in_reply_to:
                self._edges[in_reply_to].append(message_id)

            for ref in (references or []):
                self._edges[ref].append(message_id)

    def _find_thread(self,
                    in_reply_to: Optional[str],
                    references: Optional[List[str]]) -> Optional[str]:
        """Find thread ID"""
        if in_reply_to and in_reply_to in self._nodes:
            return self._nodes[in_reply_to].subject

        for ref in (references or []):
            if ref in self._nodes:
                return self._nodes[ref].subject

        return None

    def get_thread(self, message_id: str) -> Optional[Conversation]:
        """Get thread by message ID"""
        with self._lock:
            for thread in self._threads.values():
                if message_id in thread.messages:
                    return thread
            return None

    def get_thread_messages(self, thread_id: str) -> List[MessageNode]:
        """Get all messages in thread"""
        with self._lock:
            thread = self._threads.get(thread_id)
            if not thread:
                return []

            return [self._nodes[mid] for mid in thread.messages if mid in self._nodes]

    def get_reply_chain(self, message_id: str) -> List[MessageNode]:
        """Get reply chain for message"""
        with self._lock:
            chain = []
            current = message_id

            while current:
                if current in self._nodes:
                    chain.append(self._nodes[current])
                    current = self._nodes[current].in_reply_to
                else:
                    break

            return list(reversed(chain))


class ContactIntelligence:
    """Contact intelligence tracking"""

    def __init__(self):
        self._contacts: Dict[str, ContactProfile] = {}
        self._lock = threading.RLock()

        logger.info("Contact intelligence initialized")

    def process_email(self,
                      sender: str,
                      subject: str,
                      body: str,
                      timestamp: float):
        """Process email to update contact profile"""
        with self._lock:
            if sender not in self._contacts:
                self._contacts[sender] = ContactProfile(
                    email=sender,
                    display_name=sender.split('@')[0]
                )

            contact = self._contacts[sender]
            contact.email_count += 1
            contact.last_contact = timestamp

            keywords = self._extract_keywords(subject + " " + body)
            contact.keywords.update(keywords)

    def _extract_keywords(self, text: str) -> Set[str]:
        """Extract keywords"""
        words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
        stop_words = {'this', 'that', 'have', 'been', 'will', 'from', 'with', 'your'}
        return {w for w in words if w not in stop_words}

    def get_contact(self, email: str) -> Optional[ContactProfile]:
        """Get contact profile"""
        return self._contacts.get(email)

    def get_frequent_contacts(self, limit: int = 10) -> List[ContactProfile]:
        """Get most frequent contacts"""
        with self._lock:
            sorted_contacts = sorted(
                self._contacts.values(),
                key=lambda c: c.email_count,
                reverse=True
            )
            return sorted_contacts[:limit]


class IntentExtractor:
    """Extract action intents from emails"""

    def __init__(self):
        self._intent_patterns = {
            "request": [r"please", r"can you", r"could you", r"would you"],
            "schedule": [r"meeting", r"schedule", r"calendar", r"when"],
            "approval": [r"approve", r"approval", r"review", r"sign"],
            "document": [r"document", r"contract", r"agreement", r"report"],
            "payment": [r"payment", r"invoice", r"bill", r"budget"],
            "feedback": [r"feedback", r"comments", r"thoughts", r"suggestions"]
        }

        logger.info("Intent extractor initialized")

    def extract_intent(self, subject: str, body: str) -> List[str]:
        """Extract intents from email"""
        text = (subject + " " + body).lower()
        intents = []

        for intent, patterns in self._intent_patterns.items():
            for pattern in patterns:
                if pattern in text:
                    intents.append(intent)
                    break

        return intents


class EmailIntelligence:
    """Main email intelligence engine"""

    def __init__(self):
        self._conversation_graph = ConversationGraph()
        self._contact_intelligence = ContactIntelligence()
        self._intent_extractor = IntentExtractor()
        self._lock = threading.RLock()

        logger.info("Email intelligence engine initialized")

    def process_email(self,
                    message_id: str,
                    subject: str,
                    sender: str,
                    recipients: List[str],
                    body: str,
                    in_reply_to: Optional[str] = None,
                    references: Optional[List[str]] = None):
        """Process email for intelligence"""
        timestamp = time.time()

        self._conversation_graph.add_message(
            message_id, subject, sender, recipients,
            in_reply_to, references, timestamp
        )

        self._contact_intelligence.process_email(
            sender, subject, body, timestamp
        )

        intents = self._intent_extractor.extract_intent(subject, body)

        thread = self._conversation_graph.get_thread(message_id)
        if thread:
            thread.actions.extend(intents)

    def get_conversation(self, message_id: str) -> Optional[Conversation]:
        """Get conversation thread"""
        return self._conversation_graph.get_thread(message_id)

    def get_reply_chain(self, message_id: str) -> List[MessageNode]:
        """Get reply chain"""
        return self._conversation_graph.get_reply_chain(message_id)

    def get_contact(self, email: str) -> Optional[ContactProfile]:
        """Get contact profile"""
        return self._contact_intelligence.get_contact(email)


_global_intelligence: Optional[EmailIntelligence] = None


def get_email_intelligence() -> EmailIntelligence:
    """Get global email intelligence"""
    global _global_intelligence
    if _global_intelligence is None:
        _global_intelligence = EmailIntelligence()
    return _global_intelligence


__all__ = [
    "EmailRelation",
    "MessageNode",
    "Conversation",
    "ContactProfile",
    "ReplyIntent",
    "ConversationGraph",
    "ContactIntelligence",
    "IntentExtractor",
    "EmailIntelligence",
    "get_email_intelligence"
]
