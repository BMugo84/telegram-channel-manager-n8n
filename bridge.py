"""
Telegram MTProto Bridge
-----------------------
A local Flask server that exposes HTTP endpoints for n8n to interact
with your personal Telegram account via Telethon (MTProto protocol).

Endpoints:
  GET  /health         - Check if bridge is running
  GET  /dialogs        - List all joined channels/groups
  POST /leave          - Leave a channel by ID
  GET  /channel/<id>   - Get info about a specific channel
"""

import os
import asyncio
import logging
from functools import wraps

from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat
from telethon.errors import (
    FloodWaitError,
    ChannelPrivateError,
    UserNotParticipantError,
)

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv()

API_ID       = int(os.getenv("API_ID", 0))
API_HASH     = os.getenv("API_HASH", "")
PHONE        = os.getenv("PHONE", "")
PORT         = int(os.getenv("PORT", 5005))
SESSION_NAME = os.getenv("SESSION_NAME", "telegram_session")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)

# ── Validate env ──────────────────────────────────────────────────────────────

if not API_ID or not API_HASH or not PHONE:
    raise EnvironmentError(
        "Missing credentials. Make sure API_ID, API_HASH, and PHONE are set in .env"
    )

# ── Event loop helper ─────────────────────────────────────────────────────────
# Python 3.14 no longer auto-creates an event loop, so we create and set one
# BEFORE creating the Telethon client.

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

def run(coro):
    """Run an async coroutine from sync Flask context."""
    return loop.run_until_complete(coro)

# ── Telethon client (single shared instance) ──────────────────────────────────
# Must be created AFTER the event loop is set.

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# ── Flask app ─────────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app)  # Allow requests from the web UI and n8n

# ── Helpers ───────────────────────────────────────────────────────────────────

def success(data=None, message="OK"):
    return jsonify({"status": "success", "message": message, "data": data})

def error(message, code=400):
    return jsonify({"status": "error", "message": message, "data": None}), code

def serialize_dialog(dialog):
    """Convert a Telethon Dialog object to a plain dict."""
    entity = dialog.entity
    is_channel = isinstance(entity, Channel)
    is_group   = isinstance(entity, Chat)

    return {
        "id":           entity.id,
        "name":         dialog.name,
        "type":         "channel" if is_channel and entity.broadcast
                        else "supergroup" if is_channel and entity.megagroup
                        else "group" if is_group
                        else "other",
        "username":     getattr(entity, "username", None),
        "members_count": getattr(entity, "participants_count", None),
        "unread_count": dialog.unread_count,
        "is_muted":     dialog.dialog.notify_settings.mute_until is not None
                        if dialog.dialog.notify_settings else False,
    }

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Quick check — is the bridge up and authenticated?"""
    connected = run(client.is_user_authorized())
    return success(
        data={"authenticated": connected, "phone": PHONE},
        message="Bridge is running",
    )


@app.get("/dialogs")
def get_dialogs():
    """
    Return all channels and groups the user has joined.

    Query params:
      type   = channel | supergroup | group | all  (default: all)
      limit  = max number of results               (default: 200)
    """
    type_filter = request.args.get("type", "all")
    limit       = int(request.args.get("limit", 200))

    async def _fetch():
        dialogs = await client.get_dialogs(limit=limit)
        results = []
        for d in dialogs:
            if not isinstance(d.entity, (Channel, Chat)):
                continue  # skip private chats / bots
            serialized = serialize_dialog(d)
            if type_filter == "all" or serialized["type"] == type_filter:
                results.append(serialized)
        return results

    try:
        data = run(_fetch())
        return success(data=data, message=f"Found {len(data)} dialog(s)")
    except FloodWaitError as e:
        return error(f"Telegram rate limit. Retry after {e.seconds}s", 429)
    except Exception as e:
        log.exception("Error fetching dialogs")
        return error(str(e), 500)


@app.post("/leave")
def leave_channel():
    """
    Leave a channel or group.

    JSON body:
      { "channel_id": 1234567890 }

    Returns the name of the channel that was left.
    """
    body = request.get_json(silent=True) or {}
    channel_id = body.get("channel_id")

    if not channel_id:
        return error("Missing 'channel_id' in request body")

    async def _leave():
        entity = await client.get_entity(int(channel_id))
        name   = getattr(entity, "title", str(channel_id))
        await client.delete_dialog(entity)
        return name

    try:
        name = run(_leave())
        log.info("Left channel: %s (%s)", name, channel_id)
        return success(
            data={"channel_id": channel_id, "name": name},
            message=f"Successfully left '{name}'",
        )
    except ChannelPrivateError:
        return error("Channel is private or no longer accessible", 403)
    except UserNotParticipantError:
        return error("You are not a member of this channel", 404)
    except FloodWaitError as e:
        return error(f"Telegram rate limit. Retry after {e.seconds}s", 429)
    except Exception as e:
        log.exception("Error leaving channel %s", channel_id)
        return error(str(e), 500)


@app.get("/channel/<int:channel_id>")
def get_channel(channel_id):
    """Get details about a single channel by its ID."""

    async def _fetch():
        entity = await client.get_entity(channel_id)
        full   = await client(
            __import__(
                "telethon.tl.functions.channels",
                fromlist=["GetFullChannelRequest"],
            ).GetFullChannelRequest(entity)
        )
        return {
            "id":             entity.id,
            "name":           entity.title,
            "username":       getattr(entity, "username", None),
            "members_count":  getattr(full.full_chat, "participants_count", None),
            "description":    getattr(full.full_chat, "about", ""),
            "is_broadcast":   getattr(entity, "broadcast", False),
            "is_megagroup":   getattr(entity, "megagroup", False),
        }

    try:
        data = run(_fetch())
        return success(data=data)
    except Exception as e:
        log.exception("Error fetching channel %s", channel_id)
        return error(str(e), 500)


# ── Startup ───────────────────────────────────────────────────────────────────

def start_client():
    """
    Connect Telethon and authenticate.
    On first run this will prompt for your phone OTP in the terminal.
    After that, the session file is reused automatically.
    """
    log.info("Connecting to Telegram...")
    loop.run_until_complete(client.start(phone=PHONE))
    me = loop.run_until_complete(client.get_me())
    log.info("✅ Logged in as: %s (@%s)", me.first_name, me.username)


if __name__ == "__main__":
    start_client()
    log.info("🚀 Bridge running on http://localhost:%s", PORT)
    app.run(host="0.0.0.0", port=PORT, debug=False)