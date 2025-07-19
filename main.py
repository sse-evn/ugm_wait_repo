import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List
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

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
ZONE_A_CHAT_ID = int(os.getenv("ZONE_A_CHAT_ID"))  # -100123456789
ZONE_B_CHAT_ID = int(os.getenv("ZONE_B_CHAT_ID"))  # -100987654321
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))    # Для уведомлений

# Временные настройки (Алматы UTC+5)
TIMEZONE = pytz.timezone("Asia/Almaty")
MORNING_SHIFT = (7, 15)    # с 07:00 до 15:00
EVENING_SHIFT = (15, 23)   # с 15:00 до 23:00
CHECK_INTERVAL = 2700       # 45 минут в секундах

# Хранение данных
zone_a_workers: Dict[int, datetime] = {}  # {user_id: last_report_time}
zone_b_workers: Dict[int, datetime] = {}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

async def get_active_users(chat_id: int) -> List[int]:
    """Получаем список участников чата"""
    try:
        members = await bot.get_chat_administrators(chat_id)
        return [member.user.id for member in members if not member.user.is_bot]
    except Exception as e:
        logger.error(f"Ошибка получения участников чата {chat_id}: {e}")
        return []

async def check_reports():
    """Проверка отчетов по зонам"""
    now = datetime.now(TIMEZONE)
    current_hour = now.hour
    
    # Определяем текущую смену
    if MORNING_SHIFT[0] <= current_hour < MORNING_SHIFT[1]:
        shift_name = "🌅 Утренняя смена"
        active_zone = zone_a_workers
        inactive_zone = zone_b_workers
        chat_id = ZONE_A_CHAT_ID
    elif EVENING_SHIFT[0] <= current_hour < EVENING_SHIFT[1]:
        shift_name = "🌃 Вечерняя смена"
        active_zone = zone_b_workers
        inactive_zone = zone_a_workers
        chat_id = ZONE_B_CHAT_ID
    else:
        return  # Нерабочее время
    
    # Получаем текущих участников чата
    current_members = await get_active_users(chat_id)
    
    # Проверяем неактивных
    inactive_users = []
    for user_id in current_members:
        last_report = active_zone.get(user_id)
        if not last_report or (now - last_report) > timedelta(minutes=45):
            inactive_users.append(user_id)
    
    # Отправляем уведомление
    if inactive_users:
        message = f"⚠️ {shift_name} - нет отчетов от:\n"
        for user_id in inactive_users:
            try:
                user = await bot.get_chat(user_id)
                username = user.username or user.first_name
                last_report_time = active_zone.get(user_id, "никогда")
                if isinstance(last_report_time, datetime):
                    last_report_time = last_report_time.strftime('%H:%M')
                message += f"• {username} (последний: {last_report_time})\n"
            except Exception as e:
                logger.error(f"Ошибка получения данных пользователя {user_id}: {e}")
        
        await bot.send_message(chat_id, message)

@dp.message_handler(content_types=['photo'])
async def handle_photo(message: types.Message):
    """Фиксация фото-отчетов"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    now = datetime.now(TIMEZONE)
    
    if chat_id == ZONE_A_CHAT_ID:
        zone_a_workers[user_id] = now
    elif chat_id == ZONE_B_CHAT_ID:
        zone_b_workers[user_id] = now

async def scheduler():
    """Планировщик проверок"""
    while True:
        await check_reports()
        await asyncio.sleep(CHECK_INTERVAL)

async def on_startup(dp):
    """Запуск при старте"""
    asyncio.create_task(scheduler())
    await bot.send_message(ADMIN_CHAT_ID, "🔍 Бот начал мониторинг отчетов")

if __name__ == "__main__":
    executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
