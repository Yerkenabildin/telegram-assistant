# Telegram Auto-Responder Bot

A Telegram bot that automatically responds to incoming private messages based on your emoji status.

## Features

- Auto-reply to private messages based on custom emoji status
- Emoji-based message templates stored in SQLite
- ASAP urgency keyword detection with notifications
- Web-based Telegram authentication
- Docker support

## Setup

### 1. Clone the repository

```bash
git clone <repository-url>
cd telegram-assistant
```

### 2. Configure environment variables

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` and set the following variables:

- `API_ID`: Get from [my.telegram.org](https://my.telegram.org)
- `API_HASH`: Get from [my.telegram.org](https://my.telegram.org)
- `PERSONAL_TG_LOGIN`: Your personal Telegram username for notifications
- `WORK_TG_LOGIN`: Your work Telegram username allowed to set auto-replies
- `AVAILABLE_EMOJI_ID` (optional): Emoji status ID that disables auto-reply
- `SECRET_KEY` (optional): Secret key for session encryption (auto-generated if not set)

### 3. Run with Docker

```bash
# Build the image
docker build -t telegram-assistant:0.0.1 .

# Run with docker-compose
docker-compose up -d

# View logs
docker logs -f tg-helper
```

### 4. Run locally

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

## Authentication

1. Navigate to `http://localhost:8000` in your browser
2. Enter your phone number
3. Enter the verification code sent to your Telegram
4. If you have 2FA enabled, enter your password

## Usage

### Setting up auto-replies

Send a message to your bot account from your work account:

```
/set_for [emoji]
```

Reply to the message you want to use as a template.

### Auto-reply behavior

- Bot checks your current emoji status
- If a template is configured for that emoji, it will auto-reply to incoming private messages
- Rate limit: Only sends once per 30 minutes to each user (since last outgoing message)
- If your status is set to the "available" emoji, auto-reply is disabled

### ASAP notifications

When someone sends a message containing "ASAP" (case-insensitive), you'll receive a notification on your personal account (unless you're marked as available).

## Project Structure

```
.
├── main.py              # Main application entry point
├── models.py            # Database models
├── templates/           # HTML templates for authentication
├── storage/            # Persistent data (session, database)
├── Dockerfile          # Docker container configuration
├── docker-compose.yaml # Docker Compose configuration
└── requirements.txt    # Python dependencies
```

## License

MIT
