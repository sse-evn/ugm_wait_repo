import sqlite3
from datetime import datetime
from config import config
from typing import Optional, List, Tuple

class Database:
    def __init__(self, db_path: str = 'afk_bot.db'):
        self.conn = sqlite3.connect(db_path)
        self._create_tables()
        self._add_default_admins()

    def _create_tables(self):
        """Создает необходимые таблицы в базе данных"""
        cursor = self.conn.cursor()
        
        # Таблица пользователей
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            last_active TIMESTAMP,
            is_admin BOOLEAN DEFAULT 0,
            is_ignored BOOLEAN DEFAULT 0,
            last_notified TIMESTAMP NULL
        )
        ''')
        
        # Таблица смен
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS shifts (
            user_id INTEGER,
            shift_start TIMESTAMP,
            shift_end TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
        ''')
        
        self.conn.commit()

    def _add_default_admins(self):
        """Добавляет администраторов по умолчанию"""
        cursor = self.conn.cursor()
        for admin_id in config.DEFAULT_ADMINS:
            cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, is_admin)
            VALUES (?, 1)
            ''', (admin_id,))
        self.conn.commit()

    def update_user_activity(self, user_id: int, username: str):
        """Обновляет время последней активности пользователя"""
        cursor = self.conn.cursor()
        cursor.execute('''
        INSERT OR REPLACE INTO users (user_id, username, last_active, is_ignored)
        VALUES (?, ?, datetime('now'), 0)
        ''', (user_id, username))
        self.conn.commit()

    def get_afk_users(self, minutes_threshold: int = 45) -> List[Tuple[int, str, str]]:
        """Возвращает список пользователей, которые AFK дольше указанного времени"""
        cursor = self.conn.cursor()
        cursor.execute(f'''
        SELECT user_id, username, last_active 
        FROM users 
        WHERE is_admin = 0 
          AND is_ignored = 0
          AND last_active < datetime('now', '-{minutes_threshold} minutes')
          AND (last_notified IS NULL OR last_notified < last_active)
        ''')
        return cursor.fetchall()

    def mark_as_notified(self, user_id: int):
        """Помечает пользователя как уведомленного"""
        cursor = self.conn.cursor()
        cursor.execute('''
        UPDATE users 
        SET last_notified = datetime('now')
        WHERE user_id = ?
        ''', (user_id,))
        self.conn.commit()

    def get_user_status(self, user_id: int) -> Optional[Tuple[str, str]]:
        """Возвращает статус пользователя (username, last_active)"""
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT username, last_active 
        FROM users 
        WHERE user_id = ?
        ''', (user_id,))
        return cursor.fetchone()

    def toggle_ignore_user(self, user_id: int) -> bool:
        """Переключает статус игнорирования пользователя"""
        cursor = self.conn.cursor()
        cursor.execute('''
        UPDATE users 
        SET is_ignored = NOT is_ignored 
        WHERE user_id = ?
        ''', (user_id,))
        self.conn.commit()
        cursor.execute('SELECT is_ignored FROM users WHERE user_id = ?', (user_id,))
        return bool(cursor.fetchone()[0])

    def add_admin(self, user_id: int, username: str):
        """Добавляет администратора"""
        cursor = self.conn.cursor()
        cursor.execute('''
        INSERT OR REPLACE INTO users (user_id, username, is_admin)
        VALUES (?, ?, 1)
        ''', (user_id, username))
        self.conn.commit()

    def remove_admin(self, user_id: int):
        """Удаляет администратора"""
        cursor = self.conn.cursor()
        cursor.execute('''
        UPDATE users 
        SET is_admin = 0 
        WHERE user_id = ?
        ''', (user_id,))
        self.conn.commit()

    def get_all_admins(self) -> List[Tuple[int, str]]:
        """Возвращает список всех администраторов"""
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT user_id, username 
        FROM users 
        WHERE is_admin = 1
        ''')
        return cursor.fetchall()

    def close(self):
        """Закрывает соединение с базой данных"""
        self.conn.close()

# Инициализация глобального экземпляра базы данных
db = Database()