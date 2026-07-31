import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.database import AsyncSessionLocal
from db.models import Hotel, HotelState, Station

router = APIRouter()

# Функция-помощник для получения сессии базы данных
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

@router.get("/api/display")
async def get_display_data(hotel: str, db: AsyncSession = Depends(get_db)):
    """
    Этот эндпоинт опрашивают телевизоры. 
    Пример запроса: GET /api/display?hotel=plaza
    """
    
    # 1. Ищем отель по slug (например, 'plaza')
    result = await db.execute(select(Hotel).where(Hotel.slug == hotel))
    hotel_obj = result.scalar_one_or_none()

    if not hotel_obj:
        raise HTTPException(status_code=404, detail="Отель не найден")

    # Если отель не оплатил подписку
    if not hotel_obj.is_active:
        return {"status": "error", "message": "Подписка неактивна"}

    # 2. Узнаем, какую станцию админ включил в боте
    state_result = await db.execute(select(HotelState).where(HotelState.hotel_id == hotel_obj.id))
    state_obj = state_result.scalar_one_or_none()

    # Дефолтные значения (если отель только добавили и админ еще ничего не нажал)
    station_title = "Ожидание станции..."
    stream_url = ""

    if state_obj:
        # 3. Достаем саму ссылку на радиостанцию
        station_result = await db.execute(select(Station).where(Station.id == state_obj.current_station_id))
        station_obj = station_result.scalar_one_or_none()
        if station_obj and station_obj.is_active:
            station_title = station_obj.title
            stream_url = station_obj.stream_url

    # 4. Формируем красивый JSON для телевизора
    return {
        "status": "ok",
        "hotel": {
            "name": hotel_obj.name,
            # Телевизор поймет, что картинки надо искать по этому пути
            "assets_path": hotel_obj.assets_path 
        },
        "station": {
            "title": station_title,
            "url": stream_url
        }
    }

# Место для твоего прокси погоды 
@router.get("/api/weather/v1/forecast")
async def get_weather(lat: float = 55.75, lon: float = 37.61):
    """
    Прокси для Open-Meteo. 
    По умолчанию установлены координаты Москвы (55.75, 37.61).
    """
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url)
            if response.status_code == 200:
                return {"status": "ok", "data": response.json()}
            return {"status": "error", "message": "Ошибка API погоды"}
        except Exception as e:
            return {"status": "error", "message": str(e)}