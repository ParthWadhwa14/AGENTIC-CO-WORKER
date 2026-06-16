from collections.abc import Iterable

from langchain_core.messages import BaseMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings


def _require_google_key() -> str:
    if not settings.GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY is required for agent answering.")
    return settings.GOOGLE_API_KEY


def build_llm(model: str | None = None, streaming: bool = False):
    return ChatGoogleGenerativeAI(
        model=model or settings.GENERATION_MODEL,
        google_api_key=_require_google_key(),
        temperature=settings.GENERATION_TEMPERATURE,
        streaming=streaming,
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


def invoke_with_fallback(messages: list[BaseMessage | tuple[str, str]]) -> str:
    errors = []
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
