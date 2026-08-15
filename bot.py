import asyncio
import logging
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from sqlalchemy import select
from db.database import AsyncSessionLocal
from db.models import User, Station, HotelState, Hotel, ScreenSession

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("BOT_TOKEN is not set")

bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    async with AsyncSessionLocal() as session:
        # 1. Проверяем, есть ли этот пользователь в базе
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = result.scalar_one_or_none()

        if not user:
            await message.answer("⛔️ Доступ запрещен. Вы не числитесь сотрудником ни одного из отелей.")
            return

        # 2. Узнаем, в каком он отеле
        hotel_result = await session.execute(select(Hotel).where(Hotel.id == user.hotel_id))
        hotel = hotel_result.scalar_one_or_none()

        # 3. Достаем все активные станции из базы
        stations_result = await session.execute(select(Station).where(Station.is_active == True))
        stations = stations_result.scalars().all()

        # 4. Собираем красивые кнопки
        builder = InlineKeyboardBuilder()
        for station in stations:
            # В callback_data зашиваем ID станции (например, "station_1")
            builder.button(text=station.title, callback_data=f"station_{station.id}")
        builder.adjust(1) # По одной кнопке в ряд

        await message.answer(
            f"🏨 Добро пожаловать, {user.full_name}!\n"
            f"Отель: <b>{hotel.name}</b>\n\n"
            f"🎵 Выберите радиостанцию для лобби:",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )

# Этот хендлер ловит нажатия на инлайн-кнопки
@dp.callback_query(F.data.startswith("station_"))
async def change_station(callback: types.CallbackQuery):
    # Достаем ID станции из строки "station_1"
    station_id = int(callback.data.split("_")[1])
    
    async with AsyncSessionLocal() as session:
        # Снова проверяем пользователя для безопасности
        result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.scalar_one_or_none()
        
        if not user:
            await callback.answer("Ошибка доступа", show_alert=True)
            return

        # Обновляем состояние отеля
        state_result = await session.execute(select(HotelState).where(HotelState.hotel_id == user.hotel_id))
        state = state_result.scalar_one_or_none()
        
        if state:
            state.current_station_id = station_id
        else:
            # Если состояния почему-то не было, создаем
            state = HotelState(hotel_id=user.hotel_id, current_station_id=station_id)
            session.add(state)
            
        await session.commit()
        
        # Получаем название станции для красивого ответа
        station_result = await session.execute(select(Station).where(Station.id == station_id))
        station = station_result.scalar_one_or_none()

        # Незаметное уведомление сверху
        await callback.answer(f"Включаю: {station.title}")
        # Сообщение в чат
        await callback.message.answer(f"✅ Музыка переключена на: <b>{station.title}</b>", parse_mode="HTML")

# Ловим сообщения, состоящие ровно из 6 цифр
@dp.message(F.text.regexp(r'^\d{6}$'))
async def link_screen(message: types.Message):
    code = message.text
    
    async with AsyncSessionLocal() as session:
        # Проверяем права пользователя
        user_res = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = user_res.scalar_one_or_none()
        
        if not user:
            await message.answer("⛔️ У вас нет прав для привязки экранов.")
            return

        # Ищем сессию с таким кодом
        screen_res = await session.execute(select(ScreenSession).where(ScreenSession.pairing_code == code))
        screen = screen_res.scalar_one_or_none()
        
        if not screen:
            await message.answer("❌ Код не найден. Убедитесь, что экран включен, и попробуйте еще раз.")
            return
            
        if screen.hotel_id:
            await message.answer("⚠️ Этот экран уже привязан к отелю.")
            return
            
        # Привязываем экран к отелю текущего администратора
        screen.hotel_id = user.hotel_id
        await session.commit()
        
        await message.answer("✅ Отлично! Экран успешно привязан. Музыка сейчас заиграет.")

async def main():
    logging.basicConfig(level=logging.INFO)
    print("Бот запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())