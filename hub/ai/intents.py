"""Fixed intent table for the on-device model.

Rules in AssistantEngine run first. This table is only for utterances those
rules miss. The model must reply with one label. Code executes that label.
Start with 查事件. Other actions stay on their rules until they are added here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Intent:
    label: str
    title: str
    description: str
    examples: tuple[str, ...]


SEARCH_EVENTS = Intent(
    label="search_events",
    title="查事件",
    description=(
        "The user wants past camera events: whether anyone or anything came by, "
        "visitors, people, cars, or activity at the door or driveway."
    ),
    examples=(
        "Did anyone come by today?",
        "Does anyone come by today?",
        "Anybody stop by this afternoon?",
        "Who was here today?",
        "Any cars in the driveway?",
        "今天有人来过吗",
        "有没有人来过",
        "门口今天有谁",
    ),
)

NONE = Intent(
    label="none",
    title="其他",
    description="Not an event lookup. Includes lights, locks, arming, greetings, and chat.",
    examples=(
        "Turn on the lights",
        "把灯关了",
        "Arm the system",
        "Is the door locked?",
        "Hello",
    ),
)

INTENT_TABLE: tuple[Intent, ...] = (SEARCH_EVENTS, NONE)


def intent_prompt() -> str:
    """Build the classification prompt from the table so the table stays the source of truth."""
    lines = [
        "Classify the user's message for a home security hub.",
        "Reply with exactly one label and no other words.",
        "",
        "Labels:",
    ]
    for intent in INTENT_TABLE:
        lines.append(f"{intent.label}: {intent.description}")
    lines.append("")
    lines.append("Examples:")
    for intent in INTENT_TABLE:
        for example in intent.examples:
            lines.append(f"User: {example}")
            lines.append(f"Label: {intent.label}")
    return "\n".join(lines)


def parse_intent_label(raw: str) -> str:
    """Read one label from a model reply. Anything else is none."""
    labels = tuple(intent.label for intent in INTENT_TABLE)
    text = (raw or "").strip().lower()
    if not text:
        return NONE.label
    first = text.splitlines()[0].strip()
    first = re.sub(r"^(label|intent)\s*:\s*", "", first).strip()
    first = first.strip(" .\"'`*_")
    first = re.sub(r"[\s\-]+", "_", first)
    if first in labels:
        return first
    found = [label for label in labels if re.search(rf"\b{re.escape(label)}\b", first)]
    if len(found) == 1:
        return found[0]
    return NONE.label
