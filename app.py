# bot.py
import os
import json
import threading
import logging
from datetime import datetime
from flask import Flask
import requests
from requests.adapters import HTTPAdapter, Retry
import telebot

# -------------------------
# Config
# -------------------------
TOKEN = os.environ.get("BOT_TOKEN")  # required
CHANNEL_USERNAME = "@txtfilegenerator"
MLBB_ALT_API = os.environ.get("MLBB_ALT_API")  # optional alternate MLBB API (e.g. "https://example.com/api/mlbb?query={}")
PORT = int(os.environ.get("PORT", 5000))

if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")

# -------------------------
# Logging
# -------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lookup-bot")

# -------------------------
# Requests session with retries
# -------------------------
session = requests.Session()
retries = Retry(total=3, backoff_factor=0.3, status_forcelist=[429, 500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries))
session.headers.update({"User-Agent": "LookupBot/1.0"})

# -------------------------
# Flask server (keepalive)
# -------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive ✅"

def run_flask():
    app.run(host="0.0.0.0", port=PORT)

# -------------------------
# Telegram bot
# -------------------------
bot = telebot.TeleBot(TOKEN, parse_mode=None)  # we'll set parse when sending

# -------------------------
# Helper: channel membership
# -------------------------
def is_member(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ["creator", "administrator", "member"]
    except Exception as e:
        logger.warning("is_member check failed: %s", e)
        # If bot can't access channel (not added), assume not member
        return False

# -------------------------
# Roblox lookup (robust)
# -------------------------
def get_roblox_user(username):
    """
    Returns dict with info or (None, debug) where debug is helpful text.
    """
    debug = {"attempts": []}

    try:
        # If username looks like numeric id -> try /v1/users/{id}
        if username.isdigit():
            url = f"https://users.roblox.com/v1/users/{username}"
            debug["attempts"].append({"url": url})
            r = session.get(url, timeout=8)
            if r.status_code == 200:
                details = r.json()
                user_id = details.get("id")
            else:
                debug["attempts"][-1]["status_code"] = r.status_code
                # Fall through to username endpoint
                user_id = None
        else:
            user_id = None

        # Try exact username endpoint
        if user_id is None:
            url_exact = f"https://users.roblox.com/v1/users/by-username/{username}"
            debug["attempts"].append({"url": url_exact})
            r = session.get(url_exact, timeout=8)
            if r.status_code == 200:
                details = r.json()
                user_id = details.get("id")
            else:
                debug["attempts"][-1]["status_code"] = r.status_code
                # If 404, we'll try search fallback below

        if not user_id:
            # fallback: search up to 10 results and try exact-case-insensitive match
            url_search = f"https://users.roblox.com/v1/users/search?keyword={requests.utils.quote(username)}&limit=10"
            debug["attempts"].append({"url": url_search})
            r = session.get(url_search, timeout=8)
            debug["attempts"][-1]["status_code"] = r.status_code
            if r.status_code == 200:
                data = r.json().get("data", [])
                # find exact case-insensitive username
                match = next((u for u in data if u.get("name","").lower() == username.lower()), None)
                if match:
                    user_id = match.get("id")
                    details = match
                else:
                    # If there's at least one result, pick the top result (best-effort)
                    if data:
                        match = data[0]
                        user_id = match.get("id")
                        details = match
                    else:
                        # nothing found
                        return None, debug
            else:
                return None, debug

        # At this point we have user_id; fetch details (if not full)
        if "created" not in details:
            r = session.get(f"https://users.roblox.com/v1/users/{user_id}", timeout=8)
            if r.status_code == 200:
                details = r.json()
            else:
                # still proceed with what we have
                details = details

        # other info
        # friends
        try:
            r = session.get(f"https://friends.roblox.com/v1/users/{user_id}/friends/count", timeout=8)
            friends = r.json().get("count", 0) if r.status_code == 200 else 0
        except:
            friends = 0

        # groups
        try:
            r = session.get(f"https://groups.roblox.com/v1/users/{user_id}/groups/roles", timeout=8)
            groups = len(r.json().get("data", [])) if r.status_code == 200 else 0
        except:
            groups = 0

        # badges
        try:
            r = session.get(f"https://badges.roblox.com/v1/users/{user_id}/badges", timeout=8)
            badges = len(r.json().get("data", [])) if r.status_code == 200 else 0
        except:
            badges = 0

        # rolimons (optional)
        rap = value = demand = "Unknown"
        rap_change = 0
        try:
            r = session.get(f"https://www.rolimons.com/playerapi/player/{user_id}", timeout=8)
            if r.status_code == 200:
                roli = r.json()
                rap = roli.get("rap", "Unknown")
                value = roli.get("value", "Unknown")
                demand = roli.get("demand", "Unknown")
                rap_change = roli.get("rapChange", 0)
            else:
                debug["attempts"].append({"rolimons_status": r.status_code})
        except Exception as e:
            debug["rolimons_error"] = str(e)

        # created / account age
        created_raw = details.get("created")
        if created_raw:
            try:
                created = datetime.fromisoformat(created_raw).strftime("%Y-%m-%d")
                account_age_days = (datetime.utcnow() - datetime.fromisoformat(created_raw)).days
            except Exception:
                created = created_raw
                account_age_days = "Unknown"
        else:
            created = "Unknown"
            account_age_days = "Unknown"

        result = {
            "username": details.get("name", username),
            "display_name": details.get("displayName", ""),
            "user_id": user_id,
            "created": created,
            "account_age_days": account_age_days,
            "description": details.get("description", "No description."),
            "badges": badges,
            "groups": groups,
            "friends": friends,
            "rap": rap,
            "value": value,
            "demand": demand,
            "rap_change": rap_change,
            "profile_url": f"https://www.roblox.com/users/{user_id}/profile",
            "lookup_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        }
        debug["success"] = True
        debug["user_id"] = user_id
        return result, debug

    except Exception as e:
        debug["error"] = str(e)
        logger.exception("Roblox lookup error")
        return None, debug

# -------------------------
# MLBB lookup (more robust + fallback)
# -------------------------
def get_mlbb_user(query):
    """
    Try a public MLBB endpoint (merculet) first.
    If fails and MLBB_ALT_API provided, try alt.
    Returns (result_dict or None, debug)
    """
    debug = {"attempts": []}
    try:
        # attempt 1: merculet by nickname
        try:
            url = f"https://api.merculet.io/mlbb/v1/player?nickname={requests.utils.quote(query)}"
            debug["attempts"].append({"url": url})
            r = session.get(url, timeout=10)
            debug["attempts"][-1]["status_code"] = r.status_code
            if r.status_code == 200:
                data = r.json()
                # sample format: check success key
                if isinstance(data, dict) and data.get("status") == "success" and data.get("data"):
                    player = data["data"]
                    debug["success_from"] = "merculet_nickname"
                    # map fields (best-effort)
                    return {
                        "username": player.get("nickname", "Unknown"),
                        "player_id": player.get("user_id", "Unknown"),
                        "level": player.get("level", "Unknown"),
                        "rank": player.get("rank", "Unknown"),
                        "heroes": player.get("heroes_count", "Unknown"),
                        "guild": player.get("guild_name", "None"),
                        "skins_total": player.get("skins_total", "Unknown"),
                        "bind_status": player.get("bind_status", "Unknown"),
                        "last_login": player.get("last_login", "Unknown"),
                        "lookup_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                    }, debug
        except Exception as e:
            debug["merculet_error"] = str(e)

        # If query is numeric, try the nickname endpoint with user_id param (some APIs accept id)
        if query.isdigit():
            try:
                url_id = f"https://api.merculet.io/mlbb/v1/player?uid={query}"
                debug["attempts"].append({"url": url_id})
                r = session.get(url_id, timeout=10)
                debug["attempts"][-1]["status_code"] = r.status_code
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, dict) and data.get("status") == "success" and data.get("data"):
                        player = data["data"]
                        debug["success_from"] = "merculet_id"
                        return {
                            "username": player.get("nickname", "Unknown"),
                            "player_id": player.get("user_id", "Unknown"),
                            "level": player.get("level", "Unknown"),
                            "rank": player.get("rank", "Unknown"),
                            "heroes": player.get("heroes_count", "Unknown"),
                            "guild": player.get("guild_name", "None"),
                            "skins_total": player.get("skins_total", "Unknown"),
                            "bind_status": player.get("bind_status", "Unknown"),
                            "last_login": player.get("last_login", "Unknown"),
                            "lookup_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                        }, debug
            except Exception as e:
                debug["merculet_id_error"] = str(e)

        # If alternate MLBB API provided
        if MLBB_ALT_API:
            try:
                alt_url = MLBB_ALT_API.format(requests.utils.quote(query))
                debug["attempts"].append({"url": alt_url, "note": "alt api"})
                r = session.get(alt_url, timeout=10)
                debug["attempts"][-1]["status_code"] = r.status_code
                if r.status_code == 200:
                    data = r.json()
                    # Expect alt API to return useful fields; adapt to the API you provide.
                    # We'll try to map common keys if present:
                    player = data.get("data") if isinstance(data, dict) else None
                    if not player:
                        player = data
                    # Try some possible keys
                    username = player.get("nickname") if isinstance(player, dict) else None
                    player_id = player.get("user_id") if isinstance(player, dict) else None
                    # Return best-effort
                    return {
                        "username": username or player.get("name", "Unknown") if isinstance(player, dict) else "Unknown",
                        "player_id": player_id or "Unknown",
                        "level": player.get("level", "Unknown") if isinstance(player, dict) else "Unknown",
                        "rank": player.get("rank", "Unknown") if isinstance(player, dict) else "Unknown",
                        "heroes": player.get("heroes_count", "Unknown") if isinstance(player, dict) else "Unknown",
                        "guild": player.get("guild_name", "None") if isinstance(player, dict) else "None",
                        "skins_total": player.get("skins_total", "Unknown") if isinstance(player, dict) else "Unknown",
                        "bind_status": player.get("bind_status", "Unknown") if isinstance(player, dict) else "Unknown",
                        "last_login": player.get("last_login", "Unknown") if isinstance(player, dict) else "Unknown",
                        "lookup_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                    }, debug
            except Exception as e:
                debug["alt_api_error"] = str(e)

        # nothing found
        return None, debug

    except Exception as e:
        debug["error"] = str(e)
        logger.exception("MLBB lookup error")
        return None, debug

# -------------------------
# Bot Handlers
# -------------------------
@bot.message_handler(commands=["start"])
def start_cmd(message):
    user_id = message.from_user.id
    if not is_member(user_id):
        markup = telebot.types.InlineKeyboardMarkup()
        join_btn = telebot.types.InlineKeyboardButton("✅ Join Channel", url=f"https://t.me/txtfilegenerator")
        markup.add(join_btn)
        bot.send_message(message.chat.id,
                         "❌ You must join our channel first!\nClick below to join:",
                         reply_markup=markup)
        return

    markup = telebot.types.InlineKeyboardMarkup()
    roblox_btn = telebot.types.InlineKeyboardButton("🎮 Roblox Lookup", callback_data="roblox_lookup")
    mlbb_btn = telebot.types.InlineKeyboardButton("⚔️ MLBB Lookup", callback_data="mlbb_lookup")
    markup.add(roblox_btn, mlbb_btn)

    bot.send_message(message.chat.id,
                     f"👋 Hello {message.from_user.first_name}!\nWelcome to the Lookup Bot!\nChoose an option:",
                     reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    if not is_member(call.from_user.id):
        markup = telebot.types.InlineKeyboardMarkup()
        join_btn = telebot.types.InlineKeyboardButton("✅ Join Channel", url=f"https://t.me/txtfilegenerator")
        markup.add(join_btn)
        bot.send_message(call.message.chat.id, "❌ You must join the channel first!", reply_markup=markup)
        return

    if call.data == "roblox_lookup":
        bot.send_message(call.message.chat.id, "✨ Send me a Roblox username or ID:")
        bot.register_next_step_handler(call.message, roblox_lookup_step)
    elif call.data == "mlbb_lookup":
        bot.send_message(call.message.chat.id, "⚔️ Send me an MLBB username or ID:")
        bot.register_next_step_handler(call.message, mlbb_lookup_step)

@bot.message_handler(commands=["debug"])
def debug_cmd(message):
    # /debug service query
    # Example: /debug roblox SoggyWafffIe
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(message, "Usage: /debug <roblox|mlbb> <query>")
        return
    service = parts[1].lower()
    query = parts[2].strip()
    bot.send_chat_action(message.chat.id, 'typing')
    if service == "roblox":
        _, debug = get_roblox_user(query)
        bot.reply_to(message, f"Roblox debug:\n```{json.dumps(debug, indent=2)}```", parse_mode="Markdown")
    elif service == "mlbb":
        _, debug = get_mlbb_user(query)
        bot.reply_to(message, f"MLBB debug:\n```{json.dumps(debug, indent=2)}```", parse_mode="Markdown")
    else:
        bot.reply_to(message, "Service must be 'roblox' or 'mlbb'")

def roblox_lookup_step(message):
    query = message.text.strip()
    bot.send_chat_action(message.chat.id, 'typing')
    info, debug = get_roblox_user(query)
    if not info:
        # show helpful message including attempts
        msg = "❌ Roblox user not found.\nDebug info:\n"
        msg += json.dumps(debug, indent=2)
        bot.reply_to(message, msg)
        return

    text = (
        f"✨ Roblox Lookup ✨\n"
        f"👤 Username: {info['username']}\n"
        f"📛 Display Name: {info.get('display_name','')}\n"
        f"🆔 User ID: {info['user_id']}\n"
        f"📅 Created: {info['created']}\n"
        f"🦕 Account Age: {info['account_age_days']} days\n"
        f"📝 Description: {info['description']}\n\n"
        f"🏆 Achievements & Inventory:\n"
        f"• Badges: {info['badges']}\n"
        f"• Groups: {info['groups']}\n\n"
        f"💰 Trading Stats (Rolimons):\n"
        f"• RAP: {info['rap']}\n"
        f"• Value: {info['value']}\n"
        f"• Demand: {info['demand']}\n"
        f"• RAP Change: {info['rap_change']}\n\n"
        f"👥 Friends: {info['friends']}\n"
        f"🔗 Profile: {info['profile_url']}\n"
        f"🔍 Lookup at: {info['lookup_time']}"
    )
    # use Markdown
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

def mlbb_lookup_step(message):
    query = message.text.strip()
    bot.send_chat_action(message.chat.id, 'typing')
    info, debug = get_mlbb_user(query)
    if not info:
        msg = "❌ MLBB user not found or API failed.\nDebug info:\n"
        msg += json.dumps(debug, indent=2)
        bot.reply_to(message, msg)
        return

    text = (
        f"⚔️ MLBB Lookup ⚔️\n"
        f"👤 Username: {info.get('username')}\n"
        f"🆔 Player ID: {info.get('player_id')}\n"
        f"⭐ Level: {info.get('level')}\n"
        f"🏆 Rank: {info.get('rank')}\n"
        f"🛡 Heroes Count: {info.get('heroes')}\n"
        f"🎨 Total Skins: {info.get('skins_total')}\n"
        f"🔗 Bind Status: {info.get('bind_status')}\n"
        f"🏰 Guild: {info.get('guild')}\n"
        f"⏰ Last Login: {info.get('last_login')}\n"
        f"🔍 Lookup at: {info.get('lookup_time')}"
    )
    bot.send_message(message.chat.id, text)

# -------------------------
# Start
# -------------------------
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    logger.info("Flask keepalive started")
    logger.info("Starting Telegram bot polling...")
    bot.infinity_polling(timeout=60, long_polling_timeout=600)
