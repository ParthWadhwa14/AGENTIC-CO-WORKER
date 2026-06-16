from collections.abc import Iterable

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from app.config import settings


def _require_groq_key() -> str:
    if not settings.GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY is required for agent answering.")
    return settings.GROQ_API_KEY


def build_llm(model: str | None = None, streaming: bool = False):
    return ChatGroq(
        model=model or settings.GENERATION_MODEL,
        api_key=_require_groq_key(),
        temperature=settings.GENERATION_TEMPERATURE,
        streaming=streaming,
        max_tokens=settings.GROQ_MAX_OUTPUT_TOKENS,
    )


def content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "thinking":
                    continue
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
            elif item is not None:
                parts.append(str(item))
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


def _trim_middle(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    marker = "\n\n[...context truncated to fit the Groq model window...]\n\n"
    keep = max(0, max_chars - len(marker))
    head = keep // 2
    tail = keep - head
    return text[:head] + marker + text[-tail:]


def _message_role(message: BaseMessage | tuple[str, str]) -> str:
    if isinstance(message, tuple):
        return message[0]
    message_type = getattr(message, "type", "")
    return "system" if message_type == "system" else "human"


def _message_text(message: BaseMessage | tuple[str, str]) -> str:
    if isinstance(message, tuple):
        return message[1]
    return content_to_text(getattr(message, "content", ""))


def _copy_message(message: BaseMessage | tuple[str, str], content: str):
    if isinstance(message, tuple):
        return (message[0], content)
    if isinstance(message, SystemMessage):
        return SystemMessage(content=content)
    if isinstance(message, HumanMessage):
        return HumanMessage(content=content)
    return message.__class__(content=content)


def compact_messages(
    messages: list[BaseMessage | tuple[str, str]],
) -> list[BaseMessage | tuple[str, str]]:
    max_chars = settings.GROQ_CONTEXT_CHAR_LIMIT
    if max_chars <= 0:
        return messages

    system_messages = []
    other_messages = []
    for message in messages:
        if _message_role(message) == "system":
            system_messages.append(message)
        else:
            other_messages.append(message)

    system_chars = sum(len(_message_text(message)) for message in system_messages)
    remaining = max(8000, max_chars - system_chars)
    if not other_messages:
        return [_copy_message(message, _trim_middle(_message_text(message), max_chars)) for message in messages]

    per_message = max(4000, remaining // len(other_messages))
    compacted = []
    for message in messages:
        content = _message_text(message)
        role = _message_role(message)
        if role == "system":
            compacted.append(_copy_message(message, _trim_middle(content, max_chars)))
        else:
            compacted.append(_copy_message(message, _trim_middle(content, per_message)))
    return compacted


def invoke_with_fallback(messages: list[BaseMessage | tuple[str, str]]) -> str:
    errors = []
    messages = compact_messages(messages)
    for model in [settings.GENERATION_MODEL, settings.FALLBACK_GENERATION_MODEL]:
        try:
            response = build_llm(model=model, streaming=False).invoke(messages)
            return (
                content_to_text(response.content)
                if hasattr(response, "content")
                else str(response)
            )
        except Exception as exc:
            errors.append(f"{model}: {exc}")

    raise RuntimeError("All configured generation models failed: " + " | ".join(errors))


def stream_with_fallback(
    messages: list[BaseMessage | tuple[str, str]],
) -> Iterable[str]:
    errors = []
    messages = compact_messages(messages)
    for model in [settings.GENERATION_MODEL, settings.FALLBACK_GENERATION_MODEL]:
        try:
            llm = build_llm(model=model, streaming=True)
            for chunk in llm.stream(messages):
                content = (
                    content_to_text(chunk.content)
                    if hasattr(chunk, "content")
                    else str(chunk)
                )
                if content:
                    yield content
            return
        except Exception as exc:
            errors.append(f"{model}: {exc}")

    raise RuntimeError("All configured streaming models failed: " + " | ".join(errors))
