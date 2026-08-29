# Telegram AI Bot

A Telegram AI chatbot powered by Groq.

The bot supports customizable AI behavior, conversation history, web search, `.txt` file input, encrypted local user storage, request rate limiting, and structured logging.

## Features

- AI chat through the Groq API
- Custom AI behavior/personality for each user
- Conversation history
- Web search through the model's browser search tool
- `.txt` file input
- Encrypted user configuration and chat history
- API key validation during setup
- Per-user and global request limiting
- Error handling and crash logging
- Telegram user whitelist
- Separate logs for normal operation and crashes

## Project Structure

```text
Bot/
├── main.py
├── route.py
├── ai.py
├── storage.py
├── Forms/
│   └── User_form.py
├── data/
│   └── users/
├── logs/
│   └── crash_logs/
├── requirements.txt
├── README.md
└── .env
```

## Requirements

- Python 3.10 or newer
- A Telegram bot token
- A Groq API key

## Installation

Clone the repository:

```bash
git clone https://github.com/niki30b/Telegram-AI.git
cd Telegram-AI
```

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows:

```powershell
.venv\Scripts\activate
```

Install all dependencies:

```bash
pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the project directory:

```env
TOKEN_BOT=your_telegram_bot_token
STORAGE_ENCRYPTION_KEY=your_fernet_key
```

`TOKEN_BOT` is the Telegram bot token.

`STORAGE_ENCRYPTION_KEY` is optional. If it is not provided, the application uses the operating system credential store through `keyring` to generate and store the encryption key.

Do not publish `.env` or the `data/` directory to a public repository.

## Starting the Bot

Run:

```bash
python main.py
```

The bot will start polling Telegram for updates.

## First Setup

After starting the bot:

1. Send `/start`.
2. Press `Start set up`.
3. Create a Groq API key.
4. Send the API key to the bot.
5. Confirm the key.
6. Enter the behavior/instructions for your AI.
7. Start chatting.

The API key message is deleted after it is received when Telegram permissions allow the bot to do so.

## AI Behavior

During setup, you can describe how you want the AI to behave.

For example:

```text
You are a concise programming assistant.
Explain technical topics clearly.
Prefer practical examples and point out mistakes.
```

The behavior prompt is limited to 1,000 characters.

A `.txt` file can also be used as the behavior prompt.

## Limits

Current application limits:

- 10 requests per minute per user
- 2-second cooldown between requests
- 1 simultaneous AI request per user
- 3 simultaneous AI requests globally
- Maximum queue wait: 15 seconds
- Maximum queue waiters: 20
- Maximum behavior prompt: 1,000 characters
- Maximum `.txt` file size: 20 KB
- Maximum stored chat history: 20 messages

## Storage

User configuration and chat history are stored locally under:

```text
data/users/<user_id>/
```

Sensitive user data is encrypted using Fernet.

The encryption key can be supplied through `STORAGE_ENCRYPTION_KEY` or stored in the operating system credential store using `keyring`.

## Logging

Each bot launch creates a separate log file:

```text
logs/
├── 2026-08-29_13-00-00.log
└── crash_logs/
    └── 2026-08-29_13-00-00_crash.log
```

Normal application logs are stored in `logs/`.

Error-level logs are also written to the corresponding file in `logs/crash_logs/`.

## Model

The current model configured in the project is:

```text
openai/gpt-oss-20b
```

The model can be changed in `ai.py`.

## License

This project is licensed under the MIT License.
