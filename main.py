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

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
ZONE_A_CHAT_ID = int(os.getenv("ZONE_A_CHAT_ID"))  # Чат "Отчёты скаутов Е.О.М"
ZONE_B_CHAT_ID = int(os.getenv("ZONE_B_CHAT_ID"))  # Чат "10 аумақ-зона"
REPORT_CHAT_ID = -1002853755767  # Группа для уведомлений

# Временные настройки (Алматы UTC+5)
TIMEZONE = pytz.timezone("Asia/Almaty")
SHIFTS = {
    'morning': (7, 15),   # Утренняя смена 07:00-15:00
    'evening': (15, 23)   # Вечерняя смена 15:00-23:00
}
CHECK_INTERVAL = 2700      # 45 минут в секундах

# Названия зон
ZONE_NAMES = {
    'A': "Отчёты скаутов Е.О.М",
    'B': "10 аумақ-зона"
}

# Хранение данных
workers_data: Dict[int, Dict[str, datetime]] = {}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

def get_current_shift() -> Tuple[str, str]:
    """Определяем текущую смену"""
    now = datetime.now(TIMEZONE)
    current_hour = now.hour
    
    shift_name = 'morning' if SHIFTS['morning'][0] <= current_hour < SHIFTS['morning'][1] else 'evening'
    return shift_name

async def check_reports():
    """Проверка отчетов по зонам и сменам"""
    now = datetime.now(TIMEZONE)
    current_shift = get_current_shift()
    
    for zone in ['A', 'B']:
        chat_id = ZONE_A_CHAT_ID if zone == 'A' else ZONE_B_CHAT_ID
        
        try:
            members = await bot.get_chat_administrators(chat_id)
            current_members = [m.user.id for m in members if not m.user.is_bot]
        except Exception as e:
            logger.error(f"Ошибка получения участников чата {zone}: {e}")
            continue
        
        inactive_users = []
        for user_id in current_members:
            user_data = workers_data.get(user_id, {})
            
            if user_data.get('zone') == zone and user_data.get('shift') == current_shift:
                last_report = user_data.get('last_report')
                if not last_report or (now - last_report) > timedelta(minutes=45):
                    inactive_users.append(user_id)
        
        if inactive_users:
            message = (
                f"⚠️ <b>{ZONE_NAMES[zone]} ({current_shift.capitalize()} смена)</b>\n"
                f"Нет отчетов от:\n\n"
            )
            
            for user_id in inactive_users:
                try:
                    user = await bot.get_chat(user_id)
                    username = user.username or user.first_name
                    last_time = workers_data.get(user_id, {}).get('last_report', 'никогда')
                    if isinstance(last_time, datetime):
                        last_time = last_time.strftime('%d.%m %H:%M')
                    message += f"▪️ {username} (последний: {last_time})\n"
                except Exception as e:
                    logger.error(f"Ошибка получения данных пользователя {user_id}: {e}")
            
            await bot.send_message(REPORT_CHAT_ID, message, parse_mode='HTML')

@dp.message_handler(content_types=['photo'])
async def handle_photo(message: types.Message):
    """Фиксация фото-отчетов"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if chat_id not in [ZONE_A_CHAT_ID, ZONE_B_CHAT_ID]:
        return
    
    zone = 'A' if chat_id == ZONE_A_CHAT_ID else 'B'
    current_shift = get_current_shift()
    
    workers_data[user_id] = {
        'zone': zone,
        'shift': current_shift,
        'last_report': datetime.now(TIMEZONE)
    }

async def scheduler():
    """Планировщик проверок"""
    while True:
        await check_reports()
        await asyncio.sleep(CHECK_INTERVAL)

async def on_startup(dp):
    """Запуск при старте"""
    asyncio.create_task(scheduler())
    await bot.send_message(REPORT_CHAT_ID, "🟢 Бот мониторинга отчетов активирован")

if __name__ == "__main__":
    executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
