import os
from dataclasses import dataclass, field
from datetime import timedelta, timezone

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Service:
    code: str
    title: str
    price: int
    minutes: int


@dataclass(frozen=True)
class Config:
    token: str = os.getenv("BOT_TOKEN", "")
    admin_ids: tuple[int, ...] = tuple(
        int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x
    )
    tz: timezone = timezone(timedelta(hours=int(os.getenv("TIMEZONE_OFFSET", "3"))))
    db_path: str = os.getenv("DB_PATH", "bookings.db")
    work_start: int = 10          # первый слот, час
    work_end: int = 20            # конец рабочего дня, час: запись должна закончиться к этому времени
    days_ahead: int = 7           # на сколько дней вперёд можно записаться
    business_name: str = "Студия «Бритва»"
    address: str = "Москва, ул. Покровка, 31"
    phone: str = "+7 495 000-00-01"
    services: tuple[Service, ...] = field(default_factory=lambda: (
        Service("cut", "Мужская стрижка", 2200, 60),
        Service("beard", "Моделирование бороды", 1600, 40),
        Service("combo", "Стрижка + борода", 3400, 90),
        Service("shave", "Королевское бритьё", 2000, 45),
    ))

    def service(self, code: str) -> Service | None:
        return next((s for s in self.services if s.code == code), None)


config = Config()
