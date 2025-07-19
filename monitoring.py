from aiogram import types
from datetime import datetime
from config import config
from database import db
import pytz

class ShiftChecker:
    @staticmethod
    def is_working_time():
        """Проверяет, идет ли сейчас рабочая смена в Алматы"""
        now = datetime.now(config.TIMEZONE).time()
        for shift_start, shift_end in config.WORK_SHIFTS:
            if shift_start <= now < shift_end:
                return True
        return False
    
    @staticmethod
    def current_shift_name():
        """Возвращает название текущей смены"""
        now = datetime.now(config.TIMEZONE).time()
        if time(7, 0) <= now < time(15, 0):
            return "утренняя"
        elif time(15, 0) <= now < time(23, 0):
            return "вечерняя"
        return "не рабочее время"

async def handle_message(message: types.Message):
    # Работаем только в рабочее время
    if not ShiftChecker.is_working_time():
        return
    
    user_id = message.from_user.id
    # Проверяем фото с подписью "макс"
    if message.photo and "макс" in (message.caption or "").lower():
        db.update_activity(user_id, message.from_user.username)

async def check_afk(bot):
    while True:
        await asyncio.sleep(60)  # Проверка каждую минуту
        
        # Проверяем только в рабочее время
        if ShiftChecker.is_working_time():
            afk_users = db.get_afk_users(45)
            if afk_users:
                afk_list = "\n".join([f"@{username}" for user_id, username in afk_users])
                shift_name = ShiftChecker.current_shift_name()
                await bot.send_message(
                    config.ADMIN_CHAT_ID,
                    f"🚨 {shift_name} смена (Алматы):\n"
                    f"Следующие сотрудники AFK (>45 мин):\n{afk_list}"
                )