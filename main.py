import asyncio
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import pytz

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

TARGET_TIMEZONE = pytz.timezone('Asia/Almaty') 

if not all([API_TOKEN, ADMIN_IDS, SOURCE_CHAT_IDS, DESTINATION_CHAT_ID,
            INACTIVITY_THRESHOLD_MINUTES, INACTIVITY_CHECK_INTERVAL_SECONDS,
            MORNING_SHIFT_START_HOUR, MORNING_SHIFT_END_HOUR,
            EVENING_SHIFT_START_HOUR, EVENING_SHIFT_END_HOUR]):
    raise ValueError("One or more essential environment variables are not set. Check your .env file.")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

DB_NAME = 'bot_data.db'

# --- Вспомогательная функция для экранирования символов MarkdownV2 ---
def escape_markdown_v2(text: str) -> str:
    """Экранирует специальные символы для форматирования MarkdownV2."""
    # Полный список зарезервированных символов для MarkdownV2
    # Обратите внимание: дефис '-' здесь для экранирования в тексте, а не как маркер списка.
    # Если '-' используется как маркер списка в начале новой строки, его экранировать не нужно.
    # Но если он часть текста, как в '07:00-15:00', то нужно.
    # Поэтому ручное экранирование в таких случаях более надежно.
    # Оставим функцию общей, а точечные исправления сделаем в строках.
    escape_chars = r'_*[]()~`>#+=|{}.!' # Дефис убрал из универсального экранирования
                                        # так как он может быть маркером списка
                                        # и тогда его экранировать не нужно.
                                        # Будем экранировать его вручную в проблемных местах.
    return "".join(['\\' + char if char in escape_chars else char for char in text])


