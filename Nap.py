import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, \
    ConversationHandler
from datetime import datetime, timedelta
import sqlite3
import pytz  # Добавляем эту библиотеку!

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8350539182:AAHvgtrMJDAzRJIMVaTFPI240JFX71K5qE4"

# Указываем правильный часовой пояс (для России)
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# Состояния для ConversationHandler
TITLE, START_TIME, END_TIME, REMIND_COUNT, CUSTOM_PERCENTS = range(5)

REMINDER_PRESETS = {
    '1': [50],
    '2': [30, 60],
    '3': [20, 40, 60],
    '4': [15, 30, 45, 60],
    '5': [10, 20, 40, 50, 60]
}


def init_db():
    conn = sqlite3.connect('tasks.db', check_same_thread=False)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            start_time DATETIME NOT NULL,
            end_time DATETIME NOT NULL,
            reminder_percents TEXT NOT NULL,
            is_completed BOOLEAN DEFAULT FALSE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()


def save_task(user_id, title, start_time, end_time, reminder_percents):
    conn = sqlite3.connect('tasks.db', check_same_thread=False)
    cur = conn.cursor()
    percents_str = ",".join(map(str, reminder_percents))
    cur.execute('''
        INSERT INTO tasks (user_id, title, start_time, end_time, reminder_percents)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, title, start_time.isoformat(), end_time.isoformat(), percents_str))
    task_id = cur.lastrowid
    conn.commit()
    conn.close()
    return task_id


def get_user_tasks(user_id):
    conn = sqlite3.connect('tasks.db', check_same_thread=False)
    cur = conn.cursor()
    cur.execute('''
        SELECT id, title, start_time, end_time, reminder_percents FROM tasks
        WHERE user_id = ? AND is_completed = FALSE
        ORDER BY start_time
    ''', (user_id,))
    tasks = cur.fetchall()
    conn.close()
    return tasks


def delete_task(task_id, user_id):
    conn = sqlite3.connect('tasks.db', check_same_thread=False)
    cur = conn.cursor()
    cur.execute('DELETE FROM tasks WHERE id = ? AND user_id = ?', (task_id, user_id))
    conn.commit()
    conn.close()


# Получаем текущее время с правильным часовым поясом
def get_current_time():
    return datetime.now(MOSCOW_TZ)


# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    keyboard = [
        [KeyboardButton("Добавить дело"), KeyboardButton("Мои дела")],
        [KeyboardButton("Удалить дело"), KeyboardButton("Тест напоминания")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    current_time = get_current_time()
    await update.message.reply_html(
        rf"Привет {user.mention_html()}! Сейчас время: {current_time.strftime('%d.%m.%Y %H:%M:%S')}",
        reply_markup=reply_markup
    )


# Показ списка дел
async def show_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tasks = get_user_tasks(user_id)

    if not tasks:
        await update.message.reply_text("У вас пока нет активных дел.")
        return

    tasks_text = "📋 Ваши активные дела:\n\n"
    current_time = get_current_time()

    for task in tasks:
        task_id, title, start_time, end_time, percents = task
        start_dt = datetime.fromisoformat(start_time).replace(tzinfo=MOSCOW_TZ)
        end_dt = datetime.fromisoformat(end_time).replace(tzinfo=MOSCOW_TZ)

        if current_time > end_dt:
            status = "❌ Время вышло"
        elif current_time >= start_dt:
            status = "🟡 Выполняется"
        else:
            status = "⏳ Ожидание"

        tasks_text += f"• {title}\n"
        tasks_text += f"  ⏰ {start_dt.strftime('%d.%m.%Y %H:%M')} - {end_dt.strftime('%H:%M')}\n"
        tasks_text += f"  🔔 Напоминаний: {len(percents.split(','))}\n"
        tasks_text += f"  📊 Статус: {status}\n"
        tasks_text += f"  🆔 ID: {task_id}\n\n"

    await update.message.reply_text(tasks_text)


# Функция для удаления дел
async def delete_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tasks = get_user_tasks(user_id)

    if not tasks:
        await update.message.reply_text("У вас нет активных дел для удаления.")
        return

    keyboard = []
    for task in tasks:
        task_id, title, start_time, end_time, percents = task
        start_dt = datetime.fromisoformat(start_time).replace(tzinfo=MOSCOW_TZ)
        end_dt = datetime.fromisoformat(end_time).replace(tzinfo=MOSCOW_TZ)

        button_text = f"{title} ({start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')})"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"delete_{task_id}")])

    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="delete_cancel")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите дело для удаления:", reply_markup=reply_markup)


# Обработка удаления дела
async def process_delete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "delete_cancel":
        await query.edit_message_text("❌ Удаление отменено.")
        return

    task_id = int(query.data.split('_')[1])
    user_id = query.from_user.id

    tasks = get_user_tasks(user_id)
    task_title = ""
    for task in tasks:
        if task[0] == task_id:
            task_title = task[1]
            break

    if task_title:
        delete_task(task_id, user_id)
        await query.edit_message_text(f"✅ Дело '{task_title}' успешно удалено!")
    else:
        await query.edit_message_text("❌ Дело не найдено.")


# Тестовая функция для проверки напоминаний
async def test_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестовая функция - отправляет напоминание через 30 секунд"""
    user_id = update.effective_user.id
    test_time = get_current_time() + timedelta(seconds=30)

    context.job_queue.run_once(
        send_test_reminder,
        when=test_time,
        data={'user_id': user_id},
        name=f"test_{user_id}"
    )

    await update.message.reply_text(
        f"🧪 Тестовое напоминание запланировано на {test_time.strftime('%H:%M:%S')}\n"
        f"Оно придет через 30 секунд для проверки работы бота."
    )


async def send_test_reminder(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data
    user_id = data['user_id']

    current_time = get_current_time()
    message = (
        "🧪 **ТЕСТОВОЕ НАПОМИНАНИЕ**\n"
        "Если вы видите это сообщение, значит бот работает корректно!\n"
        f"✅ Время отправки: {current_time.strftime('%H:%M:%S')}\n"
        "Часовой пояс: Europe/Moscow"
    )

    try:
        await context.bot.send_message(chat_id=user_id, text=message)
        logger.info(f"✅ Тестовое напоминание отправлено пользователю {user_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки тестового напоминания: {e}")


# Начало процесса добавления дела
async def add_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current_time = get_current_time()
    await update.message.reply_text(
        "✏️ Введите название дела:\n"
        f"🕒 Текущее время: {current_time.strftime('%d.%m.%Y %H:%M:%S')}\n"
        f"🌍 Часовой пояс: Moscow"
    )
    return TITLE


# Обработка названия дела
async def process_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['title'] = update.message.text
    current_time = get_current_time()
    await update.message.reply_text(
        "📅 Введите дату и время начала (в формате ДД.ММ.ГГГГ ЧЧ:ММ):\n"
        f"Текущее время: {current_time.strftime('%d.%m.%Y %H:%M:%S')}\n"
        "Пример: 06.11.2025 19:30"
    )
    return START_TIME


# Обработка времени начала
async def process_start_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    try:
        # Создаем naive datetime и затем добавляем часовой пояс
        start_dt_naive = datetime.strptime(text, '%d.%m.%Y %H:%M')
        start_dt = MOSCOW_TZ.localize(start_dt_naive)

        current_time = get_current_time()
        time_difference = (start_dt - current_time).total_seconds()

        if time_difference < 120:  # 2 минуты
            await update.message.reply_text(
                f"❌ Время начала должно быть минимум на 2 минуты позже текущего!\n"
                f"Вы указали: {start_dt.strftime('%d.%m.%Y %H:%M:%S')}\n"
                f"Сейчас: {current_time.strftime('%d.%m.%Y %H:%M:%S')}\n"
                f"Введите время начала заново:"
            )
            return START_TIME

        context.user_data['start_time'] = start_dt
        await update.message.reply_text("📅 Введите дату и время окончания (в формате ДД.ММ.ГГГГ ЧЧ:ММ):")
        return END_TIME
    except ValueError:
        await update.message.reply_text("❌ Неверный формат даты. Попробуйте еще раз (ДД.ММ.ГГГГ ЧЧ:ММ):")
        return START_TIME


# Обработка времени окончания
async def process_end_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    try:
        end_dt_naive = datetime.strptime(text, '%d.%m.%Y %H:%M')
        end_dt = MOSCOW_TZ.localize(end_dt_naive)
        start_dt = context.user_data['start_time']

        if end_dt <= start_dt:
            await update.message.reply_text("❌ Время окончания должно быть позже времени начала. Попробуйте еще раз:")
            return END_TIME

        total_minutes = (end_dt - start_dt).total_seconds() / 60
        if total_minutes < 10:
            await update.message.reply_text("❌ Временной интервал должен быть не менее 10 минут. Попробуйте еще раз:")
            return END_TIME

        context.user_data['end_time'] = end_dt

        keyboard = [
            [InlineKeyboardButton("1 напоминание (50%)", callback_data="rem_1")],
            [InlineKeyboardButton("2 напоминания (30%, 60%)", callback_data="rem_2")],
            [InlineKeyboardButton("3 напоминания (20%, 40%, 60%)", callback_data="rem_3")],
            [InlineKeyboardButton("4 напоминания (15%, 30%, 45%, 60%)", callback_data="rem_4")],
            [InlineKeyboardButton("5 напоминаний (10%, 20%, 40%, 50%, 60%)", callback_data="rem_5")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"⏱️ Общее время: {total_minutes:.0f} минут\n"
            "🔔 Выберите шаблон напоминаний:",
            reply_markup=reply_markup
        )
        return REMIND_COUNT

    except ValueError:
        await update.message.reply_text("❌ Неверный формат даты. Попробуйте еще раз (ДД.ММ.ГГГГ ЧЧ:ММ):")
        return END_TIME


# Обработка выбора количества напоминаний
async def process_reminder_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    choice = query.data
    preset_key = choice.split('_')[1]
    context.user_data['reminder_percents'] = REMINDER_PRESETS[preset_key]

    return await save_final_task(update, context)


# Финальное сохранение задачи
async def save_final_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    title = context.user_data['title']
    start_time = context.user_data['start_time']
    end_time = context.user_data['end_time']
    reminder_percents = context.user_data['reminder_percents']

    task_id = save_task(user_id, title, start_time, end_time, reminder_percents)
    scheduled_count = await schedule_reminders(task_id, user_id, title, start_time, end_time, reminder_percents,
                                               context)

    reminders_text = "📅 Расписание напоминаний:\n"
    total_duration = end_time - start_time
    current_time = get_current_time()

    for percent in reminder_percents:
        reminder_time = start_time + (total_duration * (percent / 100))
        time_until_reminder = reminder_time - current_time
        seconds_until = int(time_until_reminder.total_seconds())

        status = "✅ Запланировано" if reminder_time > current_time else "❌ Уже прошло"
        reminders_text += f"• {percent}% - {reminder_time.strftime('%H:%M:%S')} (через {seconds_until} сек) - {status}\n"

    success_text = (
        f"✅ Отлично! Дело '{title}' запланировано!\n"
        f"⏰ С {start_time.strftime('%d.%m.%Y %H:%M:%S')} по {end_time.strftime('%d.%m.%Y %H:%M:%S')}\n"
        f"🔔 Напоминаний: {scheduled_count}/{len(reminder_percents)}\n"
        f"{reminders_text}"
        f"🌍 Часовой пояс: Moscow"
    )

    await query.edit_message_text(success_text)
    return ConversationHandler.END


# Функция для планирования напоминаний
async def schedule_reminders(task_id, user_id, title, start_time, end_time, reminder_percents,
                             context: ContextTypes.DEFAULT_TYPE):
    total_duration = end_time - start_time
    now = get_current_time()
    scheduled_count = 0

    logger.info(f"🔔 Начинаем планирование напоминаний для задачи {task_id}")

    for percent in reminder_percents:
        reminder_time = start_time + (total_duration * (percent / 100))
        time_until = (reminder_time - now).total_seconds()

        if time_until > 5:
            context.job_queue.run_once(
                send_reminder,
                when=reminder_time,
                data={
                    'user_id': user_id,
                    'task_id': task_id,
                    'title': title,
                    'start_time': start_time,
                    'end_time': end_time,
                    'percent': percent
                },
                name=f"task_{task_id}_percent_{percent}"
            )
            logger.info(
                f"✅ Запланировано напоминание для задачи {task_id} на {reminder_time} ({percent}%), через {time_until:.0f} сек")
            scheduled_count += 1
        else:
            logger.warning(
                f"❌ Время напоминания {reminder_time} уже прошло или скоро наступит (через {time_until:.0f} сек), не планируем")

    logger.info(f"📊 Итог планирования: {scheduled_count}/{len(reminder_percents)} напоминаний запланировано")
    return scheduled_count


# Функция отправки напоминания
async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data
    user_id = data['user_id']
    title = data['title']
    percent = data['percent']
    start_time = data['start_time']
    end_time = data['end_time']

    total_duration = end_time - start_time
    time_passed = total_duration * (percent / 100)
    total_minutes = int(total_duration.total_seconds() / 60)
    passed_minutes = int(time_passed.total_seconds() / 60)

    current_time = get_current_time()
    message = (
        f"⏰ Напоминание!\n"
        f"Прошло уже {passed_minutes} мин. из {total_minutes} ({percent}%), пора приступать к выполнению дела:\n"
        f"**{title}**\n"
        f"🕒 Время: {current_time.strftime('%H:%M:%S')}\n"
        f"🌍 Часовой пояс: Moscow"
    )

    try:
        await context.bot.send_message(chat_id=user_id, text=message)
        logger.info(f"✅ ОТПРАВЛЕНО напоминание пользователю {user_id} для дела '{title}' ({percent}%)")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки напоминания: {e}")


# Отмена диалога
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Диалог отменен.')
    return ConversationHandler.END


def main():
    # Установите библиотеку pytz если ее нет: pip install pytz
    init_db()

    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Добавить дело$"), add_task_start)],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_title)],
            START_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_start_time)],
            END_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_end_time)],
            REMIND_COUNT: [CallbackQueryHandler(process_reminder_choice, pattern='^rem_')],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.Regex("^Мои дела$"), show_tasks))
    application.add_handler(MessageHandler(filters.Regex("^Удалить дело$"), delete_task_start))
    application.add_handler(MessageHandler(filters.Regex("^Тест напоминания$"), test_reminder))
    application.add_handler(CallbackQueryHandler(process_delete_task, pattern='^delete_'))

    logger.info("Бот запущен с московским часовым поясом...")
    print("=" * 50)
    print("🤖 БОТ ЗАПУЩЕН! Часовой пояс: Moscow")
    print("• 'Тест напоминания' - проверка работы (30 сек)")
    print("• 'Удалить дело' - удаление существующих дел")
    print("=" * 50)

    application.run_polling()


if __name__ == '__main__':
    main()