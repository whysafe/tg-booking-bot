import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402
from config import config  # noqa: E402

DAY = "2030-01-15"


@pytest.fixture(autouse=True)
def tmp_db(tmp_path):
    # Config заморожен (frozen dataclass), поэтому путь к базе подменяем напрямую
    old = config.db_path
    object.__setattr__(config, "db_path", str(tmp_path / "test.db"))
    db.init_db()
    yield
    object.__setattr__(config, "db_path", old)


def book(service="cut", time="12:00", user_id=1, day=DAY):
    return db.create_booking(user_id, "Иван", "+7 999 123-45-67", service, day, time)


def test_create_and_list():
    booking_id = book()
    items = db.user_bookings(1, "2030-01-01")
    assert [b.id for b in items] == [booking_id]
    assert items[0].time == "12:00" and items[0].status == "active"
    assert db.bookings_between(DAY, DAY)[0].id == booking_id


def test_cancel_only_own_and_frees_slot():
    booking_id = book()
    assert db.cancel_booking(booking_id, user_id=2) is None
    cancelled = db.cancel_booking(booking_id, user_id=1)
    assert cancelled is not None and cancelled.id == booking_id
    assert db.cancel_booking(booking_id) is None
    assert db.user_bookings(1, "2030-01-01") == []
    assert "12:00" in db.free_times(DAY, "cut")
    book()  # слот снова можно занять


def test_same_slot_twice_rejected():
    book()
    with pytest.raises(db.SlotTakenError):
        book(user_id=2)


def test_long_service_blocks_next_slot():
    book(service="combo", time="12:00")  # 90 минут: 12:00-13:30
    free = db.free_times(DAY, "cut")
    assert "12:00" not in free and "13:00" not in free
    assert "11:00" in free and "14:00" in free
    with pytest.raises(db.SlotTakenError):
        book(service="cut", time="13:00", user_id=2)


def test_new_booking_cannot_overlap_next_one():
    book(service="cut", time="13:00")
    # combo в 12:00 закончилась бы в 13:30 и наехала на 13:00
    assert "12:00" not in db.free_times(DAY, "combo")
    assert "12:00" in db.free_times(DAY, "cut")
    with pytest.raises(db.SlotTakenError):
        book(service="combo", time="12:00", user_id=2)
    book(service="beard", time="12:00", user_id=2)  # 40 минут помещаются


def test_booking_must_end_before_work_end():
    last = f"{config.work_end - 1:02d}:00"
    assert last in db.free_times(DAY, "cut")
    assert last not in db.free_times(DAY, "combo")
    with pytest.raises(db.SlotTakenError):
        book(service="combo", time=last)


def test_partial_unique_index_kept():
    book()
    conn = db._connect()
    try:
        with pytest.raises(db.sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO bookings (user_id, name, phone, service, date, time, created_at) VALUES (2, 'x', 'y', 'cut', ?, '12:00', 'now')",
                (DAY,))
    finally:
        conn.close()


def test_other_days_independent():
    book(service="combo", time="12:00")
    assert "12:00" in db.free_times("2030-01-16", "combo")
