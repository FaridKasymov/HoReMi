import os
import asyncio
from dotenv import load_dotenv
from sqlalchemy import select
from db.database import AsyncSessionLocal, engine, Base
from db.models import Hotel, Station, User, HotelState

load_dotenv()

async def seed_data():
    print("Инициализация схемы базы данных...")
    
    # 1. Асинхронное создание таблиц
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2. Асинхронная сессия
    async with AsyncSessionLocal() as db:
        try:
            admin_id_str = os.getenv("ADMIN_ID")
            if not admin_id_str:
                print("❌ Ошибка: ADMIN_ID не задан в .env!")
                return
            
            admin_tg_id = int(admin_id_str)

            # Проверяем, пустая ли база
            result = await db.execute(select(Hotel))
            existing_hotel = result.scalars().first()
            
            if existing_hotel:
                print("⚠️ База уже содержит данные. Пропускаем заполнение (seed).")
                return

            print("Создаем стартовые данные...")

            # 3. Создаем отель (включая адрес для правого нижнего угла)
            plaza = Hotel(
                name="Kaznacheyskiy Hotel", 
                slug="plaza", 
                assets_path="hotels/plaza",
                address="ул. Большой Златоустинский переулок, 7с1 • 71 Big Zlatoustinsky Lane",
                is_active=True
            )
            db.add(plaza)
            await db.flush()  # Получаем plaza.id

            # 4. Создаем радиостанции
            station1 = Station(title="Lounge", stream_url="https://listen4.myradio24.com/lo-fi")
            station2 = Station(title="Lounge", stream_url="https://listen10.myradio24.com/atmo")
            db.add_all([station1, station2])
            await db.flush()  # Получаем их id

            # 5. Привязываем Лаунж-станцию к нашему отелю по умолчанию
            plaza_state = HotelState(
                hotel_id=plaza.id, 
                current_station_id=station1.id
            )
            db.add(plaza_state)

            # 6. Создаем администратора и привязываем к отелю
            admin = User(
                telegram_id=admin_tg_id,
                full_name="Администратор",
                hotel_id=plaza.id, 
                role="admin"
            )
            db.add(admin)

            await db.commit()
            print("✅ База успешно заполнена стартовыми отелями, станциями и админом!")

        except Exception as e:
            await db.rollback()
            print(f"❌ Произошла ошибка при заполнении базы: {e}")

if __name__ == "__main__":
    asyncio.run(seed_data())