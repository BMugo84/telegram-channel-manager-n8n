# Telegram Channel Manager — Project README

A personal tool to browse and leave Telegram channels/groups/bots via a web UI,
built with Python (Telethon + Flask) as a bridge and n8n as the workflow engine.

---

## How It Works

```
Browser UI (ngrok URL)
      ↕
n8n Workflows (List + Leave + UI)
      ↕
Python Bridge (Telethon/Flask) on port 5005
      ↕
Telegram User API (MTProto)
```

---

## Project Folder Structure

```
telegram-channel-manager-n8n/
├── bridge.py                    ← Main Python bridge server
├── requirements.txt             ← Python dependencies
├── .env                         ← Your credentials (never share this)
├── telegram_session.session     ← Auto-generated on first login (never share this)
└── PROJECT_README.md            ← This file
```

---

## Every Time You Want to Use the App

### Step 1 — Start the bridge
```bash
cd "C:\Users\Ben Mugo\Documents\GitHub\telegram-channel-manager-n8n"
venv\Scripts\activate
python bridge.py
```

You should see:
```
✅ Logged in as: Your Name (@username)
🚀 Bridge running on http://localhost:5005
```

### Step 2 — Make sure ngrok is running
Your ngrok tunnel must be active for the UI to be accessible. If it has reset,
update the URLs in:
- n8n Get Telegram Channels workflow → HTTP Request node URL
- n8n Leave Telegram Channel workflow → HTTP Request node URL
- n8n Telegram UI workflow → Respond to Webhook node → CHANNELS_URL and LEAVE_URL in the HTML

### Step 3 — Open the UI
```
https://perfoliate-callan-labelloid.ngrok-free.dev/webhook/telegram/ui
```

Click **Refresh** to load your channels.

---

## Switching to a Different Telegram Account

1. Stop the bridge (`Ctrl+C`)
2. Open `.env` and change the `PHONE` value to the new number (e.g. `+254...`)
3. Delete `telegram_session.session` from the project folder
4. Run `python bridge.py` again
5. Enter the OTP sent to the new account's Telegram app
6. Click Refresh in the UI — you'll now see the new account's channels

> Note: `API_ID` and `API_HASH` stay the same — you only change `PHONE`

---

## n8n Workflows

There are 3 workflows in n8n. All must be **Active** (green toggle).

### 1. Get Telegram Channels
- Trigger: `GET /webhook/telegram/channels`
- Calls bridge: `GET http://192.168.100.80:5005/dialogs`
- Returns: JSON list of all channels/groups/bots
- Nodes: Webhook → HTTP Request → Respond to Webhook

### 2. Leave Telegram Channel
- Trigger: `POST /webhook/telegram/leave`
- Calls bridge: `POST http://192.168.100.80:5005/leave`
- Body: `{ "channel_id": 1234567890 }`
- Returns: Success/error message
- Nodes: Webhook → HTTP Request → Respond to Webhook

### 3. Telegram UI
- Trigger: `GET /webhook/telegram/ui`
- Returns: The full HTML web interface
- Nodes: Webhook → Respond to Webhook (with full HTML in body)

### Required headers on all Respond to Webhook nodes:
| Header | Value |
|--------|-------|
| `Access-Control-Allow-Origin` | `*` |
| `Content-Type` | `application/json` (or `text/html` for UI) |

---

## Bridge API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Check if bridge is running and authenticated |
| GET | `/dialogs` | List all channels, groups, and bots |
| GET | `/dialogs?type=channel` | Filter by type: channel, supergroup, group, bot |
| GET | `/dialogs?limit=50` | Limit results (default 200) |
| POST | `/leave` | Leave a channel — body: `{"channel_id": 123}` |
| GET | `/channel/<id>` | Get details about a specific channel |

---

## Troubleshooting

### Bridge won't start — missing credentials
- Make sure the file is named `.env` not `env` or `.env.txt`
- Run `dir /a` in the project folder to confirm the filename
- Values should have NO quotes: `API_ID=12345678` not `API_ID="12345678"`

### Bridge starts but shows old account's channels
- You changed PHONE but forgot to delete `telegram_session.session`
- Delete the `.session` file and restart the bridge

### n8n can't connect to bridge (ECONNREFUSED)
- n8n runs in Docker — use `http://192.168.100.80:5005` not `localhost`
- Confirm the bridge is running by visiting `http://127.0.0.1:5005/health` in your browser

### UI loads but no channels appear
- Check browser console (F12) for CORS errors
- Make sure all Respond to Webhook nodes have `Access-Control-Allow-Origin: *` header
- Make sure the Webhook node is set to `Using 'Respond to Webhook' node`

### Leave button does nothing
- Check the Leave Telegram Channel workflow is Active in n8n
- Make sure the Webhook node is set to `Using 'Respond to Webhook' node` (not `Last Node`)

### ngrok URL changed
Update the URLs in 3 places:
1. n8n Get Telegram Channels → HTTP Request node
2. n8n Leave Telegram Channel → HTTP Request node  
3. n8n Telegram UI → Respond to Webhook → `CHANNELS_URL` and `LEAVE_URL` in the HTML

---

## Re-installing From Scratch

```bash
cd "C:\Users\Ben Mugo\Documents\GitHub\telegram-channel-manager-n8n"
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python bridge.py
```

---

## .env File Format

```env
API_ID=12345678
API_HASH=0123456789abcdef0123456789abcdef
PHONE=+254712345678
PORT=5005
SESSION_NAME=telegram_session
```

Get `API_ID` and `API_HASH` from: https://my.telegram.org → API development tools

---

## Security Reminders

- Never share `.env` — it contains your Telegram API credentials
- Never share `telegram_session.session` — it gives full access to your Telegram account
- The bridge only runs locally — it is never directly exposed to the internet
- ngrok exposes the n8n webhooks only, not the bridge itself
