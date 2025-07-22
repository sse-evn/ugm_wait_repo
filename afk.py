from datetime import datetime, timedelta
from typing import Dict
import logging

from aiogram import Router, types, F
from aiogram.exceptions import TelegramBadRequest

from config import Config
from database import Database

router = Router()

logger = logging.getLogger(__name__)

async def get_user_info(user_id: int, bot) -> str:
    try:
        chat_member = await bot.get_chat_member(Config.WORKERS_GROUP_ID, user_id)
        user = chat_member.user
        username = f"@{user.username}" if user.username else f"ID: {user.id}"
        return username
    except TelegramBadRequest as e:
        logger.error(f"Error getting user info for {user_id}: {e}")
        return f"ID: {user_id}"

async def check_afk_users() -> str:
    last_activity = await Database.get_last_activity()
    ignored_users = await Database.get_ignore_list()
    
    afk_threshold = datetime.now() - timedelta(minutes=Config.AFK_TIMEOUT_MINUTES)
    afk_users = {
        user_id: last_active 
        for user_id, last_active in last_activity.items()
        if last_active < afk_threshold and user_id not in ignored_users
    }
    
    if not afk_users:
        return "No AFK users currently."
    
    report_lines = [
        f"AFK Report (Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')})"
    ]
    
    for user_id, last_active in afk_users.items():
        report_lines.append(
            f"- User {user_id}: AFK since {last_active.strftime('%Y-%m-%d %H:%M:%S')}"
        )
    
    report_lines.append(f"Total AFK users: {len(afk_users)}")
    return "\n".join(report_lines)

@router.message(F.chat.id == Config.WORKERS_GROUP_ID)
async def track_activity(message: types.Message):
    if message.from_user.is_bot:
        return
    
    await Database.update_last_activity(message.from_user.id)
    
    # Check if this user was previously AFK and send a "back" notification
    last_activity = await Database.get_last_activity()
    afk_threshold = datetime.now() - timedelta(minutes=Config.AFK_TIMEOUT_MINUTES)
    
    if (last_activity.get(message.from_user.id, datetime.now()) < afk_threshold:
        # User was AFK but just returned
        try:
            username = await get_user_info(message.from_user.id, message.bot)
            await message.bot.send_message(
                Config.ADMIN_GROUP_ID,
                f"User {username} is back after being AFK."
            )
        except Exception as e:
            logger.error(f"Error sending back notification: {e}")

async def periodic_afk_check(bot):
    try:
        report = await check_afk_users()
        if "No AFK users" not in report:
            await bot.send_message(Config.ADMIN_GROUP_ID, report)
    except Exception as e:
        logger.error(f"Error in periodic AFK check: {e}")