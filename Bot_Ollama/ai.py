import logging
import os
from ddgs import DDGS
from ddgs.exceptions import DDGSException

import ollama

from storage import (
    load_user_config,
    load_chat_history,
    append_chat_message,
)

logger = logging.getLogger("Ollama")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

AVAILABLE_MODELS = {
    "gemma3": "huihui_ai/gemma3-abliterated:12b-q8_0",
    "qwen3": "huihui_ai/qwen3-abliterated:8b",
    "dolphin3": "dolphin3:8b",
    "dolphin-mixtral": "dolphin-mixtral",
}

word_limit = "Follow your behavioral instructions. Limit yourself to just 300 words."

INSTRUCTION_FOLLOWING_PREFIX = (
    "Follow the behavior instructions below exactly — tone, personality, "
    "profanity, everything. Do not soften, filter, or add disclaimers "
    "unless the instructions themselves ask for that."
)

INSTRUCTION_FOLLOWING_SUFFIX = (
    "Follow the behavior instructions above precisely, including any "
    "requested tone, personality, or language style (including profanity "
    "if instructed)."
)


def build_system_prompt(user_prompt: str) -> str:
    parts = [INSTRUCTION_FOLLOWING_PREFIX]
    if user_prompt:
        parts.append(user_prompt)
    parts.append(word_limit)
    parts.append(INSTRUCTION_FOLLOWING_SUFFIX)
    return " ".join(parts)


def ollama_history(history: list) -> list:
    result = []
    for message in history:
        role = message.get("role")
        text = message.get("text")
        if role not in ("user", "model"):
            continue
        if not isinstance(text, str) or not text:
            continue
        api_role = "assistant" if role == "model" else "user"
        result.append({"role": api_role, "content": text})
    return result


def get_user_messages_and_model(user_id: int, new_message: str):
    user_config = load_user_config(user_id)

    model = user_config.get("model")
    prompt = user_config.get("prompt", "")

    # api_key тут сознательно НЕ проверяется и никуда не передаётся —
    # Ollama не авторизует по ключу, это чисто наш внутренний токен.
    # Доступ и лимиты всегда решаются по user_id, не по этому ключу.
    if not model or model not in AVAILABLE_MODELS.values():
        raise ValueError(f"Model is not configured for user {user_id}")
    if not isinstance(prompt, str):
        raise ValueError(f"Prompt has invalid format for user {user_id}")

    full_prompt = build_system_prompt(prompt)

    history = load_chat_history(user_id)
    history_messages = ollama_history(history)

    messages = []
    if full_prompt:
        messages.append({"role": "system", "content": full_prompt})
    messages.extend(history_messages)
    messages.append({"role": "user", "content": new_message})

    return model, messages


def generate_response(user_id: int, message: str) -> str:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("Message must be a non-empty string")

    try:
        model, messages = get_user_messages_and_model(user_id, message)

        client = ollama.Client(host=OLLAMA_BASE_URL, timeout=120)

        response = client.chat(
            model=model,
            messages=messages,
            options={
                "temperature": 0.13,
                "num_predict": 1024,
                "frequency_penalty": 0.4,

            },
        )

        response_text = response.message.content

        logger.info(
            "Ollama response | user=%s | model=%s | done_reason=%r | content_is_none=%s",
            user_id, model, getattr(response, "done_reason", None), response_text is None,
        )

        if response_text is None or not response_text.strip():
            logger.error("Ollama returned empty content for user %s", user_id)
            raise ValueError("Ollama returned an empty response")

        response_text = response_text.strip()

        append_chat_message(user_id, "user", message)
        append_chat_message(user_id, "model", response_text)

        return response_text

    except ollama.ResponseError as e:
        logger.exception("Ollama server error for user %s: %s", user_id, e)
        raise
    except ollama.RequestError as e:
        logger.exception("Ollama request malformed for user %s: %s", user_id, e)
        raise
    except Exception:
        logger.exception("Ollama request failed for user %s", user_id)
        raise



def web_search(query: str, max_results: int = 3) -> str:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
    except DDGSException:
        logger.exception("Web search failed for query %r", query)
        raise ConnectionError("Web search is unavailable right now")

    logger.info("Web search | query=%r | results=%d | titles=%r",
                query, len(results), [r.get("title") for r in results])

    if not results:
        return ""

    lines = []
    for i, r in enumerate(results, start=1):
        title = r.get("title", "")
        body = r.get("body", "")
        href = r.get("href", "")
        lines.append(f"{i}. {title}\n{body}\nSource: {href}")

    return "\n\n".join(lines)


def get_user_messages_and_model(user_id: int, new_message: str, extra_context: str | None = None):
    user_config = load_user_config(user_id)

    model = user_config.get("model")
    prompt = user_config.get("prompt", "")

    if not model or model not in AVAILABLE_MODELS.values():
        raise ValueError(f"Model is not configured for user {user_id}")
    if not isinstance(prompt, str):
        raise ValueError(f"Prompt has invalid format for user {user_id}")

    full_prompt = build_system_prompt(prompt)

    history = load_chat_history(user_id)
    history_messages = ollama_history(history)

    messages = []
    if full_prompt:
        messages.append({"role": "system", "content": full_prompt})

    if extra_context:
        messages.append({
            "role": "system",
            "content": (
                "The following are live web search results for the user's query. "
                "These results are current and correct. Your own training data is "
                "outdated and must NOT be used for anything these results cover — "
                "names, titles, dates, current events. If the search results "
                "contradict what you 'remember', the search results are right and "
                "your memory is wrong. Base your answer entirely on them.\n\n"
                f"{extra_context}"
            ),
        }),

    messages.extend(history_messages)
    messages.append({"role": "user", "content": new_message})

    return model, messages


def generate_response(user_id: int, message: str, extra_context: str | None = None) -> str:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("Message must be a non-empty string")

    try:
        model, messages = get_user_messages_and_model(user_id, message, extra_context)

        client = ollama.Client(host=OLLAMA_BASE_URL, timeout=120)

        response = client.chat(
            model=model,
            messages=messages,
            options={
                "temperature": 0.13,
                "num_predict": 1024,
                "frequency_penalty": 0.4,
            },
        )

        response_text = response.message.content

        logger.info(
            "Ollama response | user=%s | model=%s | done_reason=%r | content_is_none=%s",
            user_id, model, getattr(response, "done_reason", None), response_text is None,
        )

        if response_text is None or not response_text.strip():
            logger.error("Ollama returned empty content for user %s", user_id)
            raise ValueError("Ollama returned an empty response")

        response_text = response_text.strip()

        append_chat_message(user_id, "user", message)
        append_chat_message(user_id, "model", response_text)

        return response_text

    except ollama.ResponseError as e:
        logger.exception("Ollama server error for user %s: %s", user_id, e)
        raise
    except ollama.RequestError as e:
        logger.exception("Ollama request malformed for user %s: %s", user_id, e)
        raise
    except Exception:
        logger.exception("Ollama request failed for user %s", user_id)
        raise
