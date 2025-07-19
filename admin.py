from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import config
from database import db

async def setup_admin_handlers(dp):
    @dp.message_handler(Command("admin"))
    async def admin_panel(message: types.Message):
        if not db.is_admin(message.from_user.id):
            return
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("Проверить AFK", callback_data="check_afk"))
        keyboard.add(InlineKeyboardButton("Игнор-лист", callback_data="ignore_list"))
        
        await message.reply("Админ-панель:", reply_markup=keyboard)
    
    @dp.callback_query_handler(lambda c: c.data == "check_afk")
    async def manual_afk_check(callback: types.CallbackQuery):
        afk_users = db.get_afk_users(45)
        text = "Сейчас все активны!" if not afk_users else \
               f"AFK (>45 мин):\n" + "\n".join([f"@{username}" for user_id, username in afk_users])
        await callback.message.edit_text(text)
    
    @dp.callback_query_handler(lambda c: c.data == "ignore_list")
    async def show_ignore_list(callback: types.CallbackQuery):
        # Логика для работы с игнор-листом
        pass