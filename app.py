import telebot
import requests
from datetime import datetime
from flask import Flask
import threading
import os

# -------------------------------
# Environment & Bot Setup
# -------------------------------
TOKEN = os.environ.get("BOT_TOKEN")  # Store your bot token in Render environment variables
CHANNEL_USERNAME = "@txtfilegenerator"
bot = telebot.TeleBot(TOKEN)

# -------------------------------
# Flask server to keep alive
# -------------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive ✅"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

# -------------------------------
# Helper Functions
# -------------------------------

def is_member(user_id):
    """Check if user joined required channel"""
    try:
        member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ["creator", "administrator", "member"]
    except:
        return False

# Roblox lookup
def get_roblox_user(username):
    try:
        search = requests.get(f"https://users.roblox.com/v1/users/search?keyword={username}&limit=10").json()
        users = search.get("data", [])
        # Find exact username match
        user = next((u for u in users if u["name"].lower() == username.lower()), None)
        if not user:
            return None
        user_id = user["id"]

        details = requests.get(f"https://users.roblox.com/v1/users/{user_id}").json()
        friends = requests.get(f"https://friends.roblox.com/v1/users/{user_id}/friends/count").json()
        groups = requests.get(f"https://groups.roblox.com/v1/users/{user_id}/groups/roles").json()
        badges = requests.get(f"https://badges.roblox.com/v1/users/{user_id}/badges").json()

        try:
            rolimons = requests.get(f"https://www.rolimons.com/playerapi/player/{user_id}").json()
            rap = rolimons.get("rap", "Unknown")
            value = rolimons.get("value", "Unknown")
            demand = rolimons.get("demand", "Unknown")
            rap_change = rolimons.get("rapChange", 0)
        except:
            rap = value = demand = "Unknown"
            rap_change = 0

        created = datetime.fromisoformat(details["created"]).strftime("%Y-%m-%d")
        account_age_days = (datetime.utcnow() - datetime.fromisoformat(details["created"])).days

        return {
            "username": details["name"],
            "display_name": details.get("displayName", ""),
            "user_id": user_id,
            "status": "ACTIVE ✅",
            "created": created,
            "account_age_days": account_age_days,
            "description": details.get("description", "No description."),
            "badges": len(badges.get("data", [])),
            "groups": len(groups.get("data", [])),
            "friends": friends.get("count", 0),
            "rap": rap,
            "value": value,
            "demand": demand,
            "rap_change": rap_change,
            "profile_url": f"https://www.roblox.com/users/{user_id}/profile",
            "lookup_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        }
    except:
        return None

# MLBB lookup
def get_mlbb_user(player_id_or_name):
    url = f"https://api.merculet.io/mlbb/v1/player?nickname={player_id_or_name}"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        if data.get("status") != "success":
            return None
        player = data["data"]

        skins_total = player.get("skins_total", "Unknown")
        bind_status = player.get("bind_status", "Unknown")

        return {
            "username": player.get("nickname", "Unknown"),
            "player_id": player.get("user_id", "Unknown"),
            "level": player.get("level", "Unknown"),
            "rank": player.get("rank", "Unknown"),
            "heroes": player.get("heroes_count", "Unknown"),
            "guild": player.get("guild_name", "None"),
            "skins_total": skins_total,
            "bind_status": bind_status,
            "last_login": player.get("last_login", "Unknown"),
            "lookup_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        }
    except:
        return None

# -------------------------------
# Telegram Bot Handlers
# -------------------------------

@bot.message_handler(commands=["start"])
def start(message):
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
        bot.send_message(call.message.chat.id, "✨ Send me a Roblox username:")
        bot.register_next_step_handler(call.message, roblox_lookup_step)
    elif call.data == "mlbb_lookup":
        bot.send_message(call.message.chat.id, "⚔️ Send me an MLBB username or ID:")
        bot.register_next_step_handler(call.message, mlbb_lookup_step)

def roblox_lookup_step(message):
    username = message.text.strip()
    bot.send_chat_action(message.chat.id, 'typing')
    info = get_roblox_user(username)
    if not info:
        bot.reply_to(message, "❌ Roblox user not found.")
        return

    response = f"""
✨ Roblox Lookup ✨
👤 Username: {info['username']}
📛 Display Name: {info['display_name']}
🆔 User ID: {info['user_id']}
🟢 {info['status']}
📅 Created: {info['created']}
🦕 Account Age: {info['account_age_days']} days (~{info['account_age_days']//365} years)
📝 Description: {info['description']}

🏆 Achievements & Inventory:
• Badges: {info['badges']}+
• Groups: {info['groups']}

💰 Trading Stats (Rolimons):
• RAP: {info['rap']}
• Value: {info['value']}
• Demand: {info['demand']}
• RAP Change: {info['rap_change']}

👥 Social:
• Friends: {info['friends']} 👫

🔗 Profile: [View Roblox]({info['profile_url']})
🔍 Lookup at: {info['lookup_time']}
"""
    bot.send_message(message.chat.id, response, parse_mode="Markdown")

def mlbb_lookup_step(message):
    username = message.text.strip()
    bot.send_chat_action(message.chat.id, 'typing')
    info = get_mlbb_user(username)
    if not info:
        bot.reply_to(message, "❌ MLBB user not found or API failed.")
        return

    response = f"""
⚔️ MLBB Lookup ⚔️
👤 Username: {info['username']}
🆔 Player ID: {info['player_id']}
⭐ Level: {info['level']}
🏆 Rank: {info['rank']}
🛡 Heroes Count: {info['heroes']}
🎨 Total Skins: {info['skins_total']}
🔗 Bind Status: {info['bind_status']}
🏰 Guild: {info['guild']}
⏰ Last Login: {info['last_login']}
🔍 Lookup at: {info['lookup_time']}
"""
    bot.send_message(message.chat.id, response)

# -------------------------------
# Run Bot and Flask in Thread
# -------------------------------
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    print("Flask server started to keep bot alive ✅")
    print("Telegram bot running 24/7...")
    bot.infinity_polling()
