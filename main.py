import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Command
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from config import config
from database import Database  # Импортируем класс, а не экземпляр

# Инициализация
storage = MemoryStorage()
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(bot, storage=storage)
db = Database()  # Создаем экземпляр базы данных здесь

async def on_startup(dp):
    print("Бот запущен!")
    print(f"Таймзона: {config.TIMEZONE}")
    print("Рабочие смены:")
    for i, (start, end) in enumerate(config.WORK_SHIFTS, 1):
        print(f"{i}. {start.strftime('%H:%M')}-{end.strftime('%H:%M')}")

async def check_afk():
    """Фоновая задача для проверки AFK статусов"""
    while True:
        afk_users = db.get_afk_users(45)
        if afk_users:
            message = "🚨 AFK-тревога!\n"
            for user_id, username, last_active in afk_users:
                message += f"👤 @{username} - не активен более 45 мин\n"
                db.mark_as_notified(user_id)
            
            await bot.send_message(config.ADMIN_CHAT_ID, message)
        
        await asyncio.sleep(60)  # Проверка каждую минуту

@dp.message_handler(chat_id=config.MONITOR_CHAT_ID,
                  content_types=[types.ContentType.PHOTO, types.ContentType.TEXT])
async def handle_worker_message(message: types.Message):
    """Обработчик сообщений в рабочем чате"""
    user_id = message.from_user.id
    username = message.from_user.username or f"id{user_id}"
    
    # Проверяем фото с текстом "макс"
    if message.photo and "макс" in (message.caption or "").lower():
        db.update_user_activity(user_id, username)
        print(f"Обновлена активность для @{username}")

@dp.message_handler(Command("afk_report"))
async def afk_report(message: types.Message):
    """Ручная проверка AFK статусов"""
    if not db.is_admin(message.from_user.id):
        return
    
    afk_users = db.get_afk_users(45)
    if not afk_users:
        await message.reply("Сейчас все сотрудники активны!")
        return
    
    report = "📊 Отчет по AFK:\n"
    for user_id, username, last_active in afk_users:
        report += f"👤 @{username} - не активен с {last_active}\n"
    
    await message.reply(report)

async def main():
    # Запуск фоновых задач
    asyncio.create_task(check_afk())
    
    # Запуск бота
    await dp.start_polling()

if __name__ == "__main__":
    # Инициализация базы данных
    db._create_tables()
    db._add_default_admins()
    
    # Запуск приложения
    asyncio.run(main())