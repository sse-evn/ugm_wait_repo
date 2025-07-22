import json
import aiofiles
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

STORAGE_DIR = Path("storage")
STORAGE_DIR.mkdir(exist_ok=True)

class Database:
    @staticmethod
    async def load_data(filename: str) -> Dict:
        filepath = STORAGE_DIR / filename
        try:
            async with aiofiles.open(filepath, mode="r") as f:
                data = await f.read()
                return json.loads(data)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    @staticmethod
    async def save_data(filename: str, data: Dict):
        filepath = STORAGE_DIR / filename
        async with aiofiles.open(filepath, mode="w") as f:
            await f.write(json.dumps(data, indent=2, default=str))

    @classmethod
    async def get_ignore_list(cls) -> List[int]:
        data = await cls.load_data("ignore_list.json")
        return data.get("ignored_users", [])

    @classmethod
    async def add_to_ignore_list(cls, user_id: int):
        ignored = await cls.get_ignore_list()
        if user_id not in ignored:
            ignored.append(user_id)
            await cls.save_data("ignore_list.json", {"ignored_users": ignored})

    @classmethod
    async def remove_from_ignore_list(cls, user_id: int):
        ignored = await cls.get_ignore_list()
        if user_id in ignored:
            ignored.remove(user_id)
            await cls.save_data("ignore_list.json", {"ignored_users": ignored})

    @classmethod
    async def update_last_activity(cls, user_id: int):
        data = await cls.load_data("last_activity.json")
        data[str(user_id)] = datetime.now().isoformat()
        await cls.save_data("last_activity.json", data)

    @classmethod
    async def get_last_activity(cls) -> Dict[int, datetime]:
        data = await cls.load_data("last_activity.json")
        return {int(k): datetime.fromisoformat(v) for k, v in data.items()}