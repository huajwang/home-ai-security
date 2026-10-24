"""Central Assistant Engine coordinating tools, guardrails, and RKLLM Qwen runner."""

from __future__ import annotations

import logging
from typing import Any, Optional

from hub.ai.intents import NONE, SEARCH_EVENTS, intent_prompt, parse_intent_label
from hub.ai.rkllm_bridge import get_runner
from hub.ai.rules import match_rule
from hub.ai.tools import (
    control_light_tool,
    get_device_status,
    speak_device_status,
    get_security_briefing,
    search_events_tool,
    set_armed_tool,
)

logger = logging.getLogger("home_ai.assistant")


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _meeting_chat():
    def chat(messages: list[dict[str, str]], max_new_tokens: int = 120, timeout: float = 30.0) -> str:
        runner = get_runner()
        if not runner.is_available:
            return ""
        return runner.chat(messages, max_new_tokens=max_new_tokens, timeout=timeout)

    return chat

CLASSIFY_MAX_TOKENS = 16

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
        hit = match_rule(text)

        if hit and hit.tool == "guardrail_unlock_blocked":
            return {
                "response": (
                    "Unlocking the deadbolt is not permitted via voice assistant for security reasons. "
                    "Please use the mobile app with biometric confirmation."
                ),
                "tool_used": "guardrail_unlock_blocked",
                "tool_data": {"action": "unlock_rejected"},
            }

        if hit and hit.tool in {"start_meeting", "end_meeting"}:
            return self._meeting(hit.tool, text)

        if hit and hit.tool in {"start_note", "end_note", "save_note"}:
            return self._note(hit.tool, text)

        if hit and hit.tool in {"add_task", "read_tasks"}:
            return self._task(hit, text)

        if hit and hit.tool == "control_light":
            lights = self.services.get("lights")
            result = control_light_tool(lights, turn_on=bool(hit.turn_on))
            return {
                "response": result["summary"],
                "tool_used": "control_light",
                "tool_data": result,
            }

        if hit and hit.tool == "device_status":
            state = self.services.get("state")
            lock = self.services.get("lock")
            lights = self.services.get("lights")
            if state:
                status_res = get_device_status(state, lock, lights)
                return {
                    "response": speak_device_status(status_res, prompt),
                    "tool_used": "device_status",
                    "tool_data": status_res,
                }

        if hit and hit.tool == "arm_system":
            state = self.services.get("state")
            bus = self.services.get("bus")
            if state:
                result = set_armed_tool(
                    state, bus, actor=self.actor, armed=bool(hit.armed)
                )
                return {
                    "response": result["summary"],
                    "tool_used": "arm_system",
                    "tool_data": result,
                }

        if hit and hit.tool == "security_briefing":
            store = self.services.get("store")
            if store:
                briefing_res = get_security_briefing(store, timeframe=hit.timeframe or "today")
                tool_summary = briefing_res["summary"]
                spoken = self._synthesize(prompt, tool_summary, history)
                return {
                    "response": spoken or tool_summary,
                    "tool_used": "security_briefing",
                    "tool_data": briefing_res,
                }

        if hit and hit.tool == "search_events":
            answered = self._answer_search(text, prompt, history, routed_by="rule")
            if answered:
                return answered

        # Rules missed. The fixed table may still pick 查事件.
        if self.services.get("store") and self._classify_intent(text) == SEARCH_EVENTS.label:
            answered = self._answer_search(text, prompt, history, routed_by="intent_table")
            if answered:
                return answered

        # 8. General Assistant / Conversational Query
        spoken = self._synthesize(prompt, context=None, history=history)
        if not spoken:
            spoken = "I received your request, but could not determine a specific security action."
        return {
            "response": spoken,
            "tool_used": "general_llm",
            "tool_data": {},
        }

    def _meeting(self, tool: str, text: str) -> dict[str, Any]:
        meetings = self.services.get("meetings")
        if meetings is None:
            return {
                "response": "Meetings are not available.",
                "tool_used": tool,
                "tool_data": {},
            }
        chinese = _has_cjk(text)
        if tool == "start_meeting":
            result = meetings.start()
            if result.get("already"):
                spoken = "会议已经开始了。" if chinese else "The meeting has already started."
            else:
                spoken = "会议开始了。" if chinese else "The meeting has started."
        else:
            result = meetings.finish(_meeting_chat())
            if result.get("had_meeting"):
                spoken = "纪要好了。" if chinese else "The minutes are ready."
            else:
                spoken = "没有正在进行的会议。" if chinese else "There is no meeting in progress."
        return {"response": spoken, "tool_used": tool, "tool_data": result}

    def _note(self, tool: str, text: str) -> dict[str, Any]:
        library = self.services.get("library")
        if library is None:
            return {"response": "Notes are not available.", "tool_used": tool, "tool_data": {}}
        chinese = _has_cjk(text)
        if tool == "start_note":
            result = library.start_dictation()
            if result.get("already"):
                spoken = "已经在记录了。" if chinese else "A note is already in progress."
            else:
                spoken = "开始记录了。" if chinese else "The note has started."
        elif tool == "end_note":
            result = library.finish_dictation(_meeting_chat())
            if result.get("had_note"):
                spoken = "记下了。" if chinese else "The note is saved."
            elif result.get("state") == "empty":
                spoken = "没有听到内容。" if chinese else "No speech was captured."
            else:
                spoken = "没有正在记录。" if chinese else "There is no note in progress."
        else:
            from hub.library.store import strip_note_command

            result = library.add_text(strip_note_command(text) or text, "", _meeting_chat())
            spoken = "记下了。" if result.get("ok", True) else ("没有听到内容。" if chinese else "No speech was captured.")
        return {"response": spoken, "tool_used": tool, "tool_data": result}

    def _task(self, hit: Any, text: str) -> dict[str, Any]:
        tasks = self.services.get("tasks")
        if tasks is None:
            return {"response": "Tasks are not available.", "tool_used": hit.tool, "tool_data": {}}
        chinese = _has_cjk(text)
        if hit.tool == "read_tasks":
            open_items = tasks.list_open()
            from hub.tasks.store import speak_open_tasks

            return {
                "response": speak_open_tasks(open_items, chinese),
                "tool_used": "read_tasks",
                "tool_data": {"tasks": open_items},
            }
        item = tasks.add(hit.kind or "reminder", text, _meeting_chat())
        spoken = f"已记下：{item['text']}。" if chinese else f"Noted: {item['text']}."
        return {"response": spoken, "tool_used": "add_task", "tool_data": item}

    def _answer_search(
        self,
        text: str,
        prompt: str,
        history: Optional[list[dict[str, str]]],
        routed_by: str,
    ) -> Optional[dict[str, Any]]:
        store = self.services.get("store")
        if not store:
            return None
        del prompt, history
        search_res = search_events_tool(store, query=text)
        data = dict(search_res)
        data["routed_by"] = routed_by
        return {
            "response": search_res["summary"],
            "tool_used": SEARCH_EVENTS.label,
            "tool_data": data,
        }

    def _classify_intent(self, prompt: str) -> str:
        """Ask the model to pick one label from the fixed table."""
        try:
            runner = get_runner()
            if not runner.is_available:
                return NONE.label
            raw = runner.chat(
                [
                    {"role": "system", "content": intent_prompt()},
                    {"role": "user", "content": prompt},
                ],
                max_new_tokens=CLASSIFY_MAX_TOKENS,
                timeout=10.0,
            )
            label = parse_intent_label(raw)
            logger.info("Intent table classified %r as %s (raw=%r)", prompt, label, raw)
            return label
        except Exception as exc:
            logger.warning("Intent classification error: %s", exc)
            return NONE.label

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
