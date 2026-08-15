import httpx
import uuid
import random
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy import func
from db.models import CustomBlock

from db.database import AsyncSessionLocal
from db.models import Hotel, HotelState, Station, ScreenSession

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
            "assets_path": hotel_obj.assets_path,
            "address": hotel_obj.address
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

@router.post("/api/screen/init")
async def init_screen(db: AsyncSession = Depends(get_db)):
    """Выдает экрану уникальный токен и 6-значный код сопряжения"""
    # Генерируем 6 случайных цифр
    pairing_code = str(random.randint(100000, 999999))
    auth_token = str(uuid.uuid4())
    
    new_session = ScreenSession(
        pairing_code=pairing_code,
        auth_token=auth_token
    )
    db.add(new_session)
    await db.commit()
    
    return {"status": "ok", "pairing_code": pairing_code, "auth_token": auth_token}

@router.get("/api/screen/status")
async def get_screen_status(token: str, db: AsyncSession = Depends(get_db)):
    """Позволяет экрану узнать, привязал ли его админ к отелю"""
    result = await db.execute(select(ScreenSession).where(ScreenSession.auth_token == token))
    session_obj = result.scalar_one_or_none()
    
    if not session_obj:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
        
    if session_obj.hotel_id:
        # Экран привязан! Отдаем slug отеля, чтобы фронтенд знал, чью музыку играть
        hotel_result = await db.execute(select(Hotel).where(Hotel.id == session_obj.hotel_id))
        hotel_obj = hotel_result.scalar_one_or_none()
        return {"status": "paired", "hotel_slug": hotel_obj.slug}
    else:
        return {"status": "waiting"}

@router.get("/api/dashboard/hotels")
async def get_dashboard_hotels(db: AsyncSession = Depends(get_db)):
    """Возвращает список отелей для дашборда в виде карточек"""
    result = await db.execute(select(Hotel))
    hotels = result.scalars().all()
    
    data = []
    for h in hotels:
        # Считаем количество привязанных экранов для каждого отеля
        screens_res = await db.execute(
            select(func.count(ScreenSession.id)).where(ScreenSession.hotel_id == h.id)
        )
        screens_count = screens_res.scalar()
        
        data.append({
            "id": h.id,
            "name": h.name,
            "slug": h.slug,
            "is_active": h.is_active,
            "active_screens": screens_count
        })
        
    return {"status": "ok", "hotels": data}

from db.models import HotelState

@router.get("/api/dashboard/hotel/{hotel_id}")
async def get_hotel_details(hotel_id: int, db: AsyncSession = Depends(get_db)):
    """Отдает детальную информацию для дашборда отеля"""
    # 1. Получаем отель
    hotel_res = await db.execute(select(Hotel).where(Hotel.id == hotel_id))
    hotel = hotel_res.scalar_one_or_none()
    if not hotel:
        raise HTTPException(status_code=404, detail="Отель не найден")

    # 2. Получаем привязанные экраны
    screens_res = await db.execute(select(ScreenSession).where(ScreenSession.hotel_id == hotel_id))
    screens = screens_res.scalars().all()

    # 3. Узнаем, какая станция сейчас играет
    state_res = await db.execute(select(HotelState).where(HotelState.hotel_id == hotel_id))
    state = state_res.scalar_one_or_none()
    current_station_id = state.current_station_id if state else None

    # 4. Получаем список всех доступных радиостанций
    stations_res = await db.execute(select(Station).where(Station.is_active == True))
    stations = stations_res.scalars().all()

    return {
        "status": "ok",
        "hotel": {
            "name": hotel.name,
            "slug": hotel.slug,
            "address": hotel.address,
        },
        "current_station_id": current_station_id,
        "stations": [{"id": s.id, "title": s.title} for s in stations],
        "screens": [{"id": s.id, "pairing_code": s.pairing_code, "created_at": s.created_at.strftime("%d.%m.%Y %H:%M")} for s in screens]
    }

@router.post("/api/dashboard/hotel/{hotel_id}/station/{station_id}")
async def set_hotel_station(hotel_id: int, station_id: int, db: AsyncSession = Depends(get_db)):
    """Меняет радиостанцию для всего отеля"""
    state_res = await db.execute(select(HotelState).where(HotelState.hotel_id == hotel_id))
    state = state_res.scalar_one_or_none()
    
    if state:
        state.current_station_id = station_id
    else:
        state = HotelState(hotel_id=hotel_id, current_station_id=station_id)
        db.add(state)
        
    await db.commit()
    return {"status": "ok"}

@router.delete("/api/screen/{session_id}")
async def unlink_screen(session_id: int, db: AsyncSession = Depends(get_db)):
    """Отвязывает экран от отеля (удаляет сессию)"""
    screen_res = await db.execute(select(ScreenSession).where(ScreenSession.id == session_id))
    screen = screen_res.scalar_one_or_none()
    
    if screen:
        await db.delete(screen)
        await db.commit()
    return {"status": "ok"}