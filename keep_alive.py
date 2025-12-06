from flask import Flask
from threading import Thread
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Telegram Homework Bot is ALIVE! ✅"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    server = Thread(target=run, daemon=True)
    server.start()
    print(f"🌐 Flask server started on port {os.environ.get('PORT', 8080)}")
