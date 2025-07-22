from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from config import Config
from keyboards import admin_keyboard

router = Router()

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("AFK Monitor Bot is running!")

@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id not in Config.ADMIN_IDS:
        await message.answer("You are not authorized to use this command.")
        return
    
    await message.answer(
        "Admin Panel:",
        reply_markup=admin_keyboard()
    )