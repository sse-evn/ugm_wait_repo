import asyncio
import sqlite3
from aiogram import Bot, Dispatcher, types
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

# --- Загрузка переменных окружения из .env файла ---
load_dotenv()

API_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = [int(x) for x in os.getenv('ADMIN_IDS').split(',')]
SOURCE_CHAT_IDS = [int(x) for x in os.getenv('SOURCE_CHAT_IDS').split(',')]
DESTINATION_CHAT_ID = int(os.getenv('DESTINATION_CHAT_ID'))
INACTIVITY_THRESHOLD_MINUTES = int(os.getenv('INACTIVITY_THRESHOLD_MINUTES'))
INACTIVITY_CHECK_INTERVAL_SECONDS = int(os.getenv('INACTIVITY_CHECK_INTERVAL_SECONDS'))

MORNING_SHIFT_START_HOUR = int(os.getenv('MORNING_SHIFT_START_HOUR'))
MORNING_SHIFT_END_HOUR = int(os.getenv('MORNING_SHIFT_END_HOUR'))
EVENING_SHIFT_START_HOUR = int(os.getenv('EVENING_SHIFT_START_HOUR'))
EVENING_SHIFT_END_HOUR = int(os.getenv('EVENING_SHIFT_END_HOUR'))


# Проверки на наличие обязательных переменных
if not all([API_TOKEN, ADMIN_IDS, SOURCE_CHAT_IDS, DESTINATION_CHAT_ID,
            INACTIVITY_THRESHOLD_MINUTES, INACTIVITY_CHECK_INTERVAL_SECONDS,
            MORNING_SHIFT_START_HOUR, MORNING_SHIFT_END_HOUR,
            EVENING_SHIFT_START_HOUR, EVENING_SHIFT_END_HOUR]):
    raise ValueError("One or more essential environment variables are not set. Check your .env file.")

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# --- Функции для работы с базой данных ---
DB_NAME = 'bot_data.db'

def init_db():
    """Инициализирует базу данных и создает таблицы, если их нет."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ignored_users (
                user_id INTEGER PRIMARY KEY,
                user_name TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_activity (
                user_id INTEGER PRIMARY KEY,
                user_name TEXT,
                messages_forwarded INTEGER DEFAULT 0,
                last_activity_time TEXT,
                shift TEXT DEFAULT 'unassigned' -- Добавлено поле для смены
            )
        ''')
        # Проверяем, существует ли столбец 'shift' и добавляем его, если нет
        try:
            cursor.execute("ALTER TABLE user_activity ADD COLUMN shift TEXT DEFAULT 'unassigned'")
        except sqlite3.OperationalError as e:
            if "duplicate column name: shift" not in str(e):
                raise
        conn.commit()

def get_ignored_users():
    """Возвращает словарь игнорируемых пользователей из БД."""
    ignored = {}
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, user_name FROM ignored_users")
        for user_id, user_name in cursor.fetchall():
            ignored[user_id] = user_name
    return ignored

def add_ignored_user(user_id: int, user_name: str):
    """Добавляет пользователя в список игнорируемых в БД."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO ignored_users (user_id, user_name) VALUES (?, ?)",
                       (user_id, user_name))
        conn.commit()

def remove_ignored_user(user_id: int):
    """Удаляет пользователя из списка игнорируемых в БД."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ignored_users WHERE user_id = ?", (user_id,))
        conn.commit()

def update_user_activity(user_id: int, user_name: str, current_time_str: str):
    """Обновляет счетчик пересланных сообщений и время последней активности для пользователя в БД."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        # Проверяем, существует ли пользователь. Если нет, вставляем с начальными значениями.
        cursor.execute("INSERT OR IGNORE INTO user_activity (user_id, user_name, messages_forwarded, last_activity_time, shift) VALUES (?, ?, 0, ?, 'unassigned')",
                       (user_id, user_name, current_time_str))
        # Обновляем данные пользователя
        cursor.execute("UPDATE user_activity SET messages_forwarded = messages_forwarded + 1, user_name = ?, last_activity_time = ? WHERE user_id = ?",
                       (user_name, current_time_str, user_id))
        conn.commit()

