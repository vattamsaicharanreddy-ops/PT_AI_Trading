
import os, sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes
BOT_TOKEN = os.getenv("BOT_TOKEN", "PASTE_TOKEN_HERE")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://your-app.onrender.com")
conn = sqlite3.connect("bot.db", check_same_thread=False)
conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, balance REAL DEFAULT 81418.86, profit REAL DEFAULT 74173.22, profit_per_hour REAL DEFAULT 101.7779)")
conn.commit()
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name or f"user_{uid}"
    conn.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)", (uid, username))
    conn.commit()
    kb = [[InlineKeyboardButton("🚀 Open PT_AI Trading", web_app=WebAppInfo(url=WEBAPP_URL))]]
    await update.message.reply_text(f"Welcome to PT_AI Trading, {username}!", reply_markup=InlineKeyboardMarkup(kb))
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()
if __name__ == "__main__": main()
