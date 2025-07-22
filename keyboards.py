from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

def admin_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="View Ignore List", callback_data="view_ignore_list"),
        InlineKeyboardButton(text="Add to Ignore List", callback_data="add_to_ignore")
    )
    builder.row(
        InlineKeyboardButton(text="Remove from Ignore List", callback_data="remove_from_ignore"),
        InlineKeyboardButton(text="Generate AFK Report", callback_data="generate_afk_report")
    )
    builder.row(
        InlineKeyboardButton(text="Toggle Monitoring", callback_data="toggle_monitoring")
    )
    return builder.as_markup()

def ignore_list_keyboard(ignored_users: list):
    builder = InlineKeyboardBuilder()
    for user_id in ignored_users:
        builder.row(
            InlineKeyboardButton(
                text=f"Remove {user_id}", 
                callback_data=f"remove_ignore_{user_id}"
            )
        )
    builder.row(
        InlineKeyboardButton(text="Back to Admin", callback_data="back_to_admin")
    )
    return builder.as_markup()

def back_to_admin_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Back to Admin", callback_data="back_to_admin")
    )
    return builder.as_markup()