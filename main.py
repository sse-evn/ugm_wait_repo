import os
import logging
import sys
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from dotenv import load_dotenv
import pytz
import fcntl

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка конфигурации
load_dotenv()

# Проверка обязательных переменных
required_vars = [
    'BOT_TOKEN',
    'ZONE_A_CHAT_ID',
    'ZONE_B_CHAT_ID',
    'REPORT_CHAT_ID',
    'ADMIN_IDS'
]

for var in required_vars:
    if not os.getenv(var):
        logger.error(f'❌ Отсутствует переменная: {var}')
        exit(1)

# Конфигурация
config = {
    'BOT_TOKEN': os.getenv('BOT_TOKEN'),
    'ZONE_A_CHAT_ID': int(os.getenv('ZONE_A_CHAT_ID')),
    'ZONE_B_CHAT_ID': int(os.getenv('ZONE_B_CHAT_ID')),
    'REPORT_CHAT_ID': int(os.getenv('REPORT_CHAT_ID')),
    'ADMIN_IDS': list(map(int, os.getenv('ADMIN_IDS').split(','))),
    'TIMEZONE': pytz.timezone(os.getenv('TIMEZONE', 'Asia/Almaty')),
    'CHECK_INTERVAL': int(os.getenv('CHECK_INTERVAL', '5')),
    'INACTIVITY_THRESHOLD': int(os.getenv('INACTIVITY_THRESHOLD', '30')),
    'MORNING_SHIFT': (int(os.getenv('MORNING_SHIFT_START', '7')), int(os.getenv('MORNING_SHIFT_END', '15'))),
    'EVENING_SHIFT': (int(os.getenv('EVENING_SHIFT_START', '15')), int(os.getenv('EVENING_SHIFT_END', '23'))),
    'ZONE_NAMES': {
        'A': os.getenv('ZONE_A_NAME', 'Отчёты скаутов Е.О.М'),
        'B': os.getenv('ZONE_B_NAME', '10 аумақ-зона')
    }
}

# Блокировка файла для предотвращения множественных запусков
def acquire_lock():
    lock_file = 'bot.lock'
    try:
        fd = os.open(lock_file, os.O_CREAT | os.O_WRONLY)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except (IOError, OSError):
        logger.error('❌ Бот уже запущен! Завершаю работу.')
        sys.exit(1)

# Инициализация бота
try:
    bot = Bot(token=config['BOT_TOKEN'])
    storage = MemoryStorage()
    dp = Dispatcher(bot, storage=storage)
    logger.info("🤖 Бот инициализирован")
except Exception as e:
    logger.error(f"❌ Ошибка инициализации бота: {e}")
    exit(1)

# Хранение данных
workers_data: Dict[int, Dict[str, datetime]] = {}

def get_current_shift() -> Optional[str]:
    now = datetime.now(config['TIMEZONE']).hour
    if config['MORNING_SHIFT'][0] <= now < config['MORNING_SHIFT'][1]:
        return 'morning'
    elif config['EVENING_SHIFT'][0] <= now < config['EVENING_SHIFT'][1]:
        return 'evening'
    return None

async def check_reports():
    current_shift = get_current_shift()
    if not current_shift:
        return

    now = datetime.now(config['TIMEZONE'])
    
    for zone in ['A', 'B']:
        chat_id = config[f'ZONE_{zone}_CHAT_ID']
        
        try:
            members = await bot.get_chat_administrators(chat_id)
            current_members = [m.user.id for m in members if not m.user.is_bot and m.user.id not in config['ADMIN_IDS']]
        except Exception as e:
            logger.error(f'Ошибка доступа к чату {zone}: {e}')
            continue

        inactive_users = []
        for user_id in current_members:
            user_data = workers_data.get(user_id, {})
            if user_data.get('zone') == zone and user_data.get('shift') == current_shift:
                last_report = user_data.get('last_report')
                if not last_report or (now - last_report).total_seconds() > config['INACTIVITY_THRESHOLD']:
                    inactive_users.append(user_id)

        if inactive_users:
            message = f"⚠️ <b>{config['ZONE_NAMES'][zone]} ({current_shift} смена)</b>\nНет отчетов:\n"
            for user_id in inactive_users:
                try:
                    user = await bot.get_chat(user_id)
                    username = user.username or user.first_name
                    last_time = workers_data.get(user_id, {}).get('last_report', 'никогда')
                    if isinstance(last_time, datetime):
                        last_time = last_time.strftime('%H:%M:%S')
                    message += f"• {username} (последний: {last_time})\n"
                except:
                    continue
            
            try:
                await bot.send_message(config['REPORT_CHAT_ID'], message, parse_mode='HTML')
            except Exception as e:
                logger.error(f'Ошибка отправки сообщения: {e}')

@dp.message_handler(content_types=['photo'])
async def handle_photo(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if chat_id not in [config['ZONE_A_CHAT_ID'], config['ZONE_B_CHAT_ID']] or user_id in config['ADMIN_IDS']:
        return

    zone = 'A' if chat_id == config['ZONE_A_CHAT_ID'] else 'B'
    current_shift = get_current_shift()
    
    if current_shift:
        workers_data[user_id] = {
            'zone': zone,
            'shift': current_shift,
            'last_report': datetime.now(config['TIMEZONE'])
        }
        logger.info(f'Принят отчет от {user_id} в {zone}')

async def scheduler():
    while True:
        try:
            await check_reports()
            await asyncio.sleep(config['CHECK_INTERVAL'])
        except Exception as e:
            logger.error(f'Ошибка в планировщике: {e}')
            await asyncio.sleep(10)

async def on_startup(_):
    asyncio.create_task(scheduler())
    try:
        await bot.send_message(config['ADMIN_IDS'][0], '🤖 Бот запущен и начал мониторинг')
    except Exception as e:
        logger.error(f'Не удалось отправить уведомление админу: {e}')

if __name__ == '__main__':
    lock_fd = acquire_lock()  # Получаем блокировку
    
    try:
        executor.start_polling(
            dp,
            on_startup=on_startup,
            skip_updates=True,
            timeout=60,  # Увеличиваем таймаут
            relax=1  # Задержка между запросами
        )
    except Exception as e:
        logger.error(f'Фатальная ошибка: {e}')
    finally:
        # Освобождаем блокировку при завершении
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
        try:
            os.remove('bot.lock')
        except:
            pass
        logger.info('Бот завершил работу')
