import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, \
    ConversationHandler
from datetime import datetime, timedelta
import sqlite3

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8350539182:AAHvgtrMJDAzRJIMVaTFPI240JFX71K5qE4"


# Простое решение для московского времени (UTC+3)
def get_current_time():
    return datetime.utcnow() + timedelta(hours=3)


def convert_to_moscow_time(naive_dt):
    """Конвертирует наивное datetime в московское время"""
    return naive_dt + timedelta(hours=3)


# Состояния для ConversationHandler
TITLE, START_TIME, END_TIME, REMIND_TYPE, REMIND_INTERVAL, REMIND_COUNT = range(6)

REMINDER_PRESETS = {
    '1': [50],
    '2': [30, 60],
    '3': [20, 40, 60],
    '4': [15, 30, 45, 60],
    '5': [10, 20, 40, 50, 60]
}

# Настройки для интервальных напоминаний
INTERVAL_PRESETS = {
    '30min': 30,
    '1hour': 60,
    '2hours': 120,
    '3hours': 180,
    '6hours': 360,
    '12hours': 720,
    '1day': 1440
}


def init_db():
    conn = sqlite3.connect('tasks.db', check_same_thread=False)
    cur = conn.cursor()

    # Таблица для дел с временными интервалами
    cur.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            start_time DATETIME NOT NULL,
            end_time DATETIME NOT NULL,
            reminder_percents TEXT NOT NULL,
            reminder_type TEXT DEFAULT 'percent',
            reminder_interval INTEGER,
            is_completed BOOLEAN DEFAULT FALSE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Таблица для дневника дел (простые записи)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS diary_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            reminder_enabled BOOLEAN DEFAULT FALSE,
            reminder_time DATETIME,
            reminder_interval INTEGER,
            is_completed BOOLEAN DEFAULT FALSE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()


def update_db_schema():
    conn = sqlite3.connect('tasks.db', check_same_thread=False)
    cur = conn.cursor()

    # Проверяем существование колонки reminder_type
    cur.execute("PRAGMA table_info(tasks)")
    columns = [column[1] for column in cur.fetchall()]

    if 'reminder_type' not in columns:
        print("Добавляем колонку reminder_type в таблицу tasks...")
        cur.execute('ALTER TABLE tasks ADD COLUMN reminder_type TEXT DEFAULT "percent"')
        conn.commit()

    if 'reminder_interval' not in columns:
        print("Добавляем колонку reminder_interval в таблицу tasks...")
        cur.execute('ALTER TABLE tasks ADD COLUMN reminder_interval INTEGER')
        conn.commit()

    conn.close()


