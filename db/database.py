from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from db.models import Base

# Файл базы данных будет создан в корне проекта
DATABASE_URL = "sqlite+aiosqlite:///./db/database.db"

# Создаем асинхронный движок
engine = create_async_engine(DATABASE_URL, echo=False)

# Фабрика сессий для работы с БД
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def init_db():
    """Функция для создания таблиц при старте приложения"""
    async with engine.begin() as conn:
        # Создаем все таблицы, если их еще нет
        await conn.run_sync(Base.metadata.create_all)