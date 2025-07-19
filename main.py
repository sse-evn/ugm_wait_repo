import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from dotenv import load_dotenv
import pytz
import asyncio

# 1. Настройка логирования (добавим больше деталей)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG  # Изменим на DEBUG для подробных логов
)
logger = logging.getLogger(__name__)

# 2. Загрузка конфигурации с проверкой
load_dotenv()
required_vars = [
    "BOT_TOKEN",
    "ZONE_A_CHAT_ID",
    "ZONE_B_CHAT_ID",
    "REPORT_CHAT_ID",
    "ADMIN_IDS"
]

for var in required_vars:
    if not os.getenv(var):
        logger.error(f"❌ Отсутствует обязательная переменная: {var}")
        exit(1)

# 3. Конфигурация с дефолтными значениями
config = {
    "BOT_TOKEN": os.getenv("BOT_TOKEN"),
    "ZONE_A_CHAT_ID": int(os.getenv("ZONE_A_CHAT_ID")),
    "ZONE_B_CHAT_ID": int(os.getenv("ZONE_B_CHAT_ID")),
    "REPORT_CHAT_ID": int(os.getenv("REPORT_CHAT_ID")),
    "ADMIN_IDS": list(map(int, os.getenv("ADMIN_IDS").split(","))),
    "TIMEZONE": pytz.timezone(os.getenv("TIMEZONE", "Asia/Almaty")),
    "CHECK_INTERVAL": int(os.getenv("CHECK_INTERVAL", "5")),
    "INACTIVITY_THRESHOLD": int(os.getenv("INACTIVITY_THRESHOLD", "30")),
    "MORNING_SHIFT": (int(os.getenv("MORNING_SHIFT_START", "7")), int(os.getenv("MORNING_SHIFT_END", "15"))),
    "EVENING_SHIFT": (int(os.getenv("EVENING_SHIFT_START", "15")), int(os.getenv("EVENING_SHIFT_END", "23"))),
    "ZONE_NAMES": {
        'A': os.getenv("ZONE_A_NAME", "Отчёты скаутов Е.О.М"),
        'B': os.getenv("ZONE_B_NAME", "10 аумақ-зона")
    }
}

logger.info("✅ Конфигурация загружена успешно")

# 4. Инициализация бота с обработкой ошибок
try:
    bot = Bot(token=config["BOT_TOKEN"])
    storage = MemoryStorage()
    dp = Dispatcher(bot, storage=storage)
    logger.info("🤖 Бот инициализирован")
except Exception as e:
    logger.error(f"❌ Ошибка инициализации бота: {e}")
    exit(1)

# 5. Хранение данных (с защитой от конкурентного доступа)
class WorkerData:
    def __init__(self):
        self.data: Dict[int, Dict[str, datetime]] = {}
        self.lock = asyncio.Lock()

    async def update(self, user_id: int, zone: str, shift: str):
        async with self.lock:
            self.data[user_id] = {
                'zone': zone,
                'shift': shift,
                'last_report': datetime.now(config["TIMEZONE"])
            }

    async def get_inactive(self, zone: str, shift: str, threshold: int) -> List[int]:
        async with self.lock:
            now = datetime.now(config["TIMEZONE"])
            return [
                user_id for user_id, data in self.data.items()
                if data['zone'] == zone and data['shift'] == shift and
                (now - data['last_report']).total_seconds() > threshold
            ]

workers_data = WorkerData()

# 6. Определение текущей смены с логированием
def get_current_shift() -> Optional[str]:
    now = datetime.now(config["TIMEZONE"])
    current_hour = now.hour
    logger.debug(f"Текущее время: {now} (час: {current_hour})")

    if config["MORNING_SHIFT"][0] <= current_hour < config["MORNING_SHIFT"][1]:
        logger.debug("Активна утренняя смена")
        return 'morning'
    elif config["EVENING_SHIFT"][0] <= current_hour < config["EVENING_SHIFT"][1]:
        logger.debug("Активна вечерняя смена")
        return 'evening'
    
    logger.debug("Сейчас нерабочее время")
    return None

