from datetime import datetime
from sqlalchemy import String, ForeignKey, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Базовый класс для всех моделей
class Base(DeclarativeBase):
    pass

class Hotel(Base):
    __tablename__ = 'hotels'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(50), unique=True) # Уникальный хвост ссылки, например 'hilton'
    assets_path: Mapped[str] = mapped_column(String(200))      # Путь к папке с логотипами/фото
    is_active: Mapped[bool] = mapped_column(default=True)      # Активна ли подписка отеля

class User(Base):
    __tablename__ = 'users'

    telegram_id: Mapped[int] = mapped_column(primary_key=True) # ID юзера в Telegram
    full_name: Mapped[str] = mapped_column(String(100))
    hotel_id: Mapped[int] = mapped_column(ForeignKey('hotels.id')) # Привязка к отелю
    role: Mapped[str] = mapped_column(String(20), default='employee')

class Station(Base):
    __tablename__ = 'stations'

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(100))             # Например, "🎷 Джаз"
    stream_url: Mapped[str] = mapped_column(String(500))        # Ссылка на поток
    is_active: Mapped[bool] = mapped_column(default=True)

class HotelState(Base):
    __tablename__ = 'hotel_states'

    hotel_id: Mapped[int] = mapped_column(ForeignKey('hotels.id'), primary_key=True)
    current_station_id: Mapped[int] = mapped_column(ForeignKey('stations.id'))
    # Время последнего переключения (сохраняется автоматически)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())