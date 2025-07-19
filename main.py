import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import pytz
from dotenv import load_dotenv
from telegram import Update, User
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackContext,
)

# Загрузка конфигурации
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация из .env
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS").split(",")))
SOURCE_CHAT_IDS = list(map(int, os.getenv("SOURCE_CHAT_IDS").split(",")))
DESTINATION_CHAT_ID = int(os.getenv("DESTINATION_CHAT_ID"))
INACTIVITY_THRESHOLD = timedelta(minutes=int(os.getenv("INACTIVITY_THRESHOLD_MINUTES")))
CHECK_INTERVAL = int(os.getenv("INACTIVITY_CHECK_INTERVAL_SECONDS"))
MORNING_SHIFT_START = int(os.getenv("MORNING_SHIFT_START_HOUR"))
MORNING_SHIFT_END = int(os.getenv("MORNING_SHIFT_END_HOUR"))
EVENING_SHIFT_START = int(os.getenv("EVENING_SHIFT_START_HOUR"))
EVENING_SHIFT_END = int(os.getenv("EVENING_SHIFT_END_HOUR"))

# Глобальные переменные для хранения данных
workers_data: Dict[int, Dict[str, datetime]] = {}  # {user_id: {"last_report": datetime, "zone": str}}
workers_zones: Dict[int, str] = {}  # {user_id: "zone_a" или "zone_b"}

# Временная зона (можно изменить на свою)
TIMEZONE = pytz.timezone("Europe/Moscow")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await update.message.reply_text("Бот для контроля отчетов рабочих активирован!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик входящих сообщений"""
    user = update.effective_user
    message = update.effective_message
    chat_id = update.effective_chat.id

    # Игнорируем сообщения не из нужных чатов и от админов
    if chat_id not in SOURCE_CHAT_IDS or user.id in ADMIN_IDS:
        return

    # Проверяем, есть ли фото в сообщении
    if not message.photo:
        return

    # Определяем зону (A или B) из текста сообщения
    zone = None
    if "зона а" in message.caption.lower() if message.caption else "":
        zone = "zone_a"
    elif "зона б" in message.caption.lower() if message.caption else "":
        zone = "zone_b"

    if not zone:
        return  # Игнорируем сообщения без указания зоны

    # Обновляем данные о рабочем
    workers_data[user.id] = {
        "last_report": datetime.now(TIMEZONE),
        "zone": zone
    }
    workers_zones[user.id] = zone

async def check_inactivity(context: CallbackContext):
    """Проверка неактивности рабочих"""
    now = datetime.now(TIMEZONE)
    current_hour = now.hour

    # Определяем текущую смену
    if MORNING_SHIFT_START <= current_hour < MORNING_SHIFT_END:
        current_shift = "утренняя"
    elif EVENING_SHIFT_START <= current_hour < EVENING_SHIFT_END:
        current_shift = "вечерняя"
    else:
        return  # Вне рабочего времени

    inactive_workers = []
    
    for user_id, data in workers_data.items():
        # Проверяем только рабочих в текущей смене
        last_report = data["last_report"]
        zone = data["zone"]
        
        if (now - last_report) > INACTIVITY_THRESHOLD:
            inactive_workers.append((user_id, zone))

    if inactive_workers:
        message = f"⚠️ Неактивные рабочие ({current_shift} смена):\n"
        for user_id, zone in inactive_workers:
            user = await context.bot.get_chat(user_id)
            username = user.username or user.full_name
            inactive_minutes = int((now - workers_data[user_id]["last_report"]).total_seconds() / 60)
            message += f"• {username} (Зона {zone[-1].upper()}) - {inactive_minutes} мин. без отчета\n"
        
        await context.bot.send_message(chat_id=DESTINATION_CHAT_ID, text=message)

def is_working_time(now: datetime) -> bool:
    """Проверяем, рабочее ли сейчас время"""
    current_hour = now.hour
    return (MORNING_SHIFT_START <= current_hour < MORNING_SHIFT_END) or \
           (EVENING_SHIFT_START <= current_hour < EVENING_SHIFT_END)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Ошибка: {context.error}", exc_info=context.error)

def main():
    """Запуск бота"""
    application = Application.builder().token(BOT_TOKEN).build()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start))

    # Обработчик сообщений с фото
    application.add_handler(MessageHandler(filters.PHOTO & filters.Chat(SOURCE_CHAT_IDS), handle_message))

    # Периодическая проверка неактивности
    job_queue = application.job_queue
    job_queue.run_repeating(check_inactivity, interval=CHECK_INTERVAL, first=10)

    # Обработчик ошибок
    application.add_error_handler(error_handler)

    # Запуск бота
    application.run_polling()

if __name__ == "__main__":
    main()
