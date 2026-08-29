import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.database import AsyncSessionLocal
from db.models import Device, Hotel, HotelState, PairingCode, Station

router = APIRouter()

# Функция-помощник для получения сессии базы данных
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

class RegisterDeviceRequest(BaseModel):
    device_uid: str | None = None

def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

async def get_or_create_pairing_code(device: Device, db: AsyncSession) -> PairingCode:
    now = utc_now()
    result = await db.execute(
        select(PairingCode)
        .where(
            PairingCode.device_id == device.id,
            PairingCode.used_at.is_(None),
            PairingCode.expires_at > now,
        )
        .order_by(PairingCode.created_at.desc())
    )
    pairing_code = result.scalars().first()
    if pairing_code:
        return pairing_code

    for _ in range(20):
        code = str(secrets.randbelow(900000) + 100000)
        existing = await db.execute(select(PairingCode.id).where(PairingCode.code == code))
        if existing.scalar_one_or_none() is None:
            pairing_code = PairingCode(
                code=code,
                device_id=device.id,
                expires_at=now + timedelta(minutes=10),
            )
            db.add(pairing_code)
            await db.flush()
            return pairing_code

    raise HTTPException(status_code=503, detail="Не удалось создать код привязки")

@router.post("/api/tv/register")
async def register_tv(payload: RegisterDeviceRequest, db: AsyncSession = Depends(get_db)):
    device_uid = payload.device_uid or uuid4().hex
    result = await db.execute(select(Device).where(Device.device_uid == device_uid))
    device = result.scalar_one_or_none()

    if not device:
        device = Device(device_uid=device_uid)
        db.add(device)
        await db.flush()

    device.last_seen = utc_now()

    if device.hotel_id:
        hotel_result = await db.execute(select(Hotel).where(Hotel.id == device.hotel_id))
        hotel = hotel_result.scalar_one_or_none()
        await db.commit()
        return {
            "status": "paired",
            "device_uid": device.device_uid,
            "hotel": {"name": hotel.name, "slug": hotel.slug} if hotel else None,
        }

    pairing_code = await get_or_create_pairing_code(device, db)
    await db.commit()
    return {
        "status": "waiting",
        "device_uid": device.device_uid,
        "code": pairing_code.code,
        "expires_at": pairing_code.expires_at.isoformat(),
    }

@router.get("/api/tv/status")
async def get_tv_status(device_uid: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Device).where(Device.device_uid == device_uid))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Устройство не найдено")

    device.last_seen = utc_now()

    if device.hotel_id:
        hotel_result = await db.execute(select(Hotel).where(Hotel.id == device.hotel_id))
        hotel = hotel_result.scalar_one_or_none()
        await db.commit()
        return {
            "status": "paired",
            "hotel": {"name": hotel.name, "slug": hotel.slug} if hotel else None,
        }

    pairing_code = await get_or_create_pairing_code(device, db)
    await db.commit()
    return {
        "status": "waiting",
        "code": pairing_code.code,
        "expires_at": pairing_code.expires_at.isoformat(),
    }

@router.get("/api/display")
async def get_display_data(
    hotel: str | None = None,
    device_uid: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Этот эндпоинт опрашивают телевизоры. 
    Пример запроса: GET /api/display?hotel=plaza
    """
    
    if device_uid:
        device_result = await db.execute(select(Device).where(Device.device_uid == device_uid))
        device = device_result.scalar_one_or_none()
        if not device or not device.hotel_id:
            raise HTTPException(status_code=403, detail="Телевизор не привязан к отелю")
        result = await db.execute(select(Hotel).where(Hotel.id == device.hotel_id))
    elif hotel:
        # Старый режим оставлен для совместимости со ссылками вида ?hotel=plaza.
        result = await db.execute(select(Hotel).where(Hotel.slug == hotel))
    else:
        raise HTTPException(status_code=400, detail="Не указан телевизор или отель")

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
