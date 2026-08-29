import logging

from groq import Groq
from groq import (
    APIStatusError,
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
    InternalServerError,
)

from storage import (
    load_user_config,
    load_chat_history,
    append_chat_message,
)

logger = logging.getLogger("Groq")

MODEL = "openai/gpt-oss-20b" #model/version
word_limit = " Limit yourself to just 100 words."


def validate_api_key(api_key: str) -> bool:
    client = None
    try:
        client = Groq(api_key=api_key)
        client.models.list()
        return True
    except AuthenticationError:
        return False
    except (APIConnectionError, APITimeoutError):
        raise ConnectionError("Could not reach Groq API")
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def groq_history(history: list) -> list:
    result = []
    for message in history:
        role = message.get("role")
        text = message.get("text")
        if role not in ("user", "model"):
            continue
        if not isinstance(text, str) or not text:
            continue
        groq_role = "assistant" if role == "model" else "user"
        result.append({"role": groq_role, "content": text})
    return result


def get_user_client_and_messages(user_id: int, new_message: str):
    user_config = load_user_config(user_id)

    api_key = user_config.get("api_key")
    prompt = user_config.get("prompt", "")

    if not api_key:
        raise ValueError(f"API key is not configured for user {user_id}")
    if not isinstance(prompt, str):
        raise ValueError(f"Prompt has invalid format for user {user_id}")

    full_prompt = prompt + word_limit

    history = load_chat_history(user_id)
    history_messages = groq_history(history)

    messages = []
    if full_prompt:
        messages.append({"role": "system", "content": full_prompt})
    messages.extend(history_messages)
    messages.append({"role": "user", "content": new_message})

    client = Groq(api_key=api_key)
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
            temperature=1.2,
            max_completion_tokens=4096,
            reasoning_effort="low",
            include_reasoning=False,
            tools=[{"type": "browser_search"}],
        )

        choice = response.choices[0]
        response_message = choice.message

        logger.info(
            "Groq response | user=%s | finish_reason=%r | content_is_none=%s | usage=%r",
            user_id,
            choice.finish_reason,
            response_message.content is None,
            response.usage,
        )

        response_text = response_message.content
        if response_text is None or not response_text.strip():
            logger.error("Groq returned empty content for user %s", user_id)
            raise ValueError("Groq returned an empty response")

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
        logger.exception("Groq server error for user %s", user_id)
        raise
    except Exception:
        logger.exception("Groq request failed for user %s", user_id)
        raise
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
