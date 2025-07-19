import os
from dotenv import load_dotenv
from datetime import time
import pytz

load_dotenv()

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    MONITOR_CHAT_ID = int(os.getenv("MONITOR_CHAT_ID"))
    ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
    DEFAULT_ADMINS = [int(x) for x in os.getenv("DEFAULT_ADMINS").split(",")]
    TIMEZONE = pytz.timezone(os.getenv("TIMEZONE", "Asia/Almaty"))
    
    # Парсим смены для Алматы (07:00-15:00 и 15:00-23:00)
    WORK_SHIFTS = []
    for shift in os.getenv("WORK_SHIFTS", "07:00-15:00,15:00-23:00").split(","):
        start, end = shift.split("-")
        WORK_SHIFTS.append((
            time(int(start.split(":")[0]), int(start.split(":")[1])),
            time(int(end.split(":")[0]), int(end.split(":")[1]))
        ))

config = Config()