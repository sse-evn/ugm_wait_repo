import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from aiogram import Bot, Dispatcher, executor, types
from dotenv import load_dotenv
import pytz
import asyncio

# Загрузка конфигурации
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация из .env
BOT_TOKEN = os.getenv("BOT_TOKEN")
ZONE_A_CHAT_ID = int(os.getenv("ZONE_A_CHAT_ID"))  # Чат "Отчёты скаутов Е.О.М"
ZONE_B_CHAT_ID = int(os.getenv("ZONE_B_CHAT_ID"))  # Чат "10 аумақ-зона"
REPORT_CHAT_ID = int(os.getenv("REPORT_CHAT_ID"))  # Группа для уведомлений
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))    # Чат для админов
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS").split(",")))  # ID админов

# Временные настройки из .env
TIMEZONE = pytz.timezone(os.getenv("TIMEZONE", "Asia/Almaty"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "5"))          # Интервал проверки (сек)
INACTIVITY_THRESHOLD = int(os.getenv("INACTIVITY_THRESHOLD", "30"))  # Макс. время без отчета (сек)
MORNING_SHIFT_START = int(os.getenv("MORNING_SHIFT_START", "7"))    # Начало утренней смены
MORNING_SHIFT_END = int(os.getenv("MORNING_SHIFT_END", "15"))       # Конец утренней смены
EVENING_SHIFT_START = int(os.getenv("EVENING_SHIFT_START", "15"))   # Начало вечерней смены
EVENING_SHIFT_END = int(os.getenv("EVENING_SHIFT_END", "23"))       # Конец вечерней смены

# Названия зон
ZONE_NAMES = {
    'A': os.getenv("ZONE_A_NAME", "Отчёты скаутов Е.О.М"),
    'B': os.getenv("ZONE_B_NAME", "10 аумақ-зона")
}

# Хранение данных
workers_data: Dict[int, Dict[str, datetime]] = {}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

def get_current_shift() -> str:
    """Определяем текущую смену"""
    now = datetime.now(TIMEZONE).hour
    if MORNING_SHIFT_START <= now < MORNING_SHIFT_END:
        return 'morning'
    elif EVENING_SHIFT_START <= now < EVENING_SHIFT_END:
        return 'evening'
    return None

async def check_reports():
    """Проверка отчетов"""
    current_shift = get_current_shift()
    if not current_shift:
        return

    now = datetime.now(TIMEZONE)
    
    for zone in ['A', 'B']:
        chat_id = ZONE_A_CHAT_ID if zone == 'A' else ZONE_B_CHAT_ID
        
        try:
            members = await bot.get_chat_administrators(chat_id)
            current_members = [m.user.id for m in members if not m.user.is_bot and m.user.id not in ADMIN_IDS]
        except Exception as e:
            logger.error(f"Ошибка доступа к чату {zone}: {e}")
            await notify_admins(f"🚨 Ошибка в чате {ZONE_NAMES[zone]}")
            continue

        inactive = []
        for user_id in current_members:
            data = workers_data.get(user_id, {})
            if data.get('zone') == zone and data.get('shift') == current_shift:
                last = data.get('last_report')
                if not last or (now - last).total_seconds() > INACTIVITY_THRESHOLD:
                    inactive.append(user_id)

        if inactive:
            msg = f"⚠️ <b>{ZONE_NAMES[zone]} ({current_shift})</b>\nНет отчетов:\n"
            for user_id in inactive:
                try:
                    user = await bot.get_chat(user_id)
                    last = workers_data.get(user_id, {}).get('last_report')
                    sec = int((now - last).total_seconds()) if last else "никогда"
                    msg += f"• {user.first_name} ({sec} сек)\n"
                except Exception as e:
                    logger.error(f"Ошибка пользователя {user_id}: {e}")
            
            await bot.send_message(REPORT_CHAT_ID, msg, parse_mode='HTML')

async def notify_admins(text: str):
    """Уведомление админов"""
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception as e:
            logger.error(f"Ошибка уведомления админа {admin_id}: {e}")

@dp.message_handler(content_types=['photo'])
async def handle_photo(message: types.Message):
    """Обработка фото-отчетов"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if chat_id not in [ZONE_A_CHAT_ID, ZONE_B_CHAT_ID] or user_id in ADMIN_IDS:
        return

    zone = 'A' if chat_id == ZONE_A_CHAT_ID else 'B'
    shift = get_current_shift()
    
    if shift:
        workers_data[user_id] = {
            'zone': zone,
            'shift': shift,
            'last_report': datetime.now(TIMEZONE)
        }

async def scheduler():
    """Фоновая проверка"""
    while True:
        await check_reports()
        await asyncio.sleep(CHECK_INTERVAL)

async def on_startup(_):
    """Запуск бота"""
    asyncio.create_task(scheduler())
    await notify_admins("🤖 Бот запущен и работает")

if __name__ == "__main__":
    executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
