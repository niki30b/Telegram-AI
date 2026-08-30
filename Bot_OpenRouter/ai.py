import logging

from openai import OpenAI
from openai import (
    APIStatusError,
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
    InternalServerError,
)
import requests

from storage import (
    load_user_config,
    load_chat_history,
    append_chat_message,
)

logger = logging.getLogger("OpenRouter")  # name in logs

BASE_URL = "https://openrouter.ai/api/v1"

# Без ":free" — платная версия, работает с любым ключом у которого есть
# кредиты. Юзер сам может дописать ":free" себе, если хочет бесплатный
# (но более медленный и урезанный по лимитам) тир — это зависит от его
# ключа, не от тебя.
MODEL = "cognitivecomputations/dolphin-mistral-24b-venice-edition" # you can switch model

word_limit = " Follow your behavioral instructions. Limit yourself to just 100 words."

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

EXTRA_HEADERS = {
    "HTTP-Referer": "https://github.com/",
    "X-Title": "GenaiZen0X",
}


def validate_api_key(api_key: str) -> bool:
    try:
        response = requests.get(
            f"{BASE_URL}/key",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
    except requests.exceptions.RequestException:
        raise ConnectionError("Could not reach OpenRouter API")

    if response.status_code == 401:
        return False
    if response.status_code >= 500:
        raise ConnectionError("OpenRouter API is unavailable right now")

    response.raise_for_status()
    return True


def openrouter_history(history: list) -> list:
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


def get_user_client_and_messages(user_id: int, new_message: str):
    user_config = load_user_config(user_id)

    api_key = user_config.get("api_key")
    prompt = user_config.get("prompt", "")

    if not api_key:
        raise ValueError(f"API key is not configured for user {user_id}")
    if not isinstance(prompt, str):
        raise ValueError(f"Prompt has invalid format for user {user_id}")

    full_prompt = build_system_prompt(prompt)

    history = load_chat_history(user_id)
    history_messages = openrouter_history(history)

    messages = []
    if full_prompt:
        messages.append({"role": "system", "content": full_prompt})
    messages.extend(history_messages)
    messages.append({"role": "user", "content": new_message})

    client = OpenAI(base_url=BASE_URL, api_key=api_key)
    return client, messages


def generate_response(user_id: int, message: str) -> str:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("Message must be a non-empty string")

    client = None
    try:
        client, messages = get_user_client_and_messages(user_id, message)

        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.13,
            max_tokens=1024,
            frequency_penalty=0.4,
            extra_headers=EXTRA_HEADERS,
        )

        choice = response.choices[0]
        response_message = choice.message

        logger.info(
            "OpenRouter response | user=%s | finish_reason=%r | content_is_none=%s",
            user_id,
            choice.finish_reason,
            response_message.content is None,
        )

        response_text = response_message.content
        if response_text is None or not response_text.strip():
            logger.error("OpenRouter returned empty content for user %s", user_id)
            raise ValueError("OpenRouter returned an empty response")

        response_text = response_text.strip()

        append_chat_message(user_id, "user", message)
        append_chat_message(user_id, "model", response_text)

        return response_text

    except (
        APIStatusError,
        InternalServerError,
        APIConnectionError,
        APITimeoutError,
        RateLimitError,
    ):
        logger.exception("OpenRouter server error for user %s", user_id)
        raise
    except Exception:
        logger.exception("OpenRouter request failed for user %s", user_id)
        raise
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
