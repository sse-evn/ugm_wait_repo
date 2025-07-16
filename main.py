import asyncio
import sqlite3
from aiogram import Bot, Dispatcher, types
from datetime import datetime
import os
from dotenv import load_dotenv

# --- Загрузка переменных окружения из .env файла ---
load_dotenv()

API_TOKEN = os.getenv('BOT_TOKEN')
# Преобразуем строки с ID в списки чисел
ADMIN_IDS = [int(x) for x in os.getenv('ADMIN_IDS').split(',')]
SOURCE_CHAT_IDS = [int(x) for x in os.getenv('SOURCE_CHAT_IDS').split(',')]
DESTINATION_CHAT_ID = int(os.getenv('DESTINATION_CHAT_ID'))

# Проверки на наличие обязательных переменных
if not all([API_TOKEN, ADMIN_IDS, SOURCE_CHAT_IDS, DESTINATION_CHAT_ID]):
    raise ValueError("One or more essential environment variables are not set. Check your .env file.")

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# --- Функции для работы с базой данных ---
DB_NAME = 'bot_data.db'

def init_db():
    """Инициализирует базу данных и создает таблицы, если их нет."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        # Таблица для игнорируемых пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ignored_users (
                user_id INTEGER PRIMARY KEY,
                user_name TEXT
            )
        ''')
        # Таблица для статистики активности (пересланных сообщений)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_activity (
                user_id INTEGER PRIMARY KEY,
                user_name TEXT,
                messages_forwarded INTEGER DEFAULT 0
            )
        ''')
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

def update_user_activity(user_id: int, user_name: str):
    """Обновляет счетчик пересланных сообщений для пользователя в БД."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO user_activity (user_id, user_name) VALUES (?, ?)",
                       (user_id, user_name))
        cursor.execute("UPDATE user_activity SET messages_forwarded = messages_forwarded + 1, user_name = ? WHERE user_id = ?",
                       (user_name, user_id)) # Обновляем имя на всякий случай
        conn.commit()

def get_top_users(limit: int = 10):
    """Возвращает топ пользователей по количеству пересланных сообщений."""
    top_users = []
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, user_name, messages_forwarded FROM user_activity ORDER BY messages_forwarded DESC LIMIT ?", (limit,))
        top_users = cursor.fetchall()
    return top_users

# --- Глобальная переменная для кэша игнорируемых пользователей ---
# Кэшируем для более быстрого доступа, но источник истины - БД.
ignored_users_cache = get_ignored_users()


# --- Обработчик сообщений для пересылки ---
@dp.message_handler(content_types=types.ContentType.ANY, chat_id=SOURCE_CHAT_IDS)
async def forward_messages(message: types.Message):
    user_id = message.from_user.id
    user_full_name = message.from_user.full_name or f"Пользователь {user_id}"

    # Проверяем кэш игнорируемых пользователей
    if user_id in ignored_users_cache:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Игнорируем сообщение от {user_full_name} ({user_id}) в группе {message.chat.title} ({message.chat.id}).")
        return

    try:
        await bot.copy_message(chat_id=DESTINATION_CHAT_ID,
                               from_chat_id=message.chat.id,
                               message_id=message.message_id)

        # Обновляем статистику активности пользователя
        update_user_activity(user_id, user_full_name)

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Сообщение (ID: {message.message_id}) от {user_full_name} из группы {message.chat.title} ({message.chat.id}) успешно переслано в группу {DESTINATION_CHAT_ID}.")
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Ошибка при пересылке сообщения (ID: {message.message_id}) от {user_full_name} из чата {message.chat.id}: {e}")

# --- Команды для управления списком игнорирования ---

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
        # Пытаемся получить информацию о пользователе из одной из SOURCE_CHAT_IDS
        user_info = None
        for chat_id in SOURCE_CHAT_IDS:
            try:
                member = await bot.get_chat_member(chat_id, target_user_id)
                user_info = member.user
                break
            except Exception:
                continue # Пользователя нет в этой группе или ошибка

        user_full_name = user_info.full_name if user_info else f"Неизвестный пользователь (ID: {target_user_id})"

        if target_user_id not in ignored_users_cache:
            add_ignored_user(target_user_id, user_full_name)
            ignored_users_cache[target_user_id] = user_full_name # Обновляем кэш
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
            user_full_name = ignored_users_cache.pop(target_user_id) # Удаляем из кэша
            remove_ignored_user(target_user_id) # Удаляем из БД
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

    # Перезагружаем кэш, чтобы убедиться, что он актуален с БД
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

# --- Новая команда: Топ пользователей ---
@dp.message_handler(commands=['top_users'], chat_type=types.ChatType.PRIVATE)
async def show_top_users(message: types.Message):
    """
    Показывает топ пользователей по количеству пересланных сообщений.
    Доступно только администраторам бота в приватном чате.
    """
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("У вас нет прав для выполнения этой команды.")
        return

    top_list = get_top_users()

    if not top_list:
        await message.reply("Статистика активности пока пуста.")
        return

    response = "📊 **Топ пользователей по пересланным сообщениям:**\n\n"
    for i, (user_id, user_name, forwarded_count) in enumerate(top_list):
        response += f"{i+1}. **{user_name}** (ID: `{user_id}`) - `{forwarded_count}` сообщений\n"

    await message.reply(response, parse_mode=types.ParseMode.MARKDOWN)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Показан топ пользователей.")


async def main():
    """
    Главная функция запуска бота.
    """
    init_db() # Инициализируем БД при запуске
    print("Бот запускается...")
    await dp.start_polling()

if __name__ == '__main__':
    asyncio.run(main())
    print("Бот остановлен.")
