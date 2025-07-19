import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv
import pytz
from enum import Enum

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

# Глобальные переменные для хранения данных
workers_data: Dict[int, Dict[str, datetime]] = {}  # {user_id: {"last_report": datetime, "zone": str}}
workers_zones: Dict[int, str] = {}  # {user_id: "zone_a" или "zone_b"}
workers_days_off: Dict[int, List[str]] = {}  # {user_id: ["2024-05-20", "2024-05-21"]}

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Состояния для FSM
class AdminStates(StatesGroup):
    waiting_for_day_off = State()

# Кнопки для админа
def get_admin_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Отчет за неделю", callback_data="week_report")
    builder.button(text="➕ Добавить выходной", callback_data="add_day_off")
    builder.adjust(1)
    return builder.as_markup()

# Обработчик команды /start
@dp.message(Command("start"))
async def cmd_start(message: Message):
    if message.from_user.id in ADMIN_IDS:
        await message.answer("👑 Панель админа", reply_markup=get_admin_keyboard())
    else:
        await message.answer("📋 Отправляйте фото с подписью 'Зона А' или 'Зона Б'")

# Обработчик сообщений с фото
@dp.message(F.photo & F.chat.id.in_(SOURCE_CHAT_IDS) & ~F.from_user.id.in_(ADMIN_IDS))
async def handle_photo_with_zone(message: Message):
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
@dp.callback_query(F.data == "week_report")
async def week_report_handler(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("🚫 Доступ запрещен")
        return
    
    today = datetime.now(TIMEZONE)
    week_ago = today - timedelta(days=7)
    
    report = "📅 <b>Отчет за неделю</b> ({} - {})\n\n".format(
        week_ago.strftime("%d.%m"), 
        today.strftime("%d.%m")
    )
    
    # Собираем данные по рабочим
    workers_info = {}
    for user_id, zone in workers_zones.items():
        try:
            user = await bot.get_chat(user_id)
            username = user.username or user.full_name
            days_off = workers_days_off.get(user_id, [])
            
            workers_info[username] = {
                "zone": zone.split("_")[1].upper(),
                "days_off": len(days_off),
                "last_report": workers_data[user_id]["last_report"].strftime("%d.%m %H:%M")
            }
        except Exception as e:
            logger.error(f"Ошибка при получении данных пользователя {user_id}: {e}")
    
    # Формируем отчет
    for username, data in workers_info.items():
        report += (
            f"👤 <b>{username}</b>\n"
            f"📍 Зона: {data['zone']}\n"
            f"📅 Последний отчет: {data['last_report']}\n"
            f"🏖 Выходных: {data['days_off']}\n\n"
        )
    
    await callback.message.edit_text(report, parse_mode="HTML")

# Обработчик кнопки "Добавить выходной"
@dp.callback_query(F.data == "add_day_off")
async def add_day_off_handler(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("🚫 Доступ запрещен")
        return
    
    # Получаем список рабочих для выбора
    builder = InlineKeyboardBuilder()
    for user_id in workers_zones.keys():
        try:
            user = await bot.get_chat(user_id)
            builder.button(text=user.full_name, callback_data=f"day_off_{user_id}")
        except:
            continue
    
    builder.adjust(2)
    await callback.message.edit_text(
        "Выберите рабочего для добавления выходного:",
        reply_markup=builder.as_markup()
    )
    await state.set_state(AdminStates.waiting_for_day_off)

# Обработчик выбора рабочего для выходного
@dp.callback_query(F.data.startswith("day_off_"), AdminStates.waiting_for_day_off)
async def select_worker_for_day_off(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[2])
    today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
    
    if user_id not in workers_days_off:
        workers_days_off[user_id] = []
    
    if today not in workers_days_off[user_id]:
        workers_days_off[user_id].append(today)
        await callback.answer("✅ Выходной добавлен")
    else:
        await callback.answer("⚠️ Уже есть выходной на сегодня")
    
    await state.clear()
    await callback.message.delete()

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
        # Проверяем, не выходной ли сегодня у рабочего
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

# Запуск бота
async def on_startup():
    from aiogram.utils import executor
    scheduler = executor.start(dp)
    scheduler.add_job(
        check_inactivity,
        "interval",
        seconds=CHECK_INTERVAL,
        timezone=TIMEZONE
    )

if __name__ == "__main__":
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
