from datetime import date, datetime, timedelta

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import config

WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря"]

BTN_BOOK = "📅 Записаться"
BTN_MY = "🗂 Мои записи"
BTN_PRICES = "💈 Услуги и цены"
BTN_CONTACTS = "📍 Контакты"


class ServiceCb(CallbackData, prefix="svc"):
    code: str


class DayCb(CallbackData, prefix="day"):
    value: str  # YYYY-MM-DD


class TimeCb(CallbackData, prefix="time"):
    value: str  # HH-MM (двоеточие зарезервировано разделителем callback data)


class ConfirmCb(CallbackData, prefix="confirm"):
    ok: bool


class CancelCb(CallbackData, prefix="cancel"):
    booking_id: int


class NavCb(CallbackData, prefix="nav"):
    to: str  # services | days


def human_date(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]}"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_BOOK), KeyboardButton(text=BTN_MY)],
                  [KeyboardButton(text=BTN_PRICES), KeyboardButton(text=BTN_CONTACTS)]],
        resize_keyboard=True,
    )


def services_kb():
    kb = InlineKeyboardBuilder()
    for s in config.services:
        kb.button(text=f"{s.title} · {s.price} ₽", callback_data=ServiceCb(code=s.code))
    kb.adjust(1)
    return kb.as_markup()


def days_kb():
    kb = InlineKeyboardBuilder()
    today = datetime.now(config.tz).date()
    for i in range(config.days_ahead):
        d = today + timedelta(days=i)
        label = "Сегодня" if i == 0 else "Завтра" if i == 1 else human_date(d)
        kb.button(text=label, callback_data=DayCb(value=d.isoformat()))
    kb.button(text="← К услугам", callback_data=NavCb(to="services"))
    kb.adjust(2)
    return kb.as_markup()


def times_kb(free: list[str]):
    kb = InlineKeyboardBuilder()
    for t in free:
        kb.button(text=t, callback_data=TimeCb(value=t.replace(":", "-")))
    kb.adjust(4)
    kb.row(InlineKeyboardButton(text="← Другой день", callback_data=NavCb(to="days").pack()))
    return kb.as_markup()


def phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить мой номер", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )


def confirm_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data=ConfirmCb(ok=True))
    kb.button(text="✖️ Отменить", callback_data=ConfirmCb(ok=False))
    return kb.as_markup()


def my_bookings_kb(bookings):
    kb = InlineKeyboardBuilder()
    for b in bookings:
        d = date.fromisoformat(b.date)
        kb.button(text=f"Отменить {d.day}.{d.month:02d} в {b.time}", callback_data=CancelCb(booking_id=b.id))
    kb.adjust(1)
    return kb.as_markup()