def init_db():
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
                shift TEXT DEFAULT 'unassigned'
            )
        ''')
        try:
            cursor.execute("ALTER TABLE user_activity ADD COLUMN shift TEXT DEFAULT 'unassigned'")
        except sqlite3.OperationalError as e:
            if "duplicate column name: shift" not in str(e):
                raise
        conn.commit()

def get_ignored_users():
    ignored = {}
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, user_name FROM ignored_users")
        for user_id, user_name in cursor.fetchall():
            ignored[user_id] = user_name
    return ignored

def add_ignored_user(user_id: int, user_name: str):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO ignored_users (user_id, user_name) VALUES (?, ?)",
                       (user_id, user_name))
        conn.commit()

def remove_ignored_user(user_id: int):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ignored_users WHERE user_id = ?", (user_id,))
        conn.commit()

def update_user_activity(user_id: int, user_name: str, current_time_str: str):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO user_activity (user_id, user_name, messages_forwarded, last_activity_time, shift) VALUES (?, ?, 0, ?, ?)",
                       (user_id, user_name, current_time_str, 'unassigned'))
        cursor.execute("UPDATE user_activity SET messages_forwarded = messages_forwarded + 1, user_name = ?, last_activity_time = ? WHERE user_id = ?",
                       (user_name, current_time_str, user_id))
        conn.commit()

def get_top_users(limit: int = 10, shift: str = None):
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
    inactive_users = []
    now_in_target_tz = datetime.now(TARGET_TIMEZONE)
    threshold_time = now_in_target_tz - timedelta(minutes=threshold_minutes)

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, user_name, last_activity_time, shift FROM user_activity")
        for user_id, user_name, last_activity_str, user_shift in cursor.fetchall():
            try:
                last_activity_dt = datetime.fromisoformat(last_activity_str)
                if last_activity_dt.tzinfo is None:
                     last_activity_dt = TARGET_TIMEZONE.localize(last_activity_dt)
                else:
                    last_activity_dt = last_activity_dt.astimezone(TARGET_TIMEZONE)

                if user_shift == current_active_shift and last_activity_dt < threshold_time:
                    inactive_users.append((user_id, user_name, last_activity_dt, user_shift))
            except ValueError:
                print(f"[{datetime.now(TARGET_TIMEZONE).strftime('%H:%M:%S')}] Ошибка парсинга даты для пользователя {user_id}: {last_activity_str}")
                continue
    return inactive_users

def set_user_shift(user_id: int, user_name: str, shift: str):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        current_time_in_target_tz = datetime.now(TARGET_TIMEZONE).isoformat()
        cursor.execute("INSERT OR IGNORE INTO user_activity (user_id, user_name, messages_forwarded, last_activity_time, shift) VALUES (?, ?, 0, ?, ?)",
                       (user_id, user_name, current_time_in_target_tz, 'unassigned'))
        cursor.execute("UPDATE user_activity SET shift = ?, user_name = ? WHERE user_id = ?",
                       (shift, user_name, user_id))
        conn.commit()

def get_user_by_id(user_id: int):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, user_name, shift FROM user_activity WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result:
            return {'user_id': result[0], 'user_name': result[1], 'shift': result[2]}
        return None

def get_current_shift():
    current_hour = datetime.now(TARGET_TIMEZONE).hour
    if MORNING_SHIFT_START_HOUR <= current_hour < MORNING_SHIFT_END_HOUR:
        return 'morning'
    elif EVENING_SHIFT_START_HOUR <= current_hour < EVENING_SHIFT_END_HOUR:
        return 'evening'
    else:
        return 'off_shift'

def is_bot_active_now():
    return get_current_shift() in ['morning', 'evening']

init_db()

ignored_users_cache = get_ignored_users()
notified_inactive_users_cache = set()

@dp.message(F.chat.id.in_(SOURCE_CHAT_IDS))
async def update_user_activity_on_message(message: types.Message):
    if not is_bot_active_now():
        return

    user_id = message.from_user.id
    user_full_name = message.from_user.full_name or f"Пользователь {user_id}"
    current_time_str = datetime.now(TARGET_TIMEZONE).isoformat()

    if user_id in notified_inactive_users_cache:
        notified_inactive_users_cache.remove(user_id)
        print(f"[{datetime.now(TARGET_TIMEZONE).strftime('%H:%M:%S')}] Пользователь {user_full_name} ({user_id}) снова активен.")

    if user_id in ignored_users_cache:
        print(f"[{datetime.now(TARGET_TIMEZONE).strftime('%H:%M:%S')}] Игнорируем сообщение от {user_full_name} ({user_id}) в группе {message.chat.title} ({message.chat.id}).")
        return

    update_user_activity(user_id, user_full_name, current_time_str)

    print(f"[{datetime.now(TARGET_TIMEZONE).strftime('%H:%M:%S')}] Активность пользователя {user_full_name} ({user_id}) в группе {message.chat.title} ({message.chat.id}) обновлена.")


@dp.message(Command("ignore"), F.chat.type == "private")
async def add_to_ignore_list(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("У вас нет прав для выполнения этой команды.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("Использование: /ignore `<user_id>`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    try:
        target_user_id = int(args[1])
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
            await message.reply(f"Пользователь **{escape_markdown_v2(user_full_name)}** \\(ID: `{target_user_id}`\\) добавлен в список игнорируемых\\.",
                                parse_mode=ParseMode.MARKDOWN_V2)
            print(f"[{datetime.now(TARGET_TIMEZONE).strftime('%H:%M:%S')}] Добавлен в игнор: {user_full_name} ({target_user_id})")
        else:
            await message.reply(f"Пользователь **{escape_markdown_v2(user_full_name)}** \\(ID: `{target_user_id}`\\) уже находится в списке игнорируемых\\.",
                                parse_mode=ParseMode.MARKDOWN_V2)

    except ValueError:
        await message.reply("Некорректный ID пользователя\\. ID должен быть числом\\.", parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        await message.reply(f"Произошла ошибка: {escape_markdown_v2(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)

@dp.message(Command("unignore"), F.chat.type == "private")
async def remove_from_ignore_list(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("У вас нет прав для выполнения этой команды.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("Использование: /unignore `<user_id>`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    try:
        target_user_id = int(args[1])
        if target_user_id in ignored_users_cache:
            user_full_name = ignored_users_cache.pop(target_user_id)
            remove_ignored_user(target_user_id)
            await message.reply(f"Пользователь **{escape_markdown_v2(user_full_name)}** \\(ID: `{target_user_id}`\\) удален из списка игнорируемых\\.",
                                parse_mode=ParseMode.MARKDOWN_V2)
            print(f"[{datetime.now(TARGET_TIMEZONE).strftime('%H:%M:%S')}] Удален из игнора: {user_full_name} ({target_user_id})")
        else:
            await message.reply(f"Пользователь с ID `{target_user_id}` не найден в списке игнорируемых\\.",
                                parse_mode=ParseMode.MARKDOWN_V2)
    except ValueError:
        await message.reply("Некорректный ID пользователя\\. ID должен быть числом\\.", parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        await message.reply(f"Произошла ошибка: {escape_markdown_v2(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)

@dp.message(Command("ignored_users"), F.chat.type == "private")
async def show_ignored_users(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("У вас нет прав для выполнения этой команды.")
        return

    global ignored_users_cache
    ignored_users_cache = get_ignored_users()

    if not ignored_users_cache:
        await message.reply("Список игнорируемых пользователей пуст\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    response = "Список игнорируемых пользователей:\n\n"
    for user_id, user_name in ignored_users_cache.items():
        response += f"- **{escape_markdown_v2(user_name)}** \\(ID: `{user_id}`\\)\n"

    await message.reply(response, parse_mode=ParseMode.MARKDOWN_V2)
    print(f"[{datetime.now(TARGET_TIMEZONE).strftime('%H:%M:%S')}] Показан список игнорируемых пользователей.")

@dp.message(Command("top_users"), F.chat.type == "private")
async def show_top_users(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("У вас нет прав для выполнения этой команды.")
        return

    args = message.text.split(maxsplit=1)
    shift_filter = None
    if len(args) > 1 and args[1].lower() in ['morning', 'evening', 'all']:
        shift_filter = args[1].lower()

    top_list = get_top_users(shift=shift_filter)

    if not top_list:
        if shift_filter:
            await message.reply(f"Статистика активности для смены '{shift_filter}' пока пуста\\.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await message.reply("Статистика активности пока пуста\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    response_header = "📊 **Топ пользователей по пересланным сообщениям**"
    if shift_filter == 'morning':
        response_header += " \\(Утренняя смена\\):"
    elif shift_filter == 'evening':
        response_header += " \\(Вечерняя смена\\):"
    else:
        response_header += " \\(Все смены\\):"
    response_header += "\n\n"

    response = response_header
    for i, (user_id, user_name, forwarded_count) in enumerate(top_list):
        # Здесь была потенциальная проблема с дефисом, если он не был экранирован
        # В данном случае, дефис используется как обычный текст, поэтому экранируем его.
        response += f"{i+1}\\. **{escape_markdown_v2(user_name)}** \\(ID: `{user_id}`\\) \\- `{forwarded_count}` сообщений\n"

    await message.reply(response, parse_mode=ParseMode.MARKDOWN_V2)
    print(f"[{datetime.now(TARGET_TIMEZONE).strftime('%H:%M:%S')}] Показан топ пользователей (фильтр: {shift_filter or 'нет'}).")

@dp.message(Command("set_shift"), F.chat.type == "private")
async def set_user_shift_command(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("У вас нет прав для выполнения этой команды.")
        return

    args = message.text.split(maxsplit=2)
    if len(args) != 3:
        await message.reply("Использование: /set_shift `<user_id>` `<morning|evening|unassigned>`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    try:
        target_user_id = int(args[1])
        shift_type = args[2].lower()
        if shift_type not in ['morning', 'evening', 'unassigned']:
            await message.reply("Некорректный тип смены\\. Допустимые значения: `morning`, `evening`, `unassigned`\\.", parse_mode=ParseMode.MARKDOWN_V2)
            return

        user_info_from_db = get_user_by_id(target_user_id)
        if user_info_from_db:
            user_name = user_info_from_db['user_name']
        else:
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
        await message.reply(f"Смена для пользователя **{escape_markdown_v2(user_name)}** \\(ID: `{target_user_id}`\\) установлена на **{shift_type}**\\.",
                            parse_mode=ParseMode.MARKDOWN_V2)
        print(f"[{datetime.now(TARGET_TIMEZONE).strftime('%H:%M:%S')}] Смена пользователя {user_name} ({target_user_id}) установлена на {shift_type}.")

    except ValueError:
        await message.reply("Некорректный ID пользователя\\. ID должен быть числом\\.", parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        await message.reply(f"Произошла ошибка: {escape_markdown_v2(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)

@dp.message(Command("get_shift"), F.chat.type == "private")
async def get_user_shift_command(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("У вас нет прав для выполнения этой команды.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("Использование: /get_shift `<user_id>`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    try:
        target_user_id = int(args[1])
        user_data = get_user_by_id(target_user_id)

        if user_data:
            await message.reply(f"Пользователь **{escape_markdown_v2(user_data['user_name'])}** \\(ID: `{user_data['user_id']}`\\) находится в смене: **{user_data['shift']}**\\.",
                                parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await message.reply(f"Информация о пользователе с ID `{target_user_id}` не найдена в базе данных\\.",
                                parse_mode=ParseMode.MARKDOWN_V2)
    except ValueError:
        await message.reply("Некорректный ID пользователя\\. ID должен быть числом\\.", parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        await message.reply(f"Произошла ошибка: {escape_markdown_v2(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)

@dp.message(Command("list_shifts"), F.chat.type == "private")
async def list_users_by_shifts(message: types.Message):
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
            escaped_user_name = escape_markdown_v2(user_name)
            # Дефис здесь - это маркер списка Markdown, поэтому его не нужно экранировать.
            if shift == 'morning':
                morning_users.append(f"- **{escaped_user_name}** \\(`{user_id}`\\)")
            elif shift == 'evening':
                evening_users.append(f"- **{escaped_user_name}** \\(`{user_id}`\\)")
            else:
                unassigned_users.append(f"- **{escaped_user_name}** \\(`{user_id}`\\)")

    response = "👥 **Распределение пользователей по сменам:**\n\n"
    # Здесь дефисы используются как разделители в тексте, поэтому их нужно экранировать.
    response += "🌞 **Утренняя смена \\(07:00 \\- 15:00\\):**\n"
    response += "\n".join(morning_users) if morning_users else "\\(Нет пользователей\\)\n"
    response += "\n\n🌙 **Вечерняя смена \\(15:00 \\- 23:00\\):**\n"
    response += "\n".join(evening_users) if evening_users else "\\(Нет пользователей\\)\n"
    response += "\n\n❓ **Неназначенные пользователи:**\n"
    response += "\n".join(unassigned_users) if unassigned_users else "\\(Нет пользователей\\)\n"

    await message.reply(response, parse_mode=ParseMode.MARKDOWN_V2)
    print(f"[{datetime.now(TARGET_TIMEZONE).strftime('%H:%M:%S')}] Показан список пользователей по сменам.")

async def check_inactivity_task():
    while True:
        await asyncio.sleep(INACTIVITY_CHECK_INTERVAL_SECONDS)

        current_active_shift = get_current_shift()
        if not is_bot_active_now():
            print(f"[{datetime.now(TARGET_TIMEZONE).strftime('%H:%M:%S')}] Бот вне рабочих смен ({current_active_shift}). Проверка неактивности пропущена.")
            global notified_inactive_users_cache
            notified_inactive_users_cache.clear()
            continue

        print(f"[{datetime.now(TARGET_TIMEZONE).strftime('%H:%M:%S')}] Запущена проверка неактивных пользователей для смены '{current_active_shift}'...")

        inactive_users = get_inactive_users(INACTIVITY_THRESHOLD_MINUTES, current_active_shift)

        for user_id, user_name, last_activity_dt, user_shift in inactive_users:
            if user_id not in notified_inactive_users_cache:
                formatted_last_activity = last_activity_dt.strftime('%Y-%m-%d %H:%M:%S %Z%z')
                message_text = (
                    f"⚠️ Пользователь **{escape_markdown_v2(user_name)}** \\(ID: `{user_id}`\\) из **{user_shift.capitalize()}** смены "
                    f"не проявлял активности более {INACTIVITY_THRESHOLD_MINUTES} минут\\.\n"
                    f"Последняя активность: `{formatted_last_activity}`"
                )
                try:
                    await bot.send_message(DESTINATION_CHAT_ID, message_text, parse_mode=ParseMode.MARKDOWN_V2)
                    print(f"[{datetime.now(TARGET_TIMEZONE).strftime('%H:%M:%S')}] Отправлено уведомление в группу {DESTINATION_CHAT_ID} о неактивности: {user_name} ({user_id})")
                except Exception as e:
                    print(f"[{datetime.now(TARGET_TIMEZONE).strftime('%H:%M:%S')}] Ошибка при отправке уведомления в группу {DESTINATION_CHAT_ID}: {e}")
                notified_inactive_users_cache.add(user_id)

async def main():
    asyncio.create_task(check_inactivity_task())
    print("Бот запускается...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен вручную.")
    except Exception as e:
        print(f"Произошла непредвиденная ошибка: {e}")
    print("Бот завершил работу.")
