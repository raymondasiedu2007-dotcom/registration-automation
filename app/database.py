from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.models import AttemptStatus, PROFILE_FIELDS, UserProfile

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (telegram_user_id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS user_profiles (
    telegram_user_id INTEGER PRIMARY KEY, first_name TEXT DEFAULT '', last_name TEXT DEFAULT '', address_line1 TEXT DEFAULT '',
    address_line2 TEXT DEFAULT '', state_region TEXT DEFAULT '', city TEXT DEFAULT '', postal_code TEXT DEFAULT '', phone_number TEXT DEFAULT '',
    email TEXT DEFAULT '', updated_at TEXT NOT NULL, FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id));
CREATE TABLE IF NOT EXISTS registration_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_user_id INTEGER NOT NULL, site_key TEXT NOT NULL, status TEXT NOT NULL,
    started_at TEXT NOT NULL, completed_at TEXT, failure_reason TEXT, failure_category TEXT, manual_interventions INTEGER DEFAULT 0,
    duration_seconds REAL);
CREATE TABLE IF NOT EXISTS site_analytics (
    site_key TEXT PRIMARY KEY, attempts INTEGER DEFAULT 0, successes INTEGER DEFAULT 0, failures INTEGER DEFAULT 0,
    manual_interventions INTEGER DEFAULT 0, total_duration_seconds REAL DEFAULT 0, last_attempt_at TEXT);
CREATE TABLE IF NOT EXISTS error_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_user_id INTEGER, site_key TEXT, category TEXT NOT NULL, message TEXT NOT NULL,
    details_json TEXT, screenshot_path TEXT, created_at TEXT NOT NULL);
"""


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    async def init(self) -> None:
        with self._connect() as db:
            db.executescript(SCHEMA)

    async def ensure_user(self, telegram_user_id: int) -> None:
        now = utcnow_iso()
        with self._connect() as db:
            db.execute(
                "INSERT INTO users (telegram_user_id, created_at, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(telegram_user_id) DO UPDATE SET updated_at=excluded.updated_at",
                (telegram_user_id, now, now),
            )

    async def get_profile(self, telegram_user_id: int) -> UserProfile:
        await self.ensure_user(telegram_user_id)
        with self._connect() as db:
            row = db.execute("SELECT * FROM user_profiles WHERE telegram_user_id=?", (telegram_user_id,)).fetchone()
            if row is None:
                db.execute("INSERT INTO user_profiles (telegram_user_id, updated_at) VALUES (?, ?)", (telegram_user_id, utcnow_iso()))
                return UserProfile(telegram_user_id=telegram_user_id)
            return UserProfile(telegram_user_id=telegram_user_id, **{field: row[field] or "" for field in PROFILE_FIELDS})

    async def upsert_profile(self, profile: UserProfile) -> None:
        await self.ensure_user(profile.telegram_user_id)
        values = [getattr(profile, field) for field in PROFILE_FIELDS]
        placeholders = ", ".join(["?"] * (len(PROFILE_FIELDS) + 2))
        columns = ", ".join(["telegram_user_id", *PROFILE_FIELDS, "updated_at"])
        updates = ", ".join([f"{field}=excluded.{field}" for field in PROFILE_FIELDS] + ["updated_at=excluded.updated_at"])
        with self._connect() as db:
            db.execute(
                f"INSERT INTO user_profiles ({columns}) VALUES ({placeholders}) ON CONFLICT(telegram_user_id) DO UPDATE SET {updates}",
                [profile.telegram_user_id, *values, utcnow_iso()],
            )

    async def start_attempt(self, telegram_user_id: int, site_key: str) -> int:
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO registration_attempts (telegram_user_id, site_key, status, started_at) VALUES (?, ?, ?, ?)",
                (telegram_user_id, site_key, AttemptStatus.STARTED.value, utcnow_iso()),
            )
            return int(cursor.lastrowid)

    async def finish_attempt(self, attempt_id: int, status: AttemptStatus, failure_reason: str | None = None, failure_category: str | None = None, manual_interventions: int = 0) -> None:
        completed_at = utcnow_iso()
        with self._connect() as db:
            row = db.execute("SELECT * FROM registration_attempts WHERE id=?", (attempt_id,)).fetchone()
            if row is None:
                raise ValueError(f"Unknown attempt id: {attempt_id}")
            duration = (datetime.fromisoformat(completed_at) - datetime.fromisoformat(row["started_at"])).total_seconds()
            db.execute(
                "UPDATE registration_attempts SET status=?, completed_at=?, failure_reason=?, failure_category=?, manual_interventions=?, duration_seconds=? WHERE id=?",
                (status.value, completed_at, failure_reason, failure_category, manual_interventions, duration, attempt_id),
            )
            db.execute(
                "INSERT INTO site_analytics (site_key, attempts, successes, failures, manual_interventions, total_duration_seconds, last_attempt_at) VALUES (?, 1, ?, ?, ?, ?, ?) "
                "ON CONFLICT(site_key) DO UPDATE SET attempts=attempts+1, successes=successes+excluded.successes, failures=failures+excluded.failures, "
                "manual_interventions=manual_interventions+excluded.manual_interventions, total_duration_seconds=total_duration_seconds+excluded.total_duration_seconds, last_attempt_at=excluded.last_attempt_at",
                (row["site_key"], 1 if status == AttemptStatus.SUCCESS else 0, 1 if status == AttemptStatus.FAILED else 0, manual_interventions, duration, completed_at),
            )

    async def log_error(self, telegram_user_id: int | None, site_key: str | None, category: str, message: str, details: dict | None = None, screenshot_path: str | None = None) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO error_logs (telegram_user_id, site_key, category, message, details_json, screenshot_path, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (telegram_user_id, site_key, category, message, json.dumps(details or {}), screenshot_path, utcnow_iso()),
            )
