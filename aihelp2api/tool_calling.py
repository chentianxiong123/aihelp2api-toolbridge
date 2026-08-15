"""工具调用模块：提示注入、解析、流式过滤。"""
import json
import re
import uuid
from typing import Any, Dict, Iterable, List, Optional, Set


TOOL_PROMPT_TEMPLATE = """You have access to the following tools. When you need to call a tool,
output a JSON block wrapped in <tool_call> tags like this:

<tool_call>
{"name": "tool_name", "arguments": {"param1": "value1"}}
</tool_call>

Available tools:
{tool_definitions}

Additional tool choice rule:
{tool_choice_rule}

CRITICAL TOOL CALL RULES:
1. Thinking vs Executing:
   - You may plan tool usage in natural language during reasoning.
   - Do NOT output the actual <tool_call> block during reasoning.
   - The <tool_call> block is an execution command, not a planning note.

2. Trigger Placement:
   - The <tool_call> block must appear only in the final visible response.
   - If a thinking section exists, output the tool call only after thinking ends.

3. Strict Format:
   - When calling a tool, output ONLY the <tool_call> block.
   - Do NOT wrap it in markdown code fences.
   - Do NOT add explanations, comments, or extra text.
   - If multiple tool calls are necessary, output one <tool_call> block per call.

4. No Tool Needed:
   - If no tool is needed, answer normally without any <tool_call> block.

5. After Tool Results:
   - Tool results will be provided in a follow-up message.
   - Use the result to answer the user naturally.
   - Do not simply echo raw JSON.
   - Call another tool only if necessary.
"""

TOOL_CALL_FULL_PATTERN = re.compile(r"<tool_call>.*?</tool_call>", re.DOTALL)
TOOL_CALL_JSON_PATTERN = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


def build_tool_choice_rule(tool_choice: Any) -> str:
    """Convert OpenAI `tool_choice` into a natural-language rule."""
    if not tool_choice or tool_choice == "auto":
        return "Use tools only when they are helpful."
    if tool_choice == "none":
        return "Do not call any tool. Answer directly without <tool_call>."
    if tool_choice == "required":
        return "You must call at least one available tool before answering."
    if isinstance(tool_choice, dict):
        name = (tool_choice.get("function") or {}).get("name")
        if name:
            return f"You must call the tool named {name!r}."
    return "Use tools only when they are helpful."


def build_tool_prompt(tools: List[Dict[str, Any]], tool_choice: Any = None) -> str:
    """Build the complete injected tool prompt."""
    tool_definitions = json.dumps(tools, ensure_ascii=False, indent=2)
    return TOOL_PROMPT_TEMPLATE.replace("{tool_definitions}", tool_definitions).replace(
        "{tool_choice_rule}", build_tool_choice_rule(tool_choice)
    )


def inject_tools_into_messages(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    tool_choice: Any = None,
) -> List[Dict[str, Any]]:
    """Append the tool prompt to the system message, or insert one if absent."""
    if not tools or tool_choice == "none":
        return messages

    tool_prompt = build_tool_prompt(tools, tool_choice)
    new_messages = list(messages)

    for index, message in enumerate(new_messages):
        if message.get("role") == "system":
            original = message.get("content") or ""
            new_messages[index] = {
                **message,
                "content": original + "\n\n" + tool_prompt,
            }
            break
    else:
        new_messages.insert(0, {"role": "system", "content": tool_prompt})

    return new_messages


def allowed_tool_names_from_tools(tools: Iterable[Dict[str, Any]]) -> Set[str]:
    """Extract OpenAI function tool names for whitelist validation."""
    names: Set[str] = set()
    for tool in tools:
        name = (tool.get("function") or {}).get("name")
        if isinstance(name, str) and name:
            names.add(name)
    return names


def parse_tool_calls(
    text: str,
    allowed_tool_names: Optional[Set[str]] = None,
) -> tuple:
    """Remove tool-call blocks from text and return OpenAI-compatible calls."""
    tool_calls: List[Dict[str, Any]] = []

    for raw_json in TOOL_CALL_JSON_PATTERN.findall(text):
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            continue

        name = data.get("name", "")
        if not isinstance(name, str) or not name:
            continue

        if allowed_tool_names is not None and name not in allowed_tool_names:
            continue

        arguments = data.get("arguments", {})
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments, ensure_ascii=False)

        tool_calls.append(
            {
                "id": "call_" + uuid.uuid4().hex[:24],
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": arguments,
                },
            }
        )

    clean_text = TOOL_CALL_FULL_PATTERN.sub("", text).strip()
    return clean_text, tool_calls


class ToolCallFilter:
    """Streaming filter that hides <tool_call> blocks from visible output."""

    TAG_START = "<tool_call>"
    TAG_END = "</tool_call>"
    MAX_PREFIX = len(TAG_START) - 1

    def __init__(self) -> None:
        self.buffer = ""
        self.in_tool_call = False

    def feed(self, text: str) -> str:
        """Return only the safe visible text for one upstream chunk."""
        self.buffer += text
        output = ""

        while True:
            if not self.in_tool_call:
                start = self.buffer.find(self.TAG_START)
                if start == -1:
                    safe = self._safe_prefix(self.buffer)
                    output += safe
                    self.buffer = self.buffer[len(safe) :]
                    break

                output += self.buffer[:start]
                self.buffer = self.buffer[start:]
                self.in_tool_call = True
            else:
                end = self.buffer.find(self.TAG_END)
                if end == -1:
                    break

                self.buffer = self.buffer[end + len(self.TAG_END) :]
                self.in_tool_call = False

        return output

    def flush(self) -> str:
        """Flush visible trailing text; discard unfinished tool-call content."""
        if self.in_tool_call:
            self.buffer = ""
            return ""

        remaining = self.buffer
        self.buffer = ""
        return remaining

    def _safe_prefix(self, text: str) -> str:
        safe_end = len(text)
        for length in range(min(self.MAX_PREFIX, len(text)), 0, -1):
            if self.TAG_START.startswith(text[-length:]):
                safe_end = len(text) - length
                break
        return text[:safe_end]


def normalize_tool_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert role=tool messages to user messages for text-only upstreams."""
    normalized: List[Dict[str, Any]] = []

    for message in messages:
        if message.get("role") == "tool":
            name = message.get("name") or message.get("tool_call_id") or "unknown"
            normalized.append(
                {
                    "role": "user",
                    "content": f"[Tool Result from '{name}']:\n{message.get('content', '')}",
                }
            )
        else:
            normalized.append(message)

    return normalized
