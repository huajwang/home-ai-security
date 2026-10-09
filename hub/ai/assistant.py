"""Central Assistant Engine coordinating tools, guardrails, and RKLLM Qwen runner."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from hub.ai.rkllm_bridge import get_runner
from hub.ai.tools import (
    control_light_tool,
    get_device_status,
    get_security_briefing,
    search_events_tool,
    set_armed_tool,
)

logger = logging.getLogger("home_ai.assistant")

SYSTEM_VOICE_PROMPT = (
    "You are the Home AI security voice assistant. You are concise, polite, "
    "and give direct factual responses suitable for text-to-speech. "
    "Never use markdown formatting, bullet points, or asterisks. "
    "Do not exceed two sentences unless explaining security events."
)


class AssistantEngine:
    def __init__(self, services: dict[str, Any], actor: str = "voice_satellite") -> None:
        self.services = services
        self.actor = actor

    def process_query(
        self, prompt: str, history: Optional[list[dict[str, str]]] = None
    ) -> dict[str, Any]:
        """Process user text prompt, apply guardrails, invoke tools, and synthesize speech answer."""
        text = prompt.strip()
        lower = text.lower()

        # 1. Security Guardrail: Deadbolt Unlock is STRICTLY FORBIDDEN via Voice
        if re.search(r"\b(unlock|open)\b.*\b(door|deadbolt|lock)\b", lower) or re.search(
            r"\b(unlock|open)\b", lower
        ):
            if "status" not in lower and "check" not in lower and "is" not in lower:
                return {
                    "response": (
                        "Unlocking the deadbolt is not permitted via voice assistant for security reasons. "
                        "Please use the mobile app with biometric confirmation."
                    ),
                    "tool_used": "guardrail_unlock_blocked",
                    "tool_data": {"action": "unlock_rejected"},
                }

        # 2. Light Control Intent
        if re.search(r"\b(turn|switch)\s+(on|off)\b.*\b(light|bulb|porch|door)\b", lower) or re.search(
            r"\b(light|bulb|porch|door)\b.*\b(on|off)\b", lower
        ):
            turn_on = "on" in lower.split() or "turn on" in lower or "switch on" in lower
            lights = self.services.get("lights")
            result = control_light_tool(lights, turn_on=turn_on)
            return {
                "response": result["summary"],
                "tool_used": "control_light",
                "tool_data": result,
            }

        # 3. Device Status / Lock / Armed Inspection Intent (queries take precedence over commands)
        is_status_query = (
            any(
                phrase in lower
                for phrase in (
                    "status",
                    "is the door locked",
                    "is the front door locked",
                    "is it locked",
                    "check the lock",
                    "check system",
                    "system status",
                    "how is the system",
                )
            )
            or re.search(r"\b(is|are|check|what|tell me if)\b.*\b(armed|locked)\b", lower) is not None
            or re.search(r"\b(armed|locked)\b.*\b(or not|\?)\b", lower) is not None
        )

        if is_status_query:
            state = self.services.get("state")
            lock = self.services.get("lock")
            lights = self.services.get("lights")
            if state:
                status_res = get_device_status(state, lock, lights)
                tool_summary = status_res["summary"]
                spoken = self._synthesize(prompt, tool_summary, history)
                return {
                    "response": spoken or tool_summary,
                    "tool_used": "device_status",
                    "tool_data": status_res,
                }

        # 4. Arm / Disarm Intent (Action commands or polite requests like 'could you arm the system?')
        if re.search(r"\b(arm|disarm)\b", lower):
            is_disarm = "disarm" in lower
            state = self.services.get("state")
            bus = self.services.get("bus")
            if state:
                result = set_armed_tool(
                    state, bus, actor=self.actor, armed=not is_disarm
                )
                return {
                    "response": result["summary"],
                    "tool_used": "arm_system",
                    "tool_data": result,
                }

        # 5. Security Briefing Intent
        if any(
            phrase in lower
            for phrase in (
                "briefing",
                "security briefing",
                "what happened",
                "security report",
                "daily report",
                "summary of events",
                "give me a briefing",
            )
        ):
            timeframe = "today"
            for tf in ("yesterday", "last night", "this morning", "this afternoon", "past week", "today"):
                if tf in lower:
                    timeframe = tf
                    break

            store = self.services.get("store")
            if store:
                briefing_res = get_security_briefing(store, timeframe=timeframe)
                tool_summary = briefing_res["summary"]
                # Synthesize with Qwen if available
                spoken = self._synthesize(prompt, tool_summary, history)
                return {
                    "response": spoken or tool_summary,
                    "tool_used": "security_briefing",
                    "tool_data": briefing_res,
                }

        # 6. Natural Event Search Intent
        if any(
            phrase in lower
            for phrase in (
                "who came",
                "who was",
                "did anyone",
                "any visitors",
                "any cars",
                "at the door",
                "in the driveway",
                "find events",
                "search events",
            )
        ):
            store = self.services.get("store")
            if store:
                search_res = search_events_tool(store, query=text)
                tool_summary = search_res["summary"]
                spoken = self._synthesize(prompt, tool_summary, history)
                return {
                    "response": spoken or tool_summary,
                    "tool_used": "search_events",
                    "tool_data": search_res,
                }

        # 7. General Assistant / Conversational Query
        spoken = self._synthesize(prompt, context=None, history=history)
        if not spoken:
            spoken = "I received your request, but could not determine a specific security action."
        return {
            "response": spoken,
            "tool_used": "general_llm",
            "tool_data": {},
        }

    def _synthesize(
        self,
        prompt: str,
        context: Optional[str] = None,
        history: Optional[list[dict[str, str]]] = None,
    ) -> Optional[str]:
        """Synthesize response with Qwen via RKLLMRunner."""
        try:
            runner = get_runner()
            if not runner.is_available:
                return None

            system_content = SYSTEM_VOICE_PROMPT
            if context:
                system_content += f"\n\nContext information from home security hub:\n{context}\nUse the context above to directly answer the user."

            messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
            if history:
                messages.extend(history[-4:])  # keep last 4 context turns
            messages.append({"role": "user", "content": prompt})

            response = runner.chat(messages, max_new_tokens=160, timeout=15.0)
            clean = response.strip().replace("*", "").replace("\n", " ")
            return clean if clean else None
        except Exception as exc:
            logger.warning("Synthesis error: %s", exc)
            return None
