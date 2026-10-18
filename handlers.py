import logging
import re
from datetime import date, datetime, timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

import db
import keyboards as kb
from config import config

router = Router()
log = logging.getLogger(__name__)


class Booking(StatesGroup):
    service = State()
    day = State()
    time = State()
    name = State()
    phone = State()
    confirm = State()


def free_slots(day: date, service_code: str) -> list[str]:
    """Свободные слоты на день: услуга помещается целиком, время ещё не прошло."""
    now = datetime.now(config.tz)
    slots = []
    for t in db.free_times(day.isoformat(), service_code):
        slot_dt = datetime.combine(day, datetime.min.time(), tzinfo=config.tz).replace(hour=int(t[:2]), minute=int(t[3:]))
        if slot_dt > now + timedelta(minutes=30):
            slots.append(t)
    return slots


# ---------- Общие команды ----------

@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"Здравствуйте, {escape(message.from_user.first_name)}! Это бот записи в {config.business_name}.\n"
        "Выберите, что нужно, в меню ниже.",
        reply_markup=kb.main_menu(),
    )


@router.message(Command("cancel"))
@router.message(F.text.in_({"отмена", "Отмена", "ОТМЕНА"}))
async def cancel_flow(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Запись прервана. Можно начать заново в любой момент.", reply_markup=kb.main_menu())


@router.message(F.text == kb.BTN_PRICES)
async def prices(message: Message):
    lines = [f"• <b>{s.title}</b> — {s.price} ₽, {s.minutes} мин" for s in config.services]
    await message.answer("Услуги и цены:\n\n" + "\n".join(lines))


@router.message(F.text == kb.BTN_CONTACTS)
async def contacts(message: Message):
    await message.answer(
        f"<b>{config.business_name}</b>\n{config.address}\n{config.phone}\n"
        f"Работаем ежедневно с {config.work_start}:00 до {config.work_end}:00."
    )


# ---------- Запись: услуга → день → время → имя → телефон → подтверждение ----------

@router.message(F.text == kb.BTN_BOOK)
@router.message(Command("book"))
async def choose_service(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Booking.service)
    await message.answer("Какая услуга нужна?", reply_markup=kb.services_kb())


@router.callback_query(kb.NavCb.filter(F.to == "services"))
async def back_to_services(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Booking.service)
    await cb.message.edit_text("Какая услуга нужна?", reply_markup=kb.services_kb())
    await cb.answer()


@router.callback_query(Booking.service, kb.ServiceCb.filter())
async def service_chosen(cb: CallbackQuery, callback_data: kb.ServiceCb, state: FSMContext):
    service = config.service(callback_data.code)
    if not service:
        await cb.answer("Такой услуги больше нет", show_alert=True)
        return
    await state.update_data(service=service.code)
    await state.set_state(Booking.day)
    await cb.message.edit_text(f"<b>{service.title}</b>, {service.price} ₽\n\nВыберите день:", reply_markup=kb.days_kb())
    await cb.answer()


@router.callback_query(kb.NavCb.filter(F.to == "days"))
async def back_to_days(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Booking.day)
    await cb.message.edit_text("Выберите день:", reply_markup=kb.days_kb())
    await cb.answer()


@router.callback_query(Booking.day, kb.DayCb.filter())
async def day_chosen(cb: CallbackQuery, callback_data: kb.DayCb, state: FSMContext):
    day = date.fromisoformat(callback_data.value)
    data = await state.get_data()
    slots = free_slots(day, data["service"])
    if not slots:
        await cb.answer("На этот день свободного времени нет, выберите другой", show_alert=True)
        return
    await state.update_data(day=day.isoformat())
    await state.set_state(Booking.time)
    await cb.message.edit_text(f"{kb.human_date(day).capitalize()}. Свободное время:", reply_markup=kb.times_kb(slots))
    await cb.answer()


@router.callback_query(Booking.time, kb.TimeCb.filter())
async def time_chosen(cb: CallbackQuery, callback_data: kb.TimeCb, state: FSMContext):
    time = callback_data.value.replace("-", ":")
    data = await state.get_data()
    if time not in free_slots(date.fromisoformat(data["day"]), data["service"]):
        await cb.answer("Это время только что заняли. Выберите другое.", show_alert=True)
        return
    await state.update_data(time=time)
    await state.set_state(Booking.name)
    await cb.message.edit_text(f"Время {time}. Осталось указать имя и телефон.")
    await cb.message.answer("Как к вам обращаться?")
    await cb.answer()


@router.message(Booking.name, F.text)
async def name_entered(message: Message, state: FSMContext):
    name = message.text.strip()
    if not 2 <= len(name) <= 40:
        await message.answer("Напишите имя, от 2 до 40 символов.")
        return
    await state.update_data(name=name)
    await state.set_state(Booking.phone)
    await message.answer("Оставьте телефон: нажмите кнопку ниже или напишите номер.", reply_markup=kb.phone_kb())


@router.message(Booking.phone, F.contact | F.text)
async def phone_entered(message: Message, state: FSMContext):
    raw = message.contact.phone_number if message.contact else message.text
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits[0] in "78":
        digits = "7" + digits[1:]
    if len(digits) != 11:
        await message.answer("Не похоже на номер. Пример: +7 999 123-45-67")
        return
    phone = f"+{digits[0]} {digits[1:4]} {digits[4:7]}-{digits[7:9]}-{digits[9:]}"
    await state.update_data(phone=phone)
    await state.set_state(Booking.confirm)
    data = await state.get_data()
    service = config.service(data["service"])
    await message.answer("Почти готово.", reply_markup=ReplyKeyboardRemove())
    await message.answer(
        "Проверьте запись:\n\n"
        f"Услуга: <b>{service.title}</b>, {service.price} ₽\n"
        f"Когда: <b>{kb.human_date(date.fromisoformat(data['day']))}, {data['time']}</b>\n"
        f"Имя: {escape(data['name'])}\nТелефон: {phone}",
        reply_markup=kb.confirm_kb(),
    )


@router.callback_query(Booking.confirm, kb.ConfirmCb.filter())
async def confirmed(cb: CallbackQuery, callback_data: kb.ConfirmCb, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    if not callback_data.ok:
        await cb.message.edit_text("Запись отменена.")
        await cb.message.answer("Возвращаю в меню.", reply_markup=kb.main_menu())
        return await cb.answer()
    try:
        booking_id = db.create_booking(cb.from_user.id, data["name"], data["phone"], data["service"], data["day"], data["time"])
    except db.SlotTakenError:
        await cb.message.edit_text("К сожалению, это время уже заняли. Нажмите «Записаться» и выберите другое.")
        return await cb.answer()

    service = config.service(data["service"])
    when = f"{kb.human_date(date.fromisoformat(data['day']))}, {data['time']}"
    await cb.message.edit_text(f"✅ Вы записаны: <b>{service.title}</b>, {when}.\nЖдём вас по адресу {config.address}.")
    await cb.message.answer("Если планы изменятся, отменить запись можно в разделе «Мои записи».", reply_markup=kb.main_menu())
    await cb.answer("Готово!")

    for admin_id in config.admin_ids:
        try:
            await bot.send_message(admin_id, f"🆕 Запись #{booking_id}\n{service.title}\n{when}\n{escape(data['name'])}, {escape(data['phone'])}")
        except Exception as exc:  # админ мог не запускать бота
            log.warning("Не удалось уведомить админа %s: %s", admin_id, exc)


@router.message(Booking.name)
@router.message(Booking.phone)
async def wrong_input(message: Message):
    await message.answer("Отправьте ответ текстом. Чтобы прервать запись, напишите «отмена».")


# ---------- Мои записи ----------

@router.message(F.text == kb.BTN_MY)
async def my_bookings(message: Message):
    today = datetime.now(config.tz).date().isoformat()
    items = db.user_bookings(message.from_user.id, today)
    if not items:
        await message.answer("Активных записей нет. Нажмите «Записаться», чтобы выбрать время.")
        return
    text = "\n".join(
        f"• {config.service(b.service).title}, {kb.human_date(date.fromisoformat(b.date))}, {b.time}" for b in items)
    await message.answer("Ваши записи:\n\n" + text, reply_markup=kb.my_bookings_kb(items))


@router.callback_query(kb.CancelCb.filter())
async def cancel_booking(cb: CallbackQuery, callback_data: kb.CancelCb, bot: Bot):
    b = db.cancel_booking(callback_data.booking_id, user_id=cb.from_user.id)
    if not b:
        return await cb.answer("Запись уже отменена", show_alert=True)
    await cb.message.edit_text(f"Запись на {kb.human_date(date.fromisoformat(b.date))}, {b.time} отменена.")
    await cb.answer()
    for admin_id in config.admin_ids:
        try:
            await bot.send_message(admin_id, f"❌ Клиент отменил запись #{b.id}: {b.date} {b.time}, {escape(b.name)}")
        except Exception as exc:
            log.warning("Не удалось уведомить админа %s: %s", admin_id, exc)


# ---------- Админка ----------

@router.message(Command("today", "week"), F.from_user.id.in_(config.admin_ids))
async def admin_list(message: Message):
    today = datetime.now(config.tz).date()
    days = 0 if message.text.startswith("/today") else 6
    items = db.bookings_between(today.isoformat(), (today + timedelta(days=days)).isoformat())
    if not items:
        await message.answer("Записей нет.")
        return
    lines, current = [], None
    for b in items:
        if b.date != current:
            current = b.date
            lines.append(f"\n<b>{kb.human_date(date.fromisoformat(b.date)).capitalize()}</b>")
        lines.append(f"{b.time} · {config.service(b.service).title} · {escape(b.name)}, {escape(b.phone)} (#{b.id})")
    await message.answer("\n".join(lines))


@router.message(Command("drop"), F.from_user.id.in_(config.admin_ids))
async def admin_cancel(message: Message, bot: Bot):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: /drop &lt;номер записи&gt;")
        return
    b = db.cancel_booking(int(parts[1]))
    if not b:
        await message.answer("Активной записи с таким номером нет.")
        return
    await message.answer(f"Запись #{b.id} отменена.")
    try:
        await bot.send_message(b.user_id, f"Ваша запись на {kb.human_date(date.fromisoformat(b.date))}, {b.time} отменена администратором. Позвоните нам: {config.phone}")
    except Exception as exc:
        log.warning("Клиент %s не получил уведомление: %s", b.user_id, exc)
