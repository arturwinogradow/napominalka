from flask import Flask
from threading import Thread
import time

app = Flask(__name__)

@app.route('/')
def home():
    return "Telegram Bot is running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    server = Thread(target=run)
    server.daemon = True
    server.start()

if __name__ == '__main__':
    keep_alive()
    # Далее будет запущен ваш бот