def get_top_users(limit: int = 10, shift: str = None):
    """Возвращает топ пользователей по количеству пересланных сообщений, опционально по смене."""
    top_users = []
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        if shift and shift != 'all':
            cursor.execute("SELECT user_id, user_name, messages_forwarded FROM user_activity WHERE shift = ? ORDER BY messages_forwarded DESC LIMIT ?", (shift, limit))
        else:
            cursor.execute("SELECT user_id, user_name, messages_forwarded FROM user_activity ORDER BY messages_forwarded DESC LIMIT ?", (limit,))
        top_users = cursor.fetchall()
    return top_users

def get_inactive_users(threshold_minutes: int, current_active_shift: str):
    """Возвращает список пользователей, неактивных дольше заданного порога и относящихся к текущей активной смене."""
    inactive_users = []
    threshold_time = datetime.now() - timedelta(minutes=threshold_minutes)
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, user_name, last_activity_time, shift FROM user_activity")
        for user_id, user_name, last_activity_str, user_shift in cursor.fetchall():
            try:
                last_activity_dt = datetime.fromisoformat(last_activity_str)
                # Проверяем неактивность только для пользователей текущей активной смены
                if user_shift == current_active_shift and last_activity_dt < threshold_time:
                    inactive_users.append((user_id, user_name, last_activity_dt, user_shift))
            except ValueError:
                print(f"Ошибка парсинга даты для пользователя {user_id}: {last_activity_str}")
                continue
    return inactive_users

def set_user_shift(user_id: int, user_name: str, shift: str):
    """Устанавливает или обновляет смену для пользователя в БД."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO user_activity (user_id, user_name, messages_forwarded, last_activity_time, shift) VALUES (?, ?, 0, ?, ?)",
                       (user_id, user_name, datetime.now().isoformat(), 'unassigned')) # Вставляем с дефолтными значениями, если нет
        cursor.execute("UPDATE user_activity SET shift = ?, user_name = ? WHERE user_id = ?",
                       (shift, user_name, user_id))
        conn.commit()

def get_user_by_id(user_id: int):
    """Получает информацию о пользователе из user_activity."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, user_name, shift FROM user_activity WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result:
            return {'user_id': result[0], 'user_name': result[1], 'shift': result[2]}
        return None

# --- Глобальные переменные для кэша и отслеживания уведомлений ---
ignored_users_cache = get_ignored_users()
notified_inactive_users_cache = set()

# --- Вспомогательные функции для расписания ---
def get_current_shift():
    """Определяет, какая смена сейчас активна."""
    current_hour = datetime.now().hour
    if MORNING_SHIFT_START_HOUR <= current_hour < MORNING_SHIFT_END_HOUR:
        return 'morning'
    elif EVENING_SHIFT_START_HOUR <= current_hour < EVENING_SHIFT_END_HOUR:
        return 'evening'
    else:
        return 'off_shift' # Вне рабочих смен

def is_bot_active_now():
    """Проверяет, должен ли бот сейчас работать (находится ли в активной смене)."""
    return get_current_shift() in ['morning', 'evening']


# --- Обработчик сообщений для пересылки ---
@dp.message_handler(content_types=types.ContentType.ANY, chat_id=SOURCE_CHAT_IDS)
async def forward_messages(message: types.Message):
    if not is_bot_active_now():
        # Бот не должен работать вне смены, игнорируем сообщение
        return

    user_id = message.from_user.id
    user_full_name = message.from_user.full_name or f"Пользователь {user_id}"
    current_time_str = datetime.now().isoformat()

    # Если пользователь был в списке уведомленных о неактивности, удаляем его, так как он снова активен
    if user_id in notified_inactive_users_cache:
        notified_inactive_users_cache.remove(user_id)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Пользователь {user_full_name} ({user_id}) снова активен.")

    # Проверяем кэш игнорируемых пользователей
    if user_id in ignored_users_cache:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Игнорируем сообщение от {user_full_name} ({user_id}) в группе {message.chat.title} ({message.chat.id}).")
        return

    try:
        await bot.copy_message(chat_id=DESTINATION_CHAT_ID,
                               from_chat_id=message.chat.id,
                               message_id=message.message_id)

        # Обновляем статистику активности пользователя
        update_user_activity(user_id, user_full_name, current_time_str)

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Сообщение (ID: {message.message_id}) от {user_full_name} из группы {message.chat.title} ({message.chat.id}) успешно переслано в группу {DESTINATION_CHAT_ID}.")
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Ошибка при пересылке сообщения (ID: {message.message_id}) от {user_full_name} из чата {message.chat.id}: {e}")

