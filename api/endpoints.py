import httpx
import uuid
import random
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy import func
from db.models import CustomBlock
from pydantic import BaseModel
from db.models import CustomBlock

from db.database import AsyncSessionLocal
from db.models import Hotel, HotelState, Station, ScreenSession

router = APIRouter()

# Функция-помощник для получения сессии базы данных
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

# Схема для приема данных с фронтенда
class BlockCreate(BaseModel):
    content: str
    position: str

@router.get("/api/display")
async def get_display_data(hotel: str, db: AsyncSession = Depends(get_db)):
    hotel_obj = await db.execute(select(Hotel).where(Hotel.slug == hotel))
    h = hotel_obj.scalar_one_or_none()
    
    if not h:
        return {"status": "error"}
        
    # --- Получаем музыку ---
    state_obj = await db.execute(select(HotelState).where(HotelState.hotel_id == h.id))
    state = state_obj.scalar_one_or_none()
    
    station = {"title": "", "url": ""}
    if state:
        st_obj = await db.execute(select(Station).where(Station.id == state.current_station_id))
        st = st_obj.scalar_one_or_none()
        if st:
            station = {"title": st.title, "url": st.stream_url}

    # --- ПОЛУЧАЕМ ИНФО-БЛОКИ ---
    blocks_res = await db.execute(select(CustomBlock).where(CustomBlock.hotel_id == h.id, CustomBlock.is_active == True))
    blocks = blocks_res.scalars().all()

    return {
        "status": "ok",
        "hotel": {
            "name": h.name,
            "address": h.address,
            "assets_path": h.assets_path
        },
        "station": station,
        "blocks": [{"content": b.content, "position": b.position} for b in blocks] # Отдаем блоки массивом
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

@router.get("/api/dashboard/hotel/{hotel_id}")
async def get_hotel_details(hotel_id: int, db: AsyncSession = Depends(get_db)):
    """Отдает детальную информацию для дашборда отеля"""
    # 1. Получаем отель
    hotel_res = await db.execute(select(Hotel).where(Hotel.id == hotel_id))
    hotel = hotel_res.scalar_one_or_none()
    if not hotel:
        raise HTTPException(status_code=404, detail="Отель не найден")

    screens_res = await db.execute(select(ScreenSession).where(ScreenSession.hotel_id == hotel_id))
    screens = screens_res.scalars().all()

    state_res = await db.execute(select(HotelState).where(HotelState.hotel_id == hotel_id))
    state = state_res.scalar_one_or_none()
    current_station_id = state.current_station_id if state else None

    stations_res = await db.execute(select(Station).where(Station.is_active == True))
    stations = stations_res.scalars().all()

    blocks_res = await db.execute(select(CustomBlock).where(CustomBlock.hotel_id == hotel_id))
    blocks = blocks_res.scalars().all()

    return {
        "status": "ok",
        "hotel": {
            "name": hotel.name,
            "slug": hotel.slug,
            "address": hotel.address,
            "blocks": [{"id": b.id, "content": b.content, "position": b.position} for b in blocks]
        },
        "current_station_id": current_station_id,
        "stations": [{"id": s.id, "title": s.title} for s in stations],
        "screens": [{"id": s.id, "pairing_code": s.pairing_code, "created_at": s.created_at.strftime("%d.%m.%Y %H:%M")} for s in screens]
    }

# 2. НОВЫЙ МАРШРУТ: Добавление блока
@router.post("/api/dashboard/hotel/{hotel_id}/block")
async def add_custom_block(hotel_id: int, block: BlockCreate, db: AsyncSession = Depends(get_db)):
    new_block = CustomBlock(
        hotel_id=hotel_id, 
        content=block.content, 
        position=block.position
    )
    db.add(new_block)
    await db.commit()
    return {"status": "ok"}

# 3. НОВЫЙ МАРШРУТ: Удаление блока
@router.delete("/api/block/{block_id}")
async def delete_block(block_id: int, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(CustomBlock).where(CustomBlock.id == block_id))
    b = res.scalar_one_or_none()
    if b:
        await db.delete(b)
        await db.commit()
    return {"status": "ok"}

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