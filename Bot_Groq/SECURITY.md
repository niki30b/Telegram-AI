# Security Policy

## Supported Versions

Currently, only the latest version of the project is supported.

| Version | Supported |
| ------- | --------- |
| Latest  | Yes |
| Older versions | No |

## Reporting a Vulnerability

If you discover a security vulnerability, please do not publish it publicly before it has been fixed.

Instead, open a private security advisory through GitHub or contact the repository owner directly.

Please include as much information as possible:

- A description of the vulnerability
- Steps to reproduce the issue
- The affected files or components
- The potential impact
- A possible fix, if you have one

You can expect an acknowledgement after the report has been reviewed.

Contact email "niko30b@gmail.com"

## Security Features

This project includes several security-related measures:

- User API keys and chat history are stored using Fernet encryption.
- Encryption keys can be provided through the `STORAGE_ENCRYPTION_KEY` environment variable.
- When no environment key is configured, the project can use the operating system credential store through `keyring`.
- Telegram bot access can be restricted using a user ID whitelist.
- API keys are validated before being saved.
- API key messages are deleted when Telegram permissions allow it.
- Request rate limiting and cooldowns help reduce spam and API abuse.
- Per-user and global concurrency limits help prevent request overload.
- User input and uploaded `.txt` files have size limits.

## Sensitive Data

Never commit sensitive information to the repository.

This includes:

- Telegram bot tokens
- Groq API keys
- Encryption keys
- `.env` files
- User configuration files
- Chat history
- OS credential store data

Recommended `.gitignore` entries:

```gitignore
.env
.venv/
venv/
__pycache__/
*.pyc
```

## Known Limitations

This project is designed primarily for private or small-scale usage.

Security depends on proper server configuration, operating system security, access permissions, and protection of environment variables and encryption keys.
