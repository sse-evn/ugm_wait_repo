# admin.py
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter, Command
from aiogram.fsm.state import State, StatesGroup

router = Router()

class AdminStates(StatesGroup):
    waiting_for_ignore_user_id = State()

@router.callback_query(F.data == "add_to_ignore")
async def cmd_add_to_ignore(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "Введите ID пользователя для добавления в игнор-лист:",
        reply_markup=back_to_admin_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_ignore_user_id)
    await callback.answer()

@router.message(StateFilter(AdminStates.waiting_for_ignore_user_id))
async def process_ignore_user_id(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text)
        await Database.add_to_ignore_list(user_id)
        await message.answer(
            f"Пользователь {user_id} добавлен в игнор-лист",
            reply_markup=admin_keyboard()
        )
    except ValueError:
        await message.answer(
            "Ошибка! Введите корректный ID пользователя (число)",
            reply_markup=back_to_admin_keyboard()
        )
    await state.clear()
