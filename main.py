import logging
import time
from keep_alive import keep_alive

# Запускаем Flask сервер ДО запуска бота
keep_alive()

# Даем время Flask запуститься
time.sleep(2)

print("🚀 Starting Telegram Bot...")

# Импортируем и запускаем вашего бота
try:
    import Nap
    Nap.main()
except Exception as e:
    print(f"❌ Error starting bot: {e}")
    print("Bot will restart in 10 seconds...")
    time.sleep(10)
