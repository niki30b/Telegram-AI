# Telegram AI Bot — Ollama Version (BETA)

A Telegram AI chatbot powered by **Ollama** with customizable behavior, conversation history, web search, and encrypted local storage.

This is a standalone branch (`Bot-Ollama-BETA`) that uses a **locally running Ollama** instance instead of cloud APIs like Groq or OpenRouter.

---

## Features

- AI chat through a **local Ollama** instance
- Custom AI behavior/personality for each user
- Conversation history
- Web search through the model's browser search tool
- `.txt` file input
- Encrypted user configuration and chat history
- Per-user and global request limiting
- Error handling and crash logging
- Telegram user whitelist
- Separate logs for normal operation and crashes

---

## Project Structure

Bot_Ollama/

├── main.py

├── route.py

├── ai.py

├── storage.py

├── Forms/

│   └── User_form.py

├── data/

│   └── users/

└── logs/

└── crash_logs/

plain


---

## Requirements

- **Python 3.10** or newer
- A **Telegram bot token**
- **[Ollama](https://ollama.com/)** installed and running locally (or on a remote server)
- A pulled Ollama model (e.g., `llama3`, `mistral`, `qwen2.5`, etc.)

Install all Python dependencies:

```bash
pip install -r requirements.txt

Install Ollama

    Download and install Ollama: https://ollama.com/download
    Pull a model:
    bash

    ollama pull llama3

    Make sure Ollama is running:
    bash

    ollama serve

Configuration
Create a .env file in the Bot_Ollama/ directory:
env

TOKEN_BOT=your_telegram_bot_token
OLLAMA_URL=http://localhost:11434
STORAGE_ENCRYPTION_KEY=your_fernet_key


Variable	Description
TOKEN_BOT	Your Telegram bot token from @BotFather
OLLAMA_URL	URL of your Ollama instance. Default: http://localhost:11434
STORAGE_ENCRYPTION_KEY	(Optional) Fernet key for encrypting user data. If not provided, the OS credential store (via keyring) is used.

    ⚠️ Do not publish .env or the data/ directory to a public repository.

Starting the Bot

    Make sure Ollama is running:
    bash

    ollama serve

    In a separate terminal, run the bot:
    bash

    cd Bot_Ollama
    python main.py

The bot will start polling Telegram for updates.
First Setup
After starting the bot:

    Send /start.
    Press Start set up.
    Enter the Ollama model name you want to use (e.g., llama3, mistral, qwen2.5).
    Enter the behavior/instructions for your AI.
    Start chatting.

AI Behavior
During setup, you can describe how you want the AI to behave.
For example:
plain

You are a concise programming assistant.
Explain technical topics clearly.
Prefer practical examples and point out mistakes.

The behavior prompt is limited to 1,000 characters.
A .txt file can also be used as the behavior prompt.
Limits
Current application limits:

    10 requests per minute per user
    2-second cooldown between requests
    1 simultaneous AI request per user
    3 simultaneous AI requests globally
    Maximum queue wait: 15 seconds
    Maximum queue waiters: 20
    Maximum behavior prompt: 1,000 characters
    Maximum .txt file size: 20 KB
    Maximum stored chat history: 20 messages

Storage
User configuration and chat history are stored locally under:
plain

data/users/<user_id>/

Sensitive user data is encrypted using Fernet.
The encryption key can be supplied through STORAGE_ENCRYPTION_KEY or stored in the operating system credential store using keyring.
Logging
Each bot launch creates a separate log file:
plain

logs/
├── 2026-09-06_14-00-00.log
└── crash_logs/
    └── 2026-09-06_14-00-00_crash.log

    Normal application logs are stored in logs/.
    Error-level logs are also written to the corresponding file in logs/crash_logs/.

Model
The model is configured per user during setup via the Ollama model name (e.g., llama3, mistral, qwen2.5).
You can change the default model or add new ones by pulling them in Ollama:
bash

ollama pull <model-name>

Differences from Main Branch

Feature	main (Groq / OpenRouter)	Bot-Ollama-BETA (Ollama)
AI Provider	Groq / OpenRouter API	Local Ollama instance
API Key	Required (Groq/OpenRouter key)	Not required
Internet	Requires internet connection	Works fully offline
Setup step	Enter API key	Enter Ollama model name
Speed	Fast (cloud GPU)	Depends on your hardware
Privacy	Data sent to cloud API	Everything stays local
License
This project is released under The Unlicense.
You are free to use, copy, modify, publish, distribute, sublicense, and/or sell this software without restriction.
