import asyncio
from db.database import AsyncSessionLocal
from db.models import Hotel, User, Station, HotelState

async def seed_data():
    async with AsyncSessionLocal() as session:
        print("Начинаем заполнение базы...")

        # 1. Создаем тестовый отель
        plaza_hotel = Hotel(
            name="Plaza Hotel",
            slug="plaza",
            assets_path="hotels/plaza"
        )
        session.add(plaza_hotel)
        await session.commit() 
        await session.refresh(plaza_hotel) # Обновляем, чтобы получить сгенерированный ID

        # 2. Добавляем пару радиостанций
        station1 = Station(
            title="🎷 Уютный Джаз",
            stream_url="https://listen10.myradio24.com/atmo" # Можешь заменить на свои ссылки
        )
        station2 = Station(
            title="🍹 Лаунж",
            stream_url="https://listen4.myradio24.com/lo-fi"
        )
        session.add_all([station1, station2])
        await session.commit()
        await session.refresh(station1)

        # 3. Добавляем пользователя (тебя)
        # ВНИМАНИЕ: Замени 123456789 на свой реальный Telegram ID!
        admin_user = User(
            telegram_id=276055271, 
            full_name="Главный Админ",
            hotel_id=plaza_hotel.id,
            role="admin"
        )
        session.add(admin_user)

        # 4. Устанавливаем начальное состояние телевизора для Плазы
        initial_state = HotelState(
            hotel_id=plaza_hotel.id,
            current_station_id=station1.id
        )
        session.add(initial_state)

        await session.commit()
        print("✅ База данных успешно заполнена тестовыми данными!")

if __name__ == "__main__":
    asyncio.run(seed_data())