# --- Команды для управления списками ---

@dp.message_handler(commands=['ignore'], chat_type=types.ChatType.PRIVATE)
async def add_to_ignore_list(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("У вас нет прав для выполнения этой команды.")
        return

    args = message.get_args().split()
    if not args:
        await message.reply("Использование: /ignore <user_id>")
        return

    try:
        target_user_id = int(args[0])
        user_info = None
        for chat_id in SOURCE_CHAT_IDS:
            try:
                member = await bot.get_chat_member(chat_id, target_user_id)
                user_info = member.user
                break
            except Exception:
                continue

        user_full_name = user_info.full_name if user_info else f"Неизвестный пользователь (ID: {target_user_id})"

        if target_user_id not in ignored_users_cache:
            add_ignored_user(target_user_id, user_full_name)
            ignored_users_cache[target_user_id] = user_full_name
            await message.reply(f"Пользователь **{user_full_name}** (ID: `{target_user_id}`) добавлен в список игнорируемых.",
                                parse_mode=types.ParseMode.MARKDOWN)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Добавлен в игнор: {user_full_name} ({target_user_id})")
        else:
            await message.reply(f"Пользователь **{user_full_name}** (ID: `{target_user_id}`) уже находится в списке игнорируемых.",
                                parse_mode=types.ParseMode.MARKDOWN)

    except ValueError:
        await message.reply("Некорректный ID пользователя. ID должен быть числом.")
    except Exception as e:
        await message.reply(f"Произошла ошибка: {e}")

@dp.message_handler(commands=['unignore'], chat_type=types.ChatType.PRIVATE)
async def remove_from_ignore_list(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("У вас нет прав для выполнения этой команды.")
        return

    args = message.get_args().split()
    if not args:
        await message.reply("Использование: /unignore <user_id>")
        return

    try:
        target_user_id = int(args[0])
        if target_user_id in ignored_users_cache:
            user_full_name = ignored_users_cache.pop(target_user_id)
            remove_ignored_user(target_user_id)
            await message.reply(f"Пользователь **{user_full_name}** (ID: `{target_user_id}`) удален из списка игнорируемых.",
                                parse_mode=types.ParseMode.MARKDOWN)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Удален из игнора: {user_full_name} ({target_user_id})")
        else:
            await message.reply(f"Пользователь с ID `{target_user_id}` не найден в списке игнорируемых.",
                                parse_mode=types.ParseMode.MARKDOWN)
    except ValueError:
        await message.reply("Некорректный ID пользователя. ID должен быть числом.")
    except Exception as e:
        await message.reply(f"Произошла ошибка: {e}")

@dp.message_handler(commands=['ignored_users'], chat_type=types.ChatType.PRIVATE)
async def show_ignored_users(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("У вас нет прав для выполнения этой команды.")
        return

    global ignored_users_cache
    ignored_users_cache = get_ignored_users()

    if not ignored_users_cache:
        await message.reply("Список игнорируемых пользователей пуст.")
        return

    response = "Список игнорируемых пользователей:\n\n"
    for user_id, user_name in ignored_users_cache.items():
        response += f"- **{user_name}** (ID: `{user_id}`)\n"

    await message.reply(response, parse_mode=types.ParseMode.MARKDOWN)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Показан список игнорируемых пользователей.")

# --- Команда: Топ пользователей (с фильтром по смене) ---
@dp.message_handler(commands=['top_users'], chat_type=types.ChatType.PRIVATE)
async def show_top_users(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("У вас нет прав для выполнения этой команды.")
        return

    args = message.get_args().split()
    shift_filter = None
    if args and args[0].lower() in ['morning', 'evening', 'all']:
        shift_filter = args[0].lower()

    top_list = get_top_users(shift=shift_filter)

    if not top_list:
        if shift_filter:
            await message.reply(f"Статистика активности для смены '{shift_filter}' пока пуста.")
        else:
            await message.reply("Статистика активности пока пуста.")
        return

    response_header = "📊 **Топ пользователей по пересланным сообщениям**"
    if shift_filter == 'morning':
        response_header += " (Утренняя смена):"
    elif shift_filter == 'evening':
        response_header += " (Вечерняя смена):"
    else:
        response_header += " (Все смены):"
    response_header += "\n\n"

    response = response_header
    for i, (user_id, user_name, forwarded_count) in enumerate(top_list):
        response += f"{i+1}. **{user_name}** (ID: `{user_id}`) - `{forwarded_count}` сообщений\n"

    await message.reply(response, parse_mode=types.ParseMode.MARKDOWN)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Показан топ пользователей (фильтр: {shift_filter or 'нет'}).")


# --- Команды для управления сменами пользователей ---
@dp.message_handler(commands=['set_shift'], chat_type=types.ChatType.PRIVATE)
async def set_user_shift_command(message: types.Message):
    """
    Устанавливает смену для пользователя.
    Использование: /set_shift <user_id> <morning|evening|unassigned>
    """
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("У вас нет прав для выполнения этой команды.")
        return

    args = message.get_args().split()
    if len(args) != 2:
        await message.reply("Использование: /set_shift <user_id> <morning|evening|unassigned>")
        return

    try:
        target_user_id = int(args[0])
        shift_type = args[1].lower()
        if shift_type not in ['morning', 'evening', 'unassigned']:
            await message.reply("Некорректный тип смены. Допустимые значения: `morning`, `evening`, `unassigned`.")
            return

        user_info_from_db = get_user_by_id(target_user_id)
        if user_info_from_db:
            user_name = user_info_from_db['user_name']
        else:
            # Пытаемся получить имя, если пользователя нет в нашей БД
            user_info = None
            for chat_id in SOURCE_CHAT_IDS:
                try:
                    member = await bot.get_chat_member(chat_id, target_user_id)
                    user_info = member.user
                    break
                except Exception:
                    continue
            user_name = user_info.full_name if user_info else f"Неизвестный пользователь (ID: {target_user_id})"


        set_user_shift(target_user_id, user_name, shift_type)
        await message.reply(f"Смена для пользователя **{user_name}** (ID: `{target_user_id}`) установлена на **{shift_type}**.",
                            parse_mode=types.ParseMode.MARKDOWN)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Смена пользователя {user_name} ({target_user_id}) установлена на {shift_type}.")

    except ValueError:
        await message.reply("Некорректный ID пользователя. ID должен быть числом.")
    except Exception as e:
        await message.reply(f"Произошла ошибка: {e}")

@dp.message_handler(commands=['get_shift'], chat_type=types.ChatType.PRIVATE)
async def get_user_shift_command(message: types.Message):
    """
    Показывает смену пользователя.
    Использование: /get_shift <user_id>
    """
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("У вас нет прав для выполнения этой команды.")
        return

    args = message.get_args().split()
    if not args:
        await message.reply("Использование: /get_shift <user_id>")
        return

    try:
        target_user_id = int(args[0])
        user_data = get_user_by_id(target_user_id)

        if user_data:
            await message.reply(f"Пользователь **{user_data['user_name']}** (ID: `{user_data['user_id']}`) находится в смене: **{user_data['shift']}**.",
                                parse_mode=types.ParseMode.MARKDOWN)
        else:
            await message.reply(f"Информация о пользователе с ID `{target_user_id}` не найдена в базе данных.",
                                parse_mode=types.ParseMode.MARKDOWN)
    except ValueError:
        await message.reply("Некорректный ID пользователя. ID должен быть числом.")
    except Exception as e:
        await message.reply(f"Произошла ошибка: {e}")

@dp.message_handler(commands=['list_shifts'], chat_type=types.ChatType.PRIVATE)
async def list_users_by_shifts(message: types.Message):
    """
    Показывает список пользователей по сменам.
    """
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("У вас нет прав для выполнения этой команды.")
        return

    morning_users = []
    evening_users = []
    unassigned_users = []

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, user_name, shift FROM user_activity ORDER BY user_name")
        for user_id, user_name, shift in cursor.fetchall():
            if shift == 'morning':
                morning_users.append(f"- **{user_name}** (`{user_id}`)")
            elif shift == 'evening':
                evening_users.append(f"- **{user_name}** (`{user_id}`)")
            else:
                unassigned_users.append(f"- **{user_name}** (`{user_id}`)")

    response = "👥 **Распределение пользователей по сменам:**\n\n"
    response += "🌞 **Утренняя смена (07:00 - 15:00):**\n"
    response += "\n".join(morning_users) if morning_users else "_(Нет пользователей)_\n"
    response += "\n\n🌙 **Вечерняя смена (15:00 - 23:00):**\n"
    response += "\n".join(evening_users) if evening_users else "_(Нет пользователей)_\n"
    response += "\n\n❓ **Неназначенные пользователи:**\n"
    response += "\n".join(unassigned_users) if unassigned_users else "_(Нет пользователей)_\n"

    await message.reply(response, parse_mode=types.ParseMode.MARKDOWN)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Показан список пользователей по сменам.")

# --- Фоновая задача для проверки неактивности ---
async def check_inactivity_task():
    """
    Фоновая задача, которая периодически проверяет неактивных пользователей
    и отправляет уведомления администраторам, только если бот в активной смене.
    """
    while True:
        await asyncio.sleep(INACTIVITY_CHECK_INTERVAL_SECONDS)

        current_active_shift = get_current_shift()
        if not is_bot_active_now():
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Бот вне рабочих смен ({current_active_shift}). Проверка неактивности пропущена.")
            # Очищаем кэш уведомлений, чтобы не уведомить повторно после начала новой смены
            global notified_inactive_users_cache
            notified_inactive_users_cache.clear()
            continue # Пропускаем проверку, если бот вне смены

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Запущена проверка неактивных пользователей для смены '{current_active_shift}'...")

        inactive_users = get_inactive_users(INACTIVITY_THRESHOLD_MINUTES, current_active_shift)

        for user_id, user_name, last_activity_dt, user_shift in inactive_users:
            if user_id not in notified_inactive_users_cache:
                # Отправляем уведомление администраторам
                message_text = (
                    f"⚠️ Пользователь **{user_name}** (ID: `{user_id}`) из **{user_shift.capitalize()}** смены "
                    f"не проявлял активности более {INACTIVITY_THRESHOLD_MINUTES} минут. "
                    f"Последняя активность: {last_activity_dt.strftime('%Y-%m-%d %H:%M:%S')}"
                )
                for admin_id in ADMIN_IDS:
                    try:
                        await bot.send_message(admin_id, message_text, parse_mode=types.ParseMode.MARKDOWN)
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Отправлено уведомление админу {admin_id} о неактивности: {user_name} ({user_id})")
                    except Exception as e:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Ошибка при отправке уведомления админу {admin_id}: {e}")
                notified_inactive_users_cache.add(user_id) # Добавляем в кэш, чтобы не спамить

# --- Главная функция запуска бота ---
async def main():
    """
    Главная функция запуска бота и фоновой задачи.
    """
    init_db() # Инициализируем БД при запуске
    asyncio.create_task(check_inactivity_task()) # Запускаем фоновую задачу для проверки активности
    print("Бот запускается...")
    await dp.start_polling()

if __name__ == '__main__':
    asyncio.run(main())
    print("Бот остановлен.")
