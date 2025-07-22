import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    WORKERS_GROUP_ID = int(os.getenv("WORKERS_GROUP_ID"))
    ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
    ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS").split(",")]
    AFK_TIMEOUT_MINUTES = int(os.getenv("AFK_TIMEOUT_MINUTES", 45))
    
    @classmethod
    def validate(cls):
        required_vars = [
            "BOT_TOKEN", "WORKERS_GROUP_ID", 
            "ADMIN_GROUP_ID", "ADMIN_IDS"
        ]
        missing = [var for var in required_vars if not getattr(cls, var)]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")