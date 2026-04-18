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

# ── Event loop ────────────────────────────────────────────────────────────────
# Must be created and set BEFORE TelegramClient is instantiated (Python 3.14+)

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# ── Telethon client ───────────────────────────────────────────────────────────

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# ── Async helper ──────────────────────────────────────────────────────────────

def run(coro):
    """Run an async coroutine from sync Flask context."""
    return loop.run_until_complete(coro)

# ── Flask app ─────────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app)

# ── Response helpers ──────────────────────────────────────────────────────────

def success(data=None, message="OK"):
    return jsonify({"status": "success", "message": message, "data": data})

def error(message, code=400):
    return jsonify({"status": "error", "message": message, "data": None}), code

# ── Serializer ────────────────────────────────────────────────────────────────

def serialize_dialog(dialog):
    entity = dialog.entity
    is_channel = isinstance(entity, Channel)
    is_group   = isinstance(entity, Chat)

    return {
        "id":            entity.id,
        "name":          dialog.name,
        "type":          "channel"    if is_channel and entity.broadcast
                         else "supergroup" if is_channel and entity.megagroup
                         else "group" if is_group
                         else "other",
        "username":      getattr(entity, "username", None),
        "members_count": getattr(entity, "participants_count", None),
        "unread_count":  dialog.unread_count,
        "is_muted":      (
                             dialog.dialog.notify_settings.mute_until is not None
                             if dialog.dialog.notify_settings else False
                         ),
    }

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    async def _check():
        return await client.is_user_authorized()

    connected = run(_check())
    return success(
        data={"authenticated": connected, "phone": PHONE},
        message="Bridge is running",
    )


@app.get("/dialogs")
def get_dialogs():
    type_filter = request.args.get("type", "all")
    limit       = int(request.args.get("limit", 200))

    async def _fetch():
        from telethon.tl.types import User
        dialogs = await client.get_dialogs(limit=limit)
        results = []
        for d in dialogs:
            entity = d.entity
            if isinstance(entity, User) and entity.bot:
                if type_filter in ("all", "bot"):
                    results.append({
                        "id":            entity.id,
                        "name":          d.name,
                        "type":          "bot",
                        "username":      getattr(entity, "username", None),
                        "members_count": None,
                        "unread_count":  d.unread_count,
                        "is_muted":      False,
                    })
            elif isinstance(entity, (Channel, Chat)):
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
    body       = request.get_json(silent=True) or {}
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
    async def _fetch():
        from telethon.tl.functions.channels import GetFullChannelRequest
        entity = await client.get_entity(channel_id)
        full   = await client(GetFullChannelRequest(entity))
        return {
            "id":            entity.id,
            "name":          entity.title,
            "username":      getattr(entity, "username", None),
            "members_count": getattr(full.full_chat, "participants_count", None),
            "description":   getattr(full.full_chat, "about", ""),
            "is_broadcast":  getattr(entity, "broadcast", False),
            "is_megagroup":  getattr(entity, "megagroup", False),
        }

    try:
        data = run(_fetch())
        return success(data=data)
    except Exception as e:
        log.exception("Error fetching channel %s", channel_id)
        return error(str(e), 500)

# ── Startup ───────────────────────────────────────────────────────────────────

def start_client():
    async def _start():
        log.info("Connecting to Telegram...")
        await client.start(phone=PHONE)
        me = await client.get_me()
        log.info("✅ Logged in as: %s (@%s)", me.first_name, me.username)

    loop.run_until_complete(_start())


if __name__ == "__main__":
    start_client()
    log.info("🚀 Bridge running on http://localhost:%s", PORT)
    app.run(host="0.0.0.0", port=PORT, debug=False)