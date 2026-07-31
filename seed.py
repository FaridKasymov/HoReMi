import asyncio
from sqlalchemy.future import select

# Убедись, что импорты совпадают с твоей структурой проекта
from db.database import engine, AsyncSessionLocal, Base
from db.models import Hotel, Station, HotelState

async def seed_data():
    print("Начинаем подготовку базы...")
    
    # 1. Сначала генерируем структуру таблиц
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Таблицы успешно созданы (или уже существуют).")

    # 2. Заполняем данными
    async with AsyncSessionLocal() as session:
        # Проверяем, есть ли уже отель Plaza, чтобы избежать ошибки дубликатов
        result = await session.execute(select(Hotel).where(Hotel.slug == "plaza"))
        existing_hotel = result.scalar_one_or_none()

        if existing_hotel:
            print("⚠️ База уже заполнена! Повторное добавление отменено.")
            return

        print("Записываем стартовые данные...")
        
        # Создаем отель
        plaza = Hotel(
            name="Plaza Hotel", 
            slug="plaza", 
            assets_path="hotels/plaza", 
            is_active=True
        )
        session.add(plaza)
        await session.commit()
        await session.refresh(plaza) # Обновляем, чтобы получить его ID из базы

        # Создаем радиостанции (можешь поменять ссылки на реальные аудиопотоки)
        station1 = Station(title="🍸 Лаунж", stream_url="https://lounge-stream.example.com")
        station2 = Station(title="🎷 Джаз", stream_url="https://jazz-stream.example.com")
        
        session.add_all([station1, station2])
        await session.commit()
        await session.refresh(station1)

        # Создаем состояние отеля по умолчанию (включаем Лаунж)
        plaza_state = HotelState(
            hotel_id=plaza.id,
            current_station_id=station1.id
        )
        session.add(plaza_state)
        await session.commit()

        print("✅ База успешно заполнена стартовыми отелями и станциями!")

if __name__ == "__main__":
    asyncio.run(seed_data())