# 7. Улучшенная проверка отчетов
async def check_reports():
    logger.info("🔍 Начало проверки отчетов")
    
    current_shift = get_current_shift()
    if not current_shift:
        return

    for zone in ['A', 'B']:
        chat_id = config[f"ZONE_{zone}_CHAT_ID"]
        zone_name = config["ZONE_NAMES"][zone]
        
        try:
            members = await bot.get_chat_administrators(chat_id)
            current_members = [
                m.user.id for m in members 
                if not m.user.is_bot and m.user.id not in config["ADMIN_IDS"]
            ]
            logger.debug(f"В чате {zone_name} найдено {len(current_members)} рабочих")
        except Exception as e:
            logger.error(f"Ошибка доступа к чату {zone_name}: {e}")
            await notify_admins(f"🚨 Ошибка доступа к чату {zone_name}")
            continue

        inactive_users = await workers_data.get_inactive(
            zone, current_shift, config["INACTIVITY_THRESHOLD"]
        )

        if inactive_users:
            message = (
                f"⚠️ <b>{zone_name} ({current_shift} смена)</b>\n"
                f"Нет отчетов более {config['INACTIVITY_THRESHOLD']} сек от:\n\n"
            )
            
            for user_id in inactive_users:
                try:
                    user = await bot.get_chat(user_id)
                    username = user.username or user.first_name
                    message += f"• {username}\n"
                except Exception as e:
                    logger.error(f"Ошибка получения данных пользователя {user_id}: {e}")
            
            await bot.send_message(config["REPORT_CHAT_ID"], message, parse_mode='HTML')
            logger.info(f"Отправлено уведомление о {len(inactive_users)} неактивных пользователях в {zone_name}")

# 8. Уведомление админов с повторными попытками
async def notify_admins(message: str, max_retries: int = 3):
    for admin_id in config["ADMIN_IDS"]:
        for attempt in range(max_retries):
            try:
                await bot.send_message(admin_id, message)
                logger.debug(f"Уведомление отправлено админу {admin_id}")
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")
                await asyncio.sleep(1)

# 9. Обработчик фото с улучшенной валидацией
@dp.message_handler(content_types=types.ContentType.PHOTO)
async def handle_photo(message: types.Message):
    try:
        user_id = message.from_user.id
        chat_id = message.chat.id
        
        if chat_id not in [config["ZONE_A_CHAT_ID"], config["ZONE_B_CHAT_ID"]]:
            logger.debug(f"Фото из нерелевантного чата {chat_id}")
            return
            
        if user_id in config["ADMIN_IDS"]:
            logger.debug(f"Фото от админа {user_id}")
            return

        zone = 'A' if chat_id == config["ZONE_A_CHAT_ID"] else 'B'
        current_shift = get_current_shift()
        
        if current_shift:
            await workers_data.update(user_id, zone, current_shift)
            logger.info(f"Зарегистрирован отчет от {user_id} в {zone} ({current_shift})")
    except Exception as e:
        logger.error(f"Ошибка обработки фото: {e}")

# 10. Запуск планировщика с обработкой ошибок
async def scheduler():
    while True:
        try:
            await check_reports()
        except Exception as e:
            logger.error(f"Ошибка в планировщике: {e}")
            await notify_admins(f"🔥 Критическая ошибка в планировщике: {str(e)}")
        await asyncio.sleep(config["CHECK_INTERVAL"])

# 11. Запуск бота с обработкой ошибок
async def on_startup(dp):
    try:
        asyncio.create_task(scheduler())
        await notify_admins("🤖 Бот успешно запущен!")
        logger.info("Бот запущен и готов к работе")
    except Exception as e:
        logger.error(f"Ошибка при запуске: {e}")
        exit(1)

if __name__ == "__main__":
    try:
        executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
    except Exception as e:
        logger.error(f"Фатальная ошибка: {e}")
