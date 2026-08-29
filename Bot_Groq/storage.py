import json
import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("Storage")

path = Path(__file__).resolve().parent
data_path = path / "data"

config = data_path / "config.json"
USERS_DIR = data_path / "users"

MAX_HISTORY_MESSAGES = 20

KEYRING_SERVICE = "telegram_ai_bot"
KEYRING_USERNAME = "data_encryption_key"

try:
    import keyring
except ImportError:
    keyring = None


def _get_encryption_key() -> bytes:
    env_key = os.getenv("STORAGE_ENCRYPTION_KEY")
    if env_key:
        try:
            key = env_key.encode("ascii")
            Fernet(key)
            return key
        except Exception as exc:
            raise RuntimeError("STORAGE_ENCRYPTION_KEY exists but is not a valid Fernet key") from exc

    if keyring is None:
        raise RuntimeError("keyring is not installed. Run: pip install cryptography keyring")

    try:
        stored_key = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        if stored_key:
            key = stored_key.encode("ascii")
            Fernet(key)
            return key

        key = Fernet.generate_key()
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, key.decode("ascii"))
        logger.info("Created a new storage encryption key in the OS credential store.")
        return key

    except Exception as exc:
        raise RuntimeError(
            "Could not access the OS credential store. "
            "Set STORAGE_ENCRYPTION_KEY manually or fix keyring."
        ) from exc


_FERNET = Fernet(_get_encryption_key())


def get_user_dir(user_id: int) -> Path:
    try:
        user_id = int(user_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid user_id") from exc
    if user_id < 0:
        raise ValueError("Invalid user_id")
    user_dir = USERS_DIR / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def _load_json(file_path: Path, default):
    if not file_path.exists():
        return default
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error("JSON file %s is corrupted: %s", file_path, e)
        raise


def _save_json(file_path: Path, data):
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = file_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(file_path)


def _load_encrypted(file_path: Path, default):
    if not file_path.exists():
        return default
    try:
        encrypted = file_path.read_bytes()
        decrypted = _FERNET.decrypt(encrypted)
        return json.loads(decrypted.decode("utf-8"))
    except InvalidToken:
        logger.critical("Could not decrypt %s: invalid encryption key or corrupted file.", file_path)
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.error("Encrypted file %s is corrupted: %s", file_path, exc)
        raise


def _save_encrypted(file_path: Path, data):
    file_path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encrypted = _FERNET.encrypt(raw)
    tmp = file_path.with_suffix(file_path.suffix + ".tmp")
    tmp.write_bytes(encrypted)
    tmp.replace(file_path)


def load_user_config(user_id: int) -> dict:
    p = get_user_dir(user_id) / "config.json"
    data = _load_encrypted(p, {})
    if not isinstance(data, dict):
        raise ValueError("User config must be a JSON object")
    return data


def save_user_config(user_id: int, data: dict):
    if not isinstance(data, dict):
        raise TypeError("user config must be a dict")
    p = get_user_dir(user_id) / "config.json"
    _save_encrypted(p, data)


def get_user_history_path(user_id: int) -> Path:
    return get_user_dir(user_id) / "chat_history.json"


def load_chat_history(user_id: int) -> list:
    p = get_user_history_path(user_id)
    history = _load_encrypted(p, [])
    if not isinstance(history, list):
        logger.error("Chat history has invalid format for user %s", user_id)
        return []
    return history


def save_chat_history(user_id: int, history: list):
    if not isinstance(history, list):
        raise TypeError("history must be a list")
    if len(history) > MAX_HISTORY_MESSAGES:
        history = history[-MAX_HISTORY_MESSAGES:]
    p = get_user_history_path(user_id)
    _save_encrypted(p, history)


def append_chat_message(user_id: int, role: str, text: str):
    if role not in ("user", "model"):
        raise ValueError("role must be 'user' or 'model'")
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    history = load_chat_history(user_id)
    history.append({"role": role, "text": text})
    save_chat_history(user_id, history)


def load_data():
    return _load_json(config, {})


def save_data(data):
    _save_json(config, data)
