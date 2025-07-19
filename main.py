import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from dotenv import load_dotenv
import pytz

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
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS").split(",")))
SOURCE_CHAT_IDS = list(map(int, os.getenv("SOURCE_CHAT_IDS").split(",")))
DESTINATION_CHAT_ID = int(os.getenv("DESTINATION_CHAT_ID"))
INACTIVITY_THRESHOLD = timedelta(minutes=int(os.getenv("INACTIVITY_THRESHOLD_MINUTES")))
CHECK_INTERVAL = int(os.getenv("INACTIVITY_CHECK_INTERVAL_SECONDS"))
MORNING_SHIFT_START = int(os.getenv("MORNING_SHIFT_START_HOUR"))
MORNING_SHIFT_END = int(os.getenv("MORNING_SHIFT_END_HOUR"))
EVENING_SHIFT_START = int(os.getenv("EVENING_SHIFT_START_HOUR"))
EVENING_SHIFT_END = int(os.getenv("EVENING_SHIFT_END_HOUR"))

TIMEZONE = pytz.timezone("Europe/Moscow")

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Глобальные переменные для хранения данных
workers_data: Dict[int, Dict[str, datetime]] = {}
workers_zones: Dict[int, str] = {}
workers_days_off: Dict[int, List[str]] = {}

# Клавиатура для админа
def get_admin_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(
        text="📊 Отчет за неделю",
        callback_data="week_report"
    ))
    keyboard.add(types.InlineKeyboardButton(
        text="➕ Добавить выходной",
        callback_data="add_day_off"
    ))
    return keyboard

# Обработчик команды /start
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    if message.from_user.id in ADMIN_IDS:
        await message.answer("👑 Панель админа", reply_markup=get_admin_keyboard())
    else:
        await message.answer("📋 Отправляйте фото с подписью 'Зона А' или 'Зона Б'")

# Обработчик сообщений с фото
@dp.message_handler(
    lambda message: message.photo and 
    message.chat.id in SOURCE_CHAT_IDS and 
    message.from_user.id not in ADMIN_IDS
)
async def handle_photo_with_zone(message: types.Message):
    user = message.from_user
    caption = message.caption or ""
    
    zone = None
    if "зона а" in caption.lower():
        zone = "zone_a"
    elif "зона б" in caption.lower():
        zone = "zone_b"
    
    if not zone:
        await message.reply("❌ Укажите зону в подписи (например, 'Зона А')")
        return
    
    workers_data[user.id] = {
        "last_report": datetime.now(TIMEZONE),
        "zone": zone
    }
    workers_zones[user.id] = zone
    
    await message.reply(f"✅ Отчет принят! Зона: {zone.split('_')[1].upper()}")

# Обработчик кнопки "Отчет за неделю"
@dp.callback_query_handler(lambda c: c.data == "week_report")
async def week_report_handler(callback_query: types.CallbackQuery):
    if callback_query.from_user.id not in ADMIN_IDS:
        await callback_query.answer("🚫 Доступ запрещен")
        return
    
    today = datetime.now(TIMEZONE)
    week_ago = today - timedelta(days=7)
    
    report = f"📅 <b>Отчет за неделю</b> ({week_ago.strftime('%d.%m')} - {today.strftime('%d.%m')})\n\n"
    
    for user_id, zone in workers_zones.items():
        try:
            user = await bot.get_chat(user_id)
            username = user.username or user.full_name
            days_off = workers_days_off.get(user_id, [])
            
            report += (
                f"👤 <b>{username}</b>\n"
                f"📍 Зона: {zone.split('_')[1].upper()}\n"
                f"📅 Последний отчет: {workers_data[user_id]['last_report'].strftime('%d.%m %H:%M')}\n"
                f"🏖 Выходных: {len(days_off)}\n\n"
            )
        except Exception as e:
            logger.error(f"Ошибка при получении данных пользователя {user_id}: {e}")
    
    await callback_query.message.edit_text(report, parse_mode="HTML")

# Состояния для FSM
class AdminStates(StatesGroup):
    waiting_for_worker = State()
    waiting_for_date = State()

