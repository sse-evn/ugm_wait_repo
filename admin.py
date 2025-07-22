from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

from config import Config
from database import Database
from keyboards import (
    admin_keyboard, 
    ignore_list_keyboard,
    back_to_admin_keyboard
)

router = Router()

class AdminStates(StatesGroup):
    ADD_TO_IGNORE = State()

@router.callback_query(F.data == "back_to_admin")
async def back_to_admin(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "Admin Panel:",
        reply_markup=admin_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "view_ignore_list")
async def view_ignore_list(callback: types.CallbackQuery):
    ignored_users = await Database.get_ignore_list()
    if not ignored_users:
        text = "Ignore list is empty."
    else:
        text = "Ignored Users:\n" + "\n".join(str(user_id) for user_id in ignored_users)
    
    await callback.message.edit_text(
        text,
        reply_markup=ignore_list_keyboard(ignored_users)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("remove_ignore_"))
async def remove_from_ignore_list(callback: types.CallbackQuery):
    user_id = int(callback.data.split("_")[-1])
    await Database.remove_from_ignore_list(user_id)
    
    ignored_users = await Database.get_ignore_list()
    if not ignored_users:
        text = "Ignore list is empty."
    else:
        text = "Ignored Users:\n" + "\n".join(str(user_id) for user_id in ignored_users)
    
    await callback.message.edit_text(
        f"User {user_id} removed from ignore list.\n\n{text}",
        reply_markup=ignore_list_keyboard(ignored_users)
    )
    await callback.answer()

@router.callback_query(F.data == "add_to_ignore")
async def add_to_ignore_prompt(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Please send the user ID or username to add to the ignore list:",
        reply_markup=back_to_admin_keyboard()
    )
    await state.set_state(AdminStates.ADD_TO_IGNORE)
    await callback.answer()

@router.message(StateFilter(AdminStates.ADD_TO_IGNORE))
async def add_to_ignore_handler(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
    except ValueError:
        if message.text.startswith("@"):
            await message.answer("Please provide a numeric user ID instead of username.")
            return
        else:
            await message.answer("Please provide a valid numeric user ID.")
            return
    
    await Database.add_to_ignore_list(user_id)
    await message.answer(
        f"User {user_id} added to ignore list.",
        reply_markup=back_to_admin_keyboard()
    )
    await state.clear()

@router.callback_query(F.data == "generate_afk_report")
async def generate_afk_report(callback: types.CallbackQuery):
    from handlers.afk import check_afk_users
    report = await check_afk_users()
    await callback.message.edit_text(
        report,
        reply_markup=back_to_admin_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "toggle_monitoring")
async def toggle_monitoring(callback: types.CallbackQuery):
    await callback.answer("Monitoring toggle not implemented yet")
