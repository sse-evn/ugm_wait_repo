import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta
from config import config
from database import db
from monitoring import ShiftChecker

# Инициализация бота
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(bot)

async def get_afk_report(minutes_threshold=45):
    """Генерирует отчет о AFK пользователях"""
    afk_users = db.get_afk_users(minutes_threshold)
    if not afk_users:
        return "Сейчас все сотрудники активны!"
    
    report = []
    for user_id, username, last_active in afk_users:
        last_active_dt = datetime.strptime(last_active, "%Y-%m-%d %H:%M:%S")
        afk_duration = datetime.now(config.TIMEZONE) - last_active_dt
        hours, remainder = divmod(afk_duration.seconds, 3600)
        minutes = remainder // 60
        
        duration_str = f"{hours}ч {minutes}м" if hours else f"{minutes}м"
        report.append(f"👤 @{username} - AFK {duration_str} (с {last_active_dt.strftime('%H:%M')})")
    
    shift_name = ShiftChecker.current_shift_name()
    return (
        f"📊 Отчет по AFK ({shift_name} смена, Алматы):\n"
        f"Порог: {minutes_threshold} минут\n\n" +
        "\n".join(report)
)

@dp.message_handler(Command("afk_report"))
async def send_afk_report(message: types.Message):
    """Отправляет текущий отчет по AFK"""
    if not db.is_admin(message.from_user.id):
        return
    
    # Можно указать кастомный порог: /afk_report 30
    try:
        threshold = int(message.get_args()) if message.get_args() else 45
    except ValueError:
        threshold = 45
    
    report = await get_afk_report(threshold)
    await message.reply(report)

@dp.message_handler(Command("user_status"))
async def user_status(message: types.Message):
    """Показывает статус конкретного пользователя"""
    if not db.is_admin(message.from_user.id):
        return
    
    # Формат: /user_status @username
    username = message.get_args().strip("@") if message.get_args() else None
    if not username:
        await message.reply("Укажите username: /user_status @username")
        return
    
    user_data = db.get_user_by_username(username)
    if not user_data:
        await message.reply(f"Пользователь @{username} не найден")
        return
    
    user_id, username, last_active, is_ignored = user_data
    if is_ignored:
        await message.reply(f"👤 @{username} - в игнор-листе")
        return
    
    if not last_active:
        await message.reply(f"👤 @{username} - нет данных о активности")
        return
    
    last_active_dt = datetime.strptime(last_active, "%Y-%m-%d %H:%M:%S")
    afk_duration = datetime.now(config.TIMEZONE) - last_active_dt
    
    hours, remainder = divmod(afk_duration.seconds, 3600)
    minutes = remainder // 60
    duration_str = f"{hours}ч {minutes}м" if hours else f"{minutes}м"
    
    status = "🟢 Активен" if minutes < 45 else "🔴 AFK"
    await message.reply(
        f"👤 @{username}\n"
        f"🕒 Последняя активность: {last_active_dt.strftime('%H:%M')}\n"
        f"⏱ Время AFK: {duration_str}\n"
        f"📊 Статус: {status}"
    )

async def afk_checker():
    """Фоновая задача для проверки AFK"""
    while True:
        if ShiftChecker.is_working_time():
            afk_users = db.get_afk_users(45)
            if afk_users:
                report = await get_afk_report()
                await bot.send_message(config.ADMIN_CHAT_ID, report)
        
        await asyncio.sleep(60)  # Проверка каждую минуту

async def on_startup(dp):
    """Действия при запуске бота"""
    print(f"Бот запущен | Таймзона: {config.TIMEZONE}")
    print(f"Смены: утренняя {config.WORK_SHIFTS[0][0].strftime('%H:%M')}-{config.WORK_SHIFTS[0][1].strftime('%H:%M')}, "
          f"вечерняя {config.WORK_SHIFTS[1][0].strftime('%H:%M')}-{config.WORK_SHIFTS[1][1].strftime('%H:%M')}")
    
    # Запуск фоновой задачи
    asyncio.create_task(afk_checker())

if __name__ == "__main__":
    from monitoring import handle_message
    
    # Регистрация обработчиков
    dp.register_message_handler(
        handle_message,
        chat_id=config.MONITOR_CHAT_ID,
        content_types=[types.ContentType.PHOTO, types.ContentType.TEXT]
    )
    
    executor.start_polling(dp, on_startup=on_startup)