def save_task(user_id, title, start_time, end_time, reminder_percents, reminder_type='percent', reminder_interval=None):
    conn = sqlite3.connect('tasks.db', check_same_thread=False)
    cur = conn.cursor()
    percents_str = ",".join(map(str, reminder_percents))
    cur.execute('''
        INSERT INTO tasks (user_id, title, start_time, end_time, reminder_percents, reminder_type, reminder_interval)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, title, start_time.isoformat(), end_time.isoformat(), percents_str, reminder_type, reminder_interval))
    task_id = cur.lastrowid
    conn.commit()
    conn.close()
    return task_id


def save_diary_entry(user_id, content, reminder_enabled=False, reminder_time=None, reminder_interval=None):
    conn = sqlite3.connect('tasks.db', check_same_thread=False)
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO diary_entries (user_id, content, reminder_enabled, reminder_time, reminder_interval)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, content, reminder_enabled,
          reminder_time.isoformat() if reminder_time else None,
          reminder_interval))
    entry_id = cur.lastrowid
    conn.commit()
    conn.close()
    return entry_id


def get_user_tasks(user_id):
    conn = sqlite3.connect('tasks.db', check_same_thread=False)
    cur = conn.cursor()
    cur.execute('''
        SELECT id, title, start_time, end_time, reminder_percents, reminder_type, reminder_interval FROM tasks
        WHERE user_id = ? AND is_completed = FALSE
        ORDER BY start_time
    ''', (user_id,))
    tasks = cur.fetchall()
    conn.close()
    return tasks


def get_diary_entries(user_id):
    conn = sqlite3.connect('tasks.db', check_same_thread=False)
    cur = conn.cursor()
    cur.execute('''
        SELECT id, content, reminder_enabled, reminder_time, reminder_interval, is_completed 
        FROM diary_entries 
        WHERE user_id = ? AND is_completed = FALSE
        ORDER BY created_at DESC
    ''', (user_id,))
    entries = cur.fetchall()
    conn.close()
    return entries


def delete_task(task_id, user_id):
    conn = sqlite3.connect('tasks.db', check_same_thread=False)
    cur = conn.cursor()
    cur.execute('DELETE FROM tasks WHERE id = ? AND user_id = ?', (task_id, user_id))
    conn.commit()
    conn.close()


def delete_diary_entry(entry_id, user_id):
    conn = sqlite3.connect('tasks.db', check_same_thread=False)
    cur = conn.cursor()
    cur.execute('DELETE FROM diary_entries WHERE id = ? AND user_id = ?', (entry_id, user_id))
    conn.commit()
    conn.close()


# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    keyboard = [
        [KeyboardButton("Добавить дело"), KeyboardButton("Мои дела")],
        [KeyboardButton("Удалить дело"), KeyboardButton("Дневник дел")],
        [KeyboardButton("Добавить в дневник"), KeyboardButton("Тест напоминания")]
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
        task_id, title, start_time, end_time, percents, rem_type, rem_interval = task
        start_dt = datetime.fromisoformat(start_time)
        end_dt = datetime.fromisoformat(end_time)

        if current_time > end_dt:
            status = "❌ Время вышло"
        elif current_time >= start_dt:
            status = "🟡 Выполняется"
        else:
            status = "⏳ Ожидание"

        tasks_text += f"• {title}\n"
        tasks_text += f"  ⏰ {start_dt.strftime('%d.%m.%Y %H:%M')} - {end_dt.strftime('%H:%M')}\n"

        if rem_type == 'interval' and rem_interval:
            interval_hours = rem_interval / 60
            tasks_text += f"  🔔 Интервал: каждые {interval_hours:.0f} ч\n"
        else:
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
        task_id, title, start_time, end_time, percents, rem_type, rem_interval = task
        start_dt = datetime.fromisoformat(start_time)
        end_dt = datetime.fromisoformat(end_time)

        button_text = f"{title} ({start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')})"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"delete_task_{task_id}")])

    # Добавляем кнопку для удаления записей из дневника
    diary_entries = get_diary_entries(user_id)
    if diary_entries:
        keyboard.append([InlineKeyboardButton("📔 Удалить из дневника", callback_data="delete_diary_mode")])

    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="delete_cancel")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите дело для удаления:", reply_markup=reply_markup)


# Показ дневника дел
async def show_diary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    entries = get_diary_entries(user_id)

    if not entries:
        await update.message.reply_text("📔 Ваш дневник дел пуст.")
        return

    diary_text = "📔 Ваш дневник дел:\n\n"

    for entry in entries:
        entry_id, content, reminder_enabled, reminder_time, reminder_interval, is_completed = entry

        diary_text += f"• {content}\n"
        diary_text += f"  🆔 ID: {entry_id}\n"

        if reminder_enabled and reminder_time:
            rem_time = datetime.fromisoformat(reminder_time)
            diary_text += f"  🔔 Напоминание: {rem_time.strftime('%d.%m.%Y %H:%M')}\n"

        if reminder_interval:
            interval_hours = reminder_interval / 60
            diary_text += f"  ⏱️ Повтор: каждые {interval_hours:.1f} ч.\n"

        diary_text += "\n"

    await update.message.reply_text(diary_text)


# Добавление записи в дневник
async def add_diary_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📝 Введите запись для дневника:\n"
        "Это может быть любая задача или мысль, которую вы хотите записать."
    )
    return "DIARY_CONTENT"


# Обработка содержимого дневника
async def process_diary_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['diary_content'] = update.message.text

    keyboard = [
        [InlineKeyboardButton("✅ Да, с напоминанием", callback_data="diary_reminder_yes")],
        [InlineKeyboardButton("❌ Нет, просто запись", callback_data="diary_reminder_no")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Хотите установить напоминание для этой записи?",
        reply_markup=reply_markup
    )
    return "DIARY_REMINDER"


# Обработка выбора напоминания для дневника
async def process_diary_reminder_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    choice = query.data

    if choice == "diary_reminder_no":
        # Сохраняем без напоминания
        user_id = query.from_user.id
        content = context.user_data['diary_content']

        entry_id = save_diary_entry(user_id, content)

        await query.edit_message_text(f"✅ Запись добавлена в дневник:\n\n{content}")
        return ConversationHandler.END

    else:
        # Показываем варианты интервалов для напоминаний
        keyboard = []
        for key, minutes in INTERVAL_PRESETS.items():
            hours = minutes / 60
            if hours < 1:
                button_text = f"Каждые {minutes} мин"
            else:
                button_text = f"Каждые {hours:.0f} ч" if hours.is_integer() else f"Каждые {hours:.1f} ч"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"diary_interval_{key}")])

        keyboard.append([InlineKeyboardButton("❌ Без повтора", callback_data="diary_interval_none")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "Выберите интервал напоминаний:",
            reply_markup=reply_markup
        )
        return "DIARY_INTERVAL"


# Обработка выбора интервала для дневника
async def process_diary_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    choice = query.data

    if choice == "diary_interval_none":
        # Одно напоминание без повтора
        context.user_data['diary_interval'] = None
        await query.edit_message_text(
            "⏰ Введите дату и время напоминания (в формате ДД.ММ.ГГГГ ЧЧ:ММ):\n"
            "Пример: 06.11.2025 19:30"
        )
        return "DIARY_TIME"
    else:
        # Периодическое напоминание
        interval_key = choice.split('_')[-1]
        context.user_data['diary_interval'] = INTERVAL_PRESETS[interval_key]

        await query.edit_message_text(
            "⏰ Введите дату и время первого напоминания (в формате ДД.ММ.ГГГГ ЧЧ:ММ):\n"
            "Пример: 06.11.2025 19:30"
        )
        return "DIARY_TIME"


# Обработка времени напоминания для дневника
async def process_diary_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    try:
        reminder_dt_naive = datetime.strptime(text, '%d.%m.%Y %H:%M')
        reminder_dt = convert_to_moscow_time(reminder_dt_naive)

        current_time = get_current_time()
        time_difference = (reminder_dt - current_time).total_seconds()

        if time_difference < 60:  # 1 минута
            await update.message.reply_text(
                "❌ Время напоминания должно быть минимум на 1 минуту позже текущего!\n"
                "Введите время заново:"
            )
            return "DIARY_TIME"

        # Сохраняем запись
        user_id = update.effective_user.id
        content = context.user_data['diary_content']
        interval = context.user_data.get('diary_interval')

        entry_id = save_diary_entry(user_id, content, True, reminder_dt, interval)

        # Планируем напоминание
        await schedule_diary_reminder(entry_id, user_id, content, reminder_dt, interval, context)

        success_text = f"✅ Запись добавлена в дневник с напоминанием!\n\n{content}\n"
        success_text += f"⏰ Первое напоминание: {reminder_dt.strftime('%d.%m.%Y %H:%M')}\n"

        if interval:
            interval_hours = interval / 60
            success_text += f"🔄 Повтор: каждые {interval_hours:.1f} ч."
        else:
            success_text += "🔄 Повтор: однократно"

        await update.message.reply_text(success_text)
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("❌ Неверный формат даты. Попробуйте еще раз (ДД.ММ.ГГГГ ЧЧ:ММ):")
        return "DIARY_TIME"


# Планирование напоминаний для дневника
async def schedule_diary_reminder(entry_id, user_id, content, reminder_time, interval_minutes, context):
    current_time = get_current_time()
    time_until = (reminder_time - current_time).total_seconds()

    if time_until > 5:
        # Первое напоминание
        context.job_queue.run_once(
            send_diary_reminder,
            when=time_until,
            data={
                'user_id': user_id,
                'entry_id': entry_id,
                'content': content,
                'interval_minutes': interval_minutes
            },
            name=f"diary_{entry_id}_single"
        )
        logger.info(f"✅ Запланировано напоминание дневника {entry_id} через {time_until:.0f} сек")

    if interval_minutes:
        # Периодические напоминания (начинаются после первого)
        first_repeat_seconds = time_until + (interval_minutes * 60)

        if first_repeat_seconds > 5:
            context.job_queue.run_repeating(
                send_diary_reminder,
                interval=interval_minutes * 60,  # в секундах
                first=first_repeat_seconds,
                data={
                    'user_id': user_id,
                    'entry_id': entry_id,
                    'content': content,
                    'interval_minutes': interval_minutes
                },
                name=f"diary_{entry_id}_repeat"
            )
            logger.info(f"✅ Запланирован повтор дневника {entry_id} каждые {interval_minutes} мин")


# Отправка напоминания для дневника
async def send_diary_reminder(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data
    user_id = data['user_id']
    content = data['content']
    entry_id = data['entry_id']
    interval_minutes = data['interval_minutes']

    current_time = get_current_time()

    if interval_minutes:
        message = (
            f"📔 Напоминание из дневника!\n\n"
            f"**{content}**\n\n"
            f"🔄 Следующее напоминание через {interval_minutes} мин.\n"
            f"⏰ Текущее время: {current_time.strftime('%H:%M:%S')}"
        )
    else:
        message = (
            f"📔 Напоминание из дневника!\n\n"
            f"**{content}**\n\n"
            f"⏰ Время: {current_time.strftime('%H:%M:%S')}"
        )

    try:
        await context.bot.send_message(chat_id=user_id, text=message)
        logger.info(f"✅ ОТПРАВЛЕНО напоминание дневника пользователю {user_id}")

        # Если это однократное напоминание, помечаем как выполненное
        if not interval_minutes and "single" in job.name:
            conn = sqlite3.connect('tasks.db', check_same_thread=False)
            cur = conn.cursor()
            cur.execute('UPDATE diary_entries SET is_completed = TRUE WHERE id = ?', (entry_id,))
            conn.commit()
            conn.close()

    except Exception as e:
        logger.error(f"❌ Ошибка отправки напоминания дневника: {e}")


# Обработка удаления
async def process_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "delete_cancel":
        await query.edit_message_text("❌ Удаление отменено.")
        return

    elif query.data == "delete_diary_mode":
        # Переходим в режим удаления записей дневника
        user_id = query.from_user.id
        entries = get_diary_entries(user_id)

        if not entries:
            await query.edit_message_text("❌ В дневнике нет записей для удаления.")
            return

        keyboard = []
        for entry in entries:
            entry_id, content, reminder_enabled, reminder_time, reminder_interval, is_completed = entry
            # Обрезаем длинный текст для кнопки
            button_text = content[:30] + "..." if len(content) > 30 else content
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"delete_diary_{entry_id}")])

        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="delete_cancel")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Выберите запись из дневника для удаления:", reply_markup=reply_markup)
        return

    elif query.data.startswith("delete_task_"):
        task_id = int(query.data.split('_')[2])
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

    elif query.data.startswith("delete_diary_"):
        entry_id = int(query.data.split('_')[2])
        user_id = query.from_user.id

        entries = get_diary_entries(user_id)
        entry_content = ""
        for entry in entries:
            if entry[0] == entry_id:
                entry_content = entry[1]
                break

        if entry_content:
            delete_diary_entry(entry_id, user_id)
            await query.edit_message_text(f"✅ Запись из дневника удалена!\n\n{entry_content}")
        else:
            await query.edit_message_text("❌ Запись не найдена.")


# Начало процесса добавления дела
async def add_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current_time = get_current_time()
    await update.message.reply_text(
        "✏️ Введите название дела:\n"
        f"🕒 Текущее время: {current_time.strftime('%d.%m.%Y %H:%M:%S')}\n"
        f"🌍 Часовой пояс: Moscow (UTC+3)"
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
        # Создаем naive datetime и затем конвертируем в московское время
        start_dt_naive = datetime.strptime(text, '%d.%m.%Y %H:%M')
        start_dt = convert_to_moscow_time(start_dt_naive)

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
        end_dt = convert_to_moscow_time(end_dt_naive)
        start_dt = context.user_data['start_time']

        if end_dt <= start_dt:
            await update.message.reply_text("❌ Время окончания должно быть позже времени начала. Попробуйте еще раз:")
            return END_TIME

        total_minutes = (end_dt - start_dt).total_seconds() / 60
        if total_minutes < 10:
            await update.message.reply_text("❌ Временной интервал должен быть не менее 10 минут. Попробуйте еще раз:")
            return END_TIME

        context.user_data['end_time'] = end_dt

        # Клавиатура с выбором типа напоминаний
        keyboard = [
            [InlineKeyboardButton("📊 Процентные напоминания", callback_data="rem_type_percent")],
            [InlineKeyboardButton("⏰ Интервальные напоминания", callback_data="rem_type_interval")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"⏱️ Общее время: {total_minutes:.0f} минут\n"
            "🔔 Выберите тип напоминаний:",
            reply_markup=reply_markup
        )
        return REMIND_TYPE

    except ValueError:
        await update.message.reply_text("❌ Неверный формат даты. Попробуйте еще раз (ДД.ММ.ГГГГ ЧЧ:ММ):")
        return END_TIME


# Обработка выбора типа напоминаний
async def process_reminder_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    rem_type = query.data.split('_')[2]
    context.user_data['reminder_type'] = rem_type

    if rem_type == 'percent':
        # Старые процентные напоминания
        keyboard = [
            [InlineKeyboardButton("1 напоминание (50%)", callback_data="rem_1")],
            [InlineKeyboardButton("2 напоминания (30%, 60%)", callback_data="rem_2")],
            [InlineKeyboardButton("3 напоминания (20%, 40%, 60%)", callback_data="rem_3")],
            [InlineKeyboardButton("4 напоминания (15%, 30%, 45%, 60%)", callback_data="rem_4")],
            [InlineKeyboardButton("5 напоминаний (10%, 20%, 40%, 50%, 60%)", callback_data="rem_5")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text("🔔 Выберите шаблон процентных напоминаний:", reply_markup=reply_markup)
        return REMIND_COUNT

    else:
        # Новые интервальные напоминания
        keyboard = []
        for key, minutes in INTERVAL_PRESETS.items():
            hours = minutes / 60
            if hours < 1:
                button_text = f"Каждые {minutes} мин"
            else:
                button_text = f"Каждые {hours:.0f} ч" if hours.is_integer() else f"Каждые {hours:.1f} ч"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"interval_{key}")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("🔔 Выберите интервал напоминаний:", reply_markup=reply_markup)
        return REMIND_INTERVAL


# Обработка выбора интервала
async def process_interval_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    interval_key = query.data.split('_')[1]
    interval_minutes = INTERVAL_PRESETS[interval_key]

    # Сохраняем интервал для настоящих интервальных напоминаний
    context.user_data['reminder_interval'] = interval_minutes

    # Для совместимости со старой системой создаем фиктивные проценты
    # Но основная логика будет использовать интервалы
    reminder_percents = [50]  # Фиктивное значение для совместимости

    context.user_data['reminder_percents'] = reminder_percents
    context.user_data['reminder_type'] = 'interval'

    return await save_final_task(update, context)


# Обработка выбора количества напоминаний
async def process_reminder_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    choice = query.data
    preset_key = choice.split('_')[1]
    context.user_data['reminder_percents'] = REMINDER_PRESETS[preset_key]
    context.user_data['reminder_type'] = 'percent'
    context.user_data['reminder_interval'] = None

    return await save_final_task(update, context)


# Функция для расчета количества интервальных напоминаний
async def calculate_interval_reminders_count(start_time, end_time, interval_minutes):
    count = 0
    current_time = start_time + timedelta(minutes=interval_minutes)

    while current_time < end_time:
        count += 1
        current_time += timedelta(minutes=interval_minutes)

    return count


# Функция для планирования интервальных напоминаний
async def schedule_interval_reminders(task_id, user_id, title, start_time, end_time, interval_minutes, context):
    current_time = get_current_time()
    scheduled_count = 0

    logger.info(f"🔔 Начинаем планирование ИНТЕРВАЛЬНЫХ напоминаний для задачи {task_id}")

    # Если дело уже началось, первое напоминание - сейчас + интервал
    # Если дело еще не началось, первое напоминание - время старта + интервал
    if current_time >= start_time:
        # Дело уже идет, первое напоминание через интервал от текущего времени
        next_reminder_time = current_time + timedelta(minutes=interval_minutes)
    else:
        # Дело еще не началось, первое напоминание через интервал от времени старта
        next_reminder_time = start_time + timedelta(minutes=interval_minutes)

    # Планируем периодические напоминания
    while next_reminder_time < end_time:
        time_until = (next_reminder_time - current_time).total_seconds()

        if time_until > 5:
            # Создаем уникальное имя для job
            job_name = f"task_{task_id}_interval_{next_reminder_time.strftime('%H%M')}"

            context.job_queue.run_once(
                send_interval_reminder,
                when=time_until,
                data={
                    'user_id': user_id,
                    'task_id': task_id,
                    'title': title,
                    'reminder_time': next_reminder_time
                },
                name=job_name
            )
            logger.info(f"✅ Запланировано ИНТЕРВАЛЬНОЕ напоминание для задачи {task_id} через {time_until:.0f} сек")
            scheduled_count += 1

        next_reminder_time += timedelta(minutes=interval_minutes)

    logger.info(f"📊 Итог планирования ИНТЕРВАЛЬНЫХ напоминаний: {scheduled_count} напоминаний запланировано")
    return scheduled_count


# Функция отправки интервального напоминания
async def send_interval_reminder(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data
    user_id = data['user_id']
    title = data['title']
    reminder_time = data['reminder_time']

    current_time = get_current_time()
    message = (
        f"⏰ Напоминание!\n"
        f"Время работать над делом:\n"
        f"**{title}**\n"
        f"🕒 Текущее время: {current_time.strftime('%H:%M:%S')}\n"
        f"🌍 Часовой пояс: Moscow (UTC+3)"
    )

    try:
        await context.bot.send_message(chat_id=user_id, text=message)
        logger.info(f"✅ ОТПРАВЛЕНО ИНТЕРВАЛЬНОЕ напоминание пользователю {user_id} для дела '{title}'")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки интервального напоминания: {e}")


# Функция для планирования процентных напоминаний
async def schedule_reminders(task_id, user_id, title, start_time, end_time, reminder_percents,
                             context: ContextTypes.DEFAULT_TYPE):
    total_duration = end_time - start_time
    now = get_current_time()
    scheduled_count = 0

    logger.info(f"🔔 Начинаем планирование ПРОЦЕНТНЫХ напоминаний для задачи {task_id}")

    for percent in reminder_percents:
        reminder_time = start_time + (total_duration * (percent / 100))
        time_until = (reminder_time - now).total_seconds()

        if time_until > 5:
            context.job_queue.run_once(
                send_reminder,
                when=time_until,
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
                f"✅ Запланировано ПРОЦЕНТНОЕ напоминание для задачи {task_id} через {time_until:.0f} сек ({percent}%)")
            scheduled_count += 1
        else:
            logger.warning(
                f"❌ Время напоминания уже прошло или скоро наступит (через {time_until:.0f} сек), не планируем")

    logger.info(
        f"📊 Итог планирования ПРОЦЕНТНЫХ напоминаний: {scheduled_count}/{len(reminder_percents)} напоминаний запланировано")
    return scheduled_count


# Функция отправки процентного напоминания
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
        f"🌍 Часовой пояс: Moscow (UTC+3)"
    )

    try:
        await context.bot.send_message(chat_id=user_id, text=message)
        logger.info(f"✅ ОТПРАВЛЕНО ПРОЦЕНТНОЕ напоминание пользователю {user_id} для дела '{title}' ({percent}%)")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки процентного напоминания: {e}")


# Финальное сохранение задачи
async def save_final_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    title = context.user_data['title']
    start_time = context.user_data['start_time']
    end_time = context.user_data['end_time']
    reminder_percents = context.user_data['reminder_percents']
    reminder_type = context.user_data.get('reminder_type', 'percent')
    reminder_interval = context.user_data.get('reminder_interval')

    task_id = save_task(user_id, title, start_time, end_time, reminder_percents, reminder_type, reminder_interval)

    if reminder_type == 'interval' and reminder_interval:
        # Настоящие интервальные напоминания
        scheduled_count = await schedule_interval_reminders(task_id, user_id, title, start_time, end_time,
                                                            reminder_interval, context)
        total_reminders = await calculate_interval_reminders_count(start_time, end_time, reminder_interval)
    else:
        # Старые процентные напоминания
        scheduled_count = await schedule_reminders(task_id, user_id, title, start_time, end_time, reminder_percents,
                                                   context)
        total_reminders = len(reminder_percents)

    # Создаем информационное сообщение
    current_time = get_current_time()

    if reminder_type == 'interval' and reminder_interval:
        reminders_text = "📅 Интервальные напоминания:\n"
        interval_hours = reminder_interval / 60

        # Показываем расписание первых напоминаний
        if current_time >= start_time:
            # Дело уже идет, первое напоминание через интервал от текущего времени
            next_time = current_time + timedelta(minutes=reminder_interval)
        else:
            # Дело еще не началось, первое напоминание через интервал от времени старта
            next_time = start_time + timedelta(minutes=reminder_interval)

        reminder_count = 0
        reminders_list = []

        while next_time < end_time and reminder_count < 5:
            time_until = (next_time - current_time).total_seconds()
            if time_until > 0:
                if time_until < 60:
                    time_str = f"через {int(time_until)} сек"
                elif time_until < 3600:
                    time_str = f"через {int(time_until // 60)} мин"
                else:
                    hours = int(time_until // 3600)
                    minutes = int((time_until % 3600) // 60)
                    time_str = f"через {hours} ч {minutes} мин"

                reminders_list.append(f"• {next_time.strftime('%H:%M')} ({time_str})")
                reminder_count += 1
            next_time += timedelta(minutes=reminder_interval)

        reminders_text += "\n".join(reminders_list)

        if total_reminders > 5:
            reminders_text += f"\n• ... и еще {total_reminders - 5} напоминаний"

        reminder_info = f"🔔 Интервал: каждые {interval_hours:.0f} ч\n"

    else:
        # Старые процентные напоминания
        reminders_text = "📅 Ближайшие напоминания:\n"
        total_duration = end_time - start_time

        reminder_list = []
        for percent in reminder_percents:
            reminder_time = start_time + (total_duration * (percent / 100))
            time_until_reminder = reminder_time - current_time
            seconds_until = int(time_until_reminder.total_seconds())

            if seconds_until > 0:
                if seconds_until < 60:
                    time_str = f"через {seconds_until} сек"
                elif seconds_until < 3600:
                    time_str = f"через {seconds_until // 60} мин"
                else:
                    hours = seconds_until // 3600
                    minutes = (seconds_until % 3600) // 60
                    time_str = f"через {hours} ч {minutes} мин"

                reminder_list.append((percent, reminder_time, seconds_until))

        reminder_list.sort(key=lambda x: x[2])
        for percent, reminder_time, seconds_until in reminder_list[:5]:
            reminders_text += f"• {percent}% - {reminder_time.strftime('%H:%M')} ({time_str})\n"

        if len(reminder_list) > 5:
            reminders_text += f"• ... и еще {len(reminder_list) - 5} напоминаний\n"

        reminder_info = f"🔔 Напоминаний: {scheduled_count}/{total_reminders}\n"

    success_text = (
        f"✅ Отлично! Дело '{title}' запланировано!\n"
        f"⏰ С {start_time.strftime('%d.%m.%Y %H:%M')} по {end_time.strftime('%d.%m.%Y %H:%M')}\n"
        f"{reminder_info}"
        f"{reminders_text}\n"
        f"🌍 Часовой пояс: Moscow (UTC+3)"
    )

    await query.edit_message_text(success_text)
    return ConversationHandler.END


# Тестовая функция для проверки напоминаний
async def test_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестовая функция - отправляет напоминание через 30 секунд"""
    user_id = update.effective_user.id

    context.job_queue.run_once(
        send_test_reminder,
        when=30,
        data={'user_id': user_id},
        name=f"test_{user_id}"
    )

    await update.message.reply_text(
        f"🧪 Тестовое напоминание запланировано!\n"
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
        "Часовой пояс: Moscow (UTC+3)"
    )

    try:
        await context.bot.send_message(chat_id=user_id, text=message)
        logger.info(f"✅ Тестовое напоминание отправлено пользователю {user_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки тестового напоминания: {e}")


# Отмена диалога
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Диалог отменен.')
    return ConversationHandler.END


def main():
    init_db()
    update_db_schema()  # ← ВАЖНО: обновляем схему базы данных

    application = Application.builder().token(BOT_TOKEN).build()

    # ConversationHandler для добавления дел
    task_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Добавить дело$"), add_task_start)],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_title)],
            START_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_start_time)],
            END_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_end_time)],
            REMIND_TYPE: [CallbackQueryHandler(process_reminder_type, pattern='^rem_type_')],
            REMIND_COUNT: [CallbackQueryHandler(process_reminder_choice, pattern='^rem_')],
            REMIND_INTERVAL: [CallbackQueryHandler(process_interval_choice, pattern='^interval_')],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    # ConversationHandler для дневника
    diary_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Добавить в дневник$"), add_diary_start)],
        states={
            "DIARY_CONTENT": [MessageHandler(filters.TEXT & ~filters.COMMAND, process_diary_content)],
            "DIARY_REMINDER": [CallbackQueryHandler(process_diary_reminder_choice, pattern='^diary_reminder_')],
            "DIARY_INTERVAL": [CallbackQueryHandler(process_diary_interval, pattern='^diary_interval_')],
            "DIARY_TIME": [MessageHandler(filters.TEXT & ~filters.COMMAND, process_diary_time)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(task_conv_handler)
    application.add_handler(diary_conv_handler)
    application.add_handler(MessageHandler(filters.Regex("^Мои дела$"), show_tasks))
    application.add_handler(MessageHandler(filters.Regex("^Дневник дел$"), show_diary))
    application.add_handler(MessageHandler(filters.Regex("^Удалить дело$"), delete_task_start))
    application.add_handler(MessageHandler(filters.Regex("^Тест напоминания$"), test_reminder))
    application.add_handler(CallbackQueryHandler(process_delete, pattern='^delete_'))

    logger.info("Бот запущен с расширенными функциями...")
    print("=" * 60)
    print("🤖 БОТ ЗАПУЩЕН! Новые функции:")
    print("• 📔 Дневник дел - простые записи с напоминаниями")
    print("• ⏰ ИНТЕРВАЛЬНЫЕ напоминания - настоящие интервалы каждый час/день и т.д.")
    print("• 🔄 Периодические напоминания для дневника")
    print("• 🗑️ Удаление дел И записей из дневника")
    print("• 🌍 Московское время (UTC+3)")
    print("=" * 60)

    application.run_polling()


if __name__ == '__main__':
    main()
