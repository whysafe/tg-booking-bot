"""Работа с SQLite. Для небольшого бота синхронного sqlite3 достаточно:
запросы занимают доли миллисекунды и не блокируют event loop заметно."""
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime

from config import config


@dataclass
class Booking:
    id: int
    user_id: int
    name: str
    phone: str
    service: str
    date: str   # YYYY-MM-DD
    time: str   # HH:MM
    status: str


class SlotTakenError(Exception):
    """Слот заняли, пока пользователь заполнял форму."""


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _duration(service_code: str) -> int:
    service = config.service(service_code)
    return service.minutes if service else 60


def _busy(conn: sqlite3.Connection, date: str) -> list[tuple[int, int]]:
    """Занятые интервалы дня в минутах от полуночи: [начало, конец)."""
    rows = conn.execute("SELECT service, time FROM bookings WHERE date = ? AND status = 'active'", (date,))
    result = []
    for r in rows:
        start = _minutes(r["time"])
        result.append((start, start + _duration(r["service"])))
    return result


def _fits(time: str, service_code: str, busy: list[tuple[int, int]]) -> bool:
    """Интервал [start, start + длительность) не выходит за конец дня и ни с чем не пересекается."""
    start = _minutes(time)
    end = start + _duration(service_code)
    if start < config.work_start * 60 or end > config.work_end * 60:
        return False
    return all(end <= b_start or start >= b_end for b_start, b_end in busy)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                service TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL
            )""")
        # Один активный клиент на слот: защита от двойной записи на уровне БД
        conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_active_slot
                        ON bookings(date, time) WHERE status = 'active'""")


def free_times(date: str, service_code: str) -> list[str]:
    """Начала слотов (по часу), куда помещается услуга с учётом её длительности."""
    with closing(_connect()) as conn:
        busy = _busy(conn, date)
    times = (f"{hour:02d}:00" for hour in range(config.work_start, config.work_end))
    return [t for t in times if _fits(t, service_code, busy)]


def create_booking(user_id: int, name: str, phone: str, service: str, date: str, time: str) -> int:
    try:
        with closing(_connect()) as conn, conn:
            # BEGIN IMMEDIATE берёт блокировку на запись до проверки,
            # поэтому между проверкой пересечения и INSERT никто не вклинится
            conn.execute("BEGIN IMMEDIATE")
            if not _fits(time, service, _busy(conn, date)):
                raise SlotTakenError
            cur = conn.execute(
                "INSERT INTO bookings (user_id, name, phone, service, date, time, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, name, phone, service, date, time, datetime.now(config.tz).isoformat(timespec="seconds")),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError as exc:
        raise SlotTakenError from exc


def user_bookings(user_id: int, from_date: str) -> list[Booking]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            """SELECT * FROM bookings WHERE user_id = ? AND status = 'active' AND date >= ?
               ORDER BY date, time""", (user_id, from_date))
        return [_row(r) for r in rows]


def bookings_between(date_from: str, date_to: str) -> list[Booking]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            """SELECT * FROM bookings WHERE status = 'active' AND date BETWEEN ? AND ?
               ORDER BY date, time""", (date_from, date_to))
        return [_row(r) for r in rows]


def cancel_booking(booking_id: int, user_id: int | None = None) -> Booking | None:
    """Отменяет запись. Если передан user_id, отменить можно только свою."""
    with closing(_connect()) as conn, conn:
        row = conn.execute("SELECT * FROM bookings WHERE id = ? AND status = 'active'", (booking_id,)).fetchone()
        if not row or (user_id is not None and row["user_id"] != user_id):
            return None
        conn.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
        return _row(row)


def _row(r: sqlite3.Row) -> Booking:
    return Booking(r["id"], r["user_id"], r["name"], r["phone"], r["service"], r["date"], r["time"], r["status"])