# Обработчик кнопки "Добавить выходной"
@dp.callback_query_handler(lambda c: c.data == "add_day_off", state="*")
async def add_day_off_handler(callback_query: types.CallbackQuery):
    if callback_query.from_user.id not in ADMIN_IDS:
        await callback_query.answer("🚫 Доступ запрещен")
        return
    
    keyboard = types.InlineKeyboardMarkup()
    for user_id in workers_zones.keys():
        try:
            user = await bot.get_chat(user_id)
            keyboard.add(types.InlineKeyboardButton(
                text=user.full_name,
                callback_data=f"select_worker_{user_id}"
            ))
        except:
            continue
    
    await callback_query.message.edit_text(
        "Выберите рабочего для добавления выходного:",
        reply_markup=keyboard
    )
    await AdminStates.waiting_for_worker.set()

# Обработчик выбора рабочего
@dp.callback_query_handler(lambda c: c.data.startswith("select_worker_"), state=AdminStates.waiting_for_worker)
async def select_worker_handler(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = int(callback_query.data.split("_")[2])
    await state.update_data(worker_id=user_id)
    
    await callback_query.message.edit_text(
        "Введите дату выходного в формате ДД.ММ (например, 15.05):"
    )
    await AdminStates.waiting_for_date.set()

# Обработчик ввода даты
@dp.message_handler(state=AdminStates.waiting_for_date)
async def process_date(message: types.Message, state: FSMContext):
    try:
        day, month = map(int, message.text.split('.'))
        year = datetime.now().year
        date_obj = datetime(year, month, day)
        date_str = date_obj.strftime("%Y-%m-%d")
        
        data = await state.get_data()
        user_id = data['worker_id']
        
        if user_id not in workers_days_off:
            workers_days_off[user_id] = []
        
        if date_str not in workers_days_off[user_id]:
            workers_days_off[user_id].append(date_str)
            await message.answer(f"✅ Выходной на {message.text} добавлен")
        else:
            await message.answer("⚠️ Уже есть выходной на эту дату")
        
    except Exception as e:
        await message.answer("❌ Неверный формат даты. Используйте ДД.ММ")
        return
    
    await state.finish()

# Проверка неактивности
async def check_inactivity():
    now = datetime.now(TIMEZONE)
    current_hour = now.hour
    
    if MORNING_SHIFT_START <= current_hour < MORNING_SHIFT_END:
        current_shift = "🌅 Утренняя смена"
    elif EVENING_SHIFT_START <= current_hour < EVENING_SHIFT_END:
        current_shift = "🌃 Вечерняя смена"
    else:
        return
    
    inactive_workers = []
    
    for user_id, data in workers_data.items():
        today_str = now.strftime("%Y-%m-%d")
        if user_id in workers_days_off and today_str in workers_days_off[user_id]:
            continue
        
        last_report = data["last_report"]
        zone = data["zone"]
        
        if (now - last_report) > INACTIVITY_THRESHOLD:
            inactive_workers.append((user_id, zone))
    
    if inactive_workers:
        report_msg = f"⚠️ <b>Неактивные рабочие ({current_shift})</b>:\n\n"
        for user_id, zone in inactive_workers:
            try:
                user = await bot.get_chat(user_id)
                username = user.username or user.full_name
                inactive_min = int((now - workers_data[user_id]["last_report"]).total_seconds() / 60)
                report_msg += f"👤 {username} | Зона {zone.split('_')[1].upper()} | ❌ {inactive_min} мин.\n"
            except Exception as e:
                logger.error(f"Ошибка при получении данных пользователя {user_id}: {e}")
        
        await bot.send_message(
            chat_id=DESTINATION_CHAT_ID,
            text=report_msg,
            parse_mode="HTML"
        )

# Запуск периодической проверки
async def on_startup(dp):
    from aiogram import executor
    import asyncio
    
    async def periodic_check():
        while True:
            await check_inactivity()
            await asyncio.sleep(CHECK_INTERVAL)
    
    asyncio.create_task(periodic_check())

if __name__ == "__main__":
    executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
