
from fastapi import FastAPI
from fastapi.responses import FileResponse
import sqlite3
app = FastAPI(title="PT_AI Trading")
conn = sqlite3.connect("bot.db", check_same_thread=False)
conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, balance REAL DEFAULT 81418.86, profit REAL DEFAULT 74173.22, profit_per_hour REAL DEFAULT 101.7779)")
conn.commit()
@app.get("/")
def root(): return FileResponse("index.html")
@app.get("/admin")
def admin_page(): return FileResponse("admin.html")
@app.get("/health")
def health(): return {"ok": True, "brand": "PT_AI Trading"}
