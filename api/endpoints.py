import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from db.database import AsyncSessionLocal
from db.models import CustomBlock, Device, Hotel, HotelState, PairingCode, ScreenSession, Station

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

class BlockCreate(BaseModel):
    content: str
    position: str

@router.post("/api/screen/init")
async def init_screen(db: AsyncSession = Depends(get_db)):
    """Создает совместимую с админкой экранную сессию."""
    for _ in range(20):
        code = str(secrets.randbelow(900000) + 100000)
        exists = await db.execute(select(ScreenSession.id).where(ScreenSession.pairing_code == code))
        if exists.scalar_one_or_none() is None:
            screen = ScreenSession(pairing_code=code, auth_token=uuid4().hex)
            db.add(screen)
            await db.commit()
            return {"status": "ok", "pairing_code": code, "auth_token": screen.auth_token}
    raise HTTPException(status_code=503, detail="Не удалось создать код экрана")

@router.get("/api/screen/status")
async def get_screen_status(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ScreenSession).where(ScreenSession.auth_token == token))
    screen = result.scalar_one_or_none()
    if not screen:
        raise HTTPException(status_code=404, detail="Сессия экрана не найдена")
    if not screen.hotel_id:
        return {"status": "waiting"}
    hotel_result = await db.execute(select(Hotel).where(Hotel.id == screen.hotel_id))
    hotel = hotel_result.scalar_one_or_none()
    return {"status": "paired", "hotel_slug": hotel.slug if hotel else None}

@router.get("/api/dashboard/hotels")
async def get_dashboard_hotels(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Hotel).order_by(Hotel.id))
    hotels = result.scalars().all()
    data = []
    for hotel in hotels:
        device_count = await db.scalar(select(func.count(Device.id)).where(Device.hotel_id == hotel.id))
        legacy_count = await db.scalar(select(func.count(ScreenSession.id)).where(ScreenSession.hotel_id == hotel.id))
        data.append({
            "id": hotel.id,
            "name": hotel.name,
            "slug": hotel.slug,
            "is_active": hotel.is_active,
            "active_screens": (device_count or 0) + (legacy_count or 0),
        })
    return {"status": "ok", "hotels": data}

@router.get("/api/dashboard/hotel/{hotel_id}")
async def get_hotel_details(hotel_id: int, db: AsyncSession = Depends(get_db)):
    hotel = (await db.execute(select(Hotel).where(Hotel.id == hotel_id))).scalar_one_or_none()
    if not hotel:
        raise HTTPException(status_code=404, detail="Отель не найден")
    state = (await db.execute(select(HotelState).where(HotelState.hotel_id == hotel_id))).scalar_one_or_none()
    stations = (await db.execute(select(Station).where(Station.is_active.is_(True)))).scalars().all()
    blocks = (await db.execute(select(CustomBlock).where(CustomBlock.hotel_id == hotel_id))).scalars().all()
    devices = (await db.execute(select(Device).where(Device.hotel_id == hotel_id))).scalars().all()
    legacy_screens = (await db.execute(select(ScreenSession).where(ScreenSession.hotel_id == hotel_id))).scalars().all()
    screens = [
        {"id": device.id, "device_uid": device.device_uid, "pairing_code": None, "created_at": device.created_at.strftime("%d.%m.%Y %H:%M") if device.created_at else ""}
        for device in devices
    ] + [
        {"id": screen.id, "device_uid": None, "pairing_code": screen.pairing_code, "created_at": screen.created_at.strftime("%d.%m.%Y %H:%M") if screen.created_at else ""}
        for screen in legacy_screens
    ]
    return {
        "status": "ok",
        "hotel": {"name": hotel.name, "slug": hotel.slug, "address": hotel.address, "blocks": [{"id": b.id, "content": b.content, "position": b.position} for b in blocks]},
        "current_station_id": state.current_station_id if state else None,
        "stations": [{"id": station.id, "title": station.title} for station in stations],
        "screens": screens,
    }

@router.post("/api/dashboard/hotel/{hotel_id}/block")
async def add_custom_block(hotel_id: int, block: BlockCreate, db: AsyncSession = Depends(get_db)):
    db.add(CustomBlock(hotel_id=hotel_id, content=block.content, position=block.position))
    await db.commit()
    return {"status": "ok"}

@router.delete("/api/block/{block_id}")
async def delete_block(block_id: int, db: AsyncSession = Depends(get_db)):
    block = (await db.execute(select(CustomBlock).where(CustomBlock.id == block_id))).scalar_one_or_none()
    if block:
        await db.delete(block)
        await db.commit()
    return {"status": "ok"}

@router.post("/api/dashboard/hotel/{hotel_id}/station/{station_id}")
async def set_hotel_station(hotel_id: int, station_id: int, db: AsyncSession = Depends(get_db)):
    station = (await db.execute(select(Station).where(Station.id == station_id, Station.is_active.is_(True)))).scalar_one_or_none()
    if not station:
        raise HTTPException(status_code=404, detail="Станция не найдена")
    state = (await db.execute(select(HotelState).where(HotelState.hotel_id == hotel_id))).scalar_one_or_none()
    if state:
        state.current_station_id = station_id
    else:
        db.add(HotelState(hotel_id=hotel_id, current_station_id=station_id))
    await db.commit()
    return {"status": "ok"}

@router.delete("/api/screen/{session_id}")
async def unlink_screen(session_id: int, db: AsyncSession = Depends(get_db)):
    device = (await db.execute(select(Device).where(Device.id == session_id))).scalar_one_or_none()
    if device:
        device.hotel_id = None
        await db.commit()
        return {"status": "ok"}
    screen = (await db.execute(select(ScreenSession).where(ScreenSession.id == session_id))).scalar_one_or_none()
    if screen:
        await db.delete(screen)
        await db.commit()
    return {"status": "ok"}


# --- HoReMi dashboard API -------------------------------------------------

class HotelCreate(BaseModel):
    name: str
    slug: str
    address: str | None = None
    assets_path: str | None = None
    is_active: bool = True


class HotelUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    address: str | None = None
    assets_path: str | None = None
    is_active: bool | None = None


class StationCreate(BaseModel):
    title: str
    stream_url: str
    status: str | None = None
    is_active: bool = True


class StationUpdate(BaseModel):
    title: str | None = None
    stream_url: str | None = None
    status: str | None = None
    is_active: bool | None = None


class DeviceUpdate(BaseModel):
    name: str | None = None
    hotel_id: int | None = None


def clean_required(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail=f"Поле «{field_name}» не может быть пустым")
    return cleaned


def clean_slug(value: str) -> str:
    slug = value.strip().lower()
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-")
    if not slug or any(char not in allowed for char in slug):
        raise HTTPException(
            status_code=422,
            detail="Slug может содержать только латинские буквы, цифры и дефис",
        )
    return slug


async def serialize_hotel(hotel: Hotel, db: AsyncSession) -> dict:
    devices = (await db.execute(select(Device).where(Device.hotel_id == hotel.id))).scalars().all()
    online_since = utc_now() - timedelta(seconds=90)
    state = (
        await db.execute(select(HotelState).where(HotelState.hotel_id == hotel.id))
    ).scalar_one_or_none()
    station = None
    if state:
        station = (
            await db.execute(select(Station).where(Station.id == state.current_station_id))
        ).scalar_one_or_none()
    return {
        "id": hotel.id,
        "name": hotel.name,
        "slug": hotel.slug,
        "address": hotel.address or "",
        "assets_path": hotel.assets_path,
        "is_active": hotel.is_active,
        "devices_total": len(devices),
        "devices_online": sum(
            1 for device in devices if device.last_seen and device.last_seen >= online_since
        ),
        "station": {"id": station.id, "title": station.title} if station else None,
    }


@router.get("/api/admin/overview")
async def get_admin_overview(db: AsyncSession = Depends(get_db)):
    hotels = (await db.execute(select(Hotel).order_by(Hotel.name))).scalars().all()
    devices = (await db.execute(select(Device).order_by(Device.last_seen.desc()))).scalars().all()
    stations = (await db.execute(select(Station).order_by(Station.title))).scalars().all()
    online_since = utc_now() - timedelta(seconds=90)
    return {
        "status": "ok",
        "stats": {
            "hotels": len(hotels),
            "active_hotels": sum(1 for hotel in hotels if hotel.is_active),
            "devices": len(devices),
            "online_devices": sum(
                1 for device in devices if device.last_seen and device.last_seen >= online_since
            ),
            "stations": len(stations),
            "active_stations": sum(1 for station in stations if station.is_active),
        },
        "recent_devices": [
            {
                "id": device.id,
                "name": device.name,
                "hotel_id": device.hotel_id,
                "last_seen": device.last_seen.isoformat() if device.last_seen else None,
                "is_online": bool(device.last_seen and device.last_seen >= online_since),
            }
            for device in devices[:5]
        ],
    }


@router.get("/api/admin/hotels")
async def get_admin_hotels(db: AsyncSession = Depends(get_db)):
    hotels = (await db.execute(select(Hotel).order_by(Hotel.name))).scalars().all()
    return {"status": "ok", "hotels": [await serialize_hotel(hotel, db) for hotel in hotels]}


@router.post("/api/admin/hotels")
async def create_admin_hotel(payload: HotelCreate, db: AsyncSession = Depends(get_db)):
    name = clean_required(payload.name, "Название")
    slug = clean_slug(payload.slug)
    hotel = Hotel(
        name=name,
        slug=slug,
        address=(payload.address or "").strip() or None,
        assets_path=(payload.assets_path or f"hotels/{slug}").strip(),
        is_active=payload.is_active,
    )
    db.add(hotel)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Отель с таким slug уже существует")
    await db.refresh(hotel)
    return {"status": "ok", "hotel": await serialize_hotel(hotel, db)}


@router.patch("/api/admin/hotels/{hotel_id}")
async def update_admin_hotel(
    hotel_id: int, payload: HotelUpdate, db: AsyncSession = Depends(get_db)
):
    hotel = (await db.execute(select(Hotel).where(Hotel.id == hotel_id))).scalar_one_or_none()
    if not hotel:
        raise HTTPException(status_code=404, detail="Отель не найден")

    values = payload.model_dump(exclude_unset=True)
    if "name" in values:
        hotel.name = clean_required(values["name"], "Название")
    if "slug" in values:
        hotel.slug = clean_slug(values["slug"])
    if "address" in values:
        hotel.address = (values["address"] or "").strip() or None
    if "assets_path" in values:
        hotel.assets_path = clean_required(values["assets_path"] or "", "Папка медиа")
    if "is_active" in values:
        hotel.is_active = values["is_active"]
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Отель с таким slug уже существует")
    return {"status": "ok", "hotel": await serialize_hotel(hotel, db)}


@router.get("/api/admin/stations")
async def get_admin_stations(db: AsyncSession = Depends(get_db)):
    stations = (await db.execute(select(Station).order_by(Station.title))).scalars().all()
    usage_rows = await db.execute(
        select(HotelState.current_station_id, func.count(HotelState.hotel_id)).group_by(
            HotelState.current_station_id
        )
    )
    usage = dict(usage_rows.all())
    return {
        "status": "ok",
        "stations": [
            {
                "id": station.id,
                "title": station.title,
                "stream_url": station.stream_url,
                "status": station.status or "",
                "is_active": station.is_active,
                "hotels_count": usage.get(station.id, 0),
            }
            for station in stations
        ],
    }


@router.post("/api/admin/stations")
async def create_admin_station(payload: StationCreate, db: AsyncSession = Depends(get_db)):
    station = Station(
        title=clean_required(payload.title, "Название"),
        stream_url=clean_required(payload.stream_url, "Ссылка на поток"),
        status=(payload.status or "").strip() or None,
        is_active=payload.is_active,
    )
    db.add(station)
    await db.commit()
    await db.refresh(station)
    return {"status": "ok", "station_id": station.id}


@router.patch("/api/admin/stations/{station_id}")
async def update_admin_station(
    station_id: int, payload: StationUpdate, db: AsyncSession = Depends(get_db)
):
    station = (
        await db.execute(select(Station).where(Station.id == station_id))
    ).scalar_one_or_none()
    if not station:
        raise HTTPException(status_code=404, detail="Станция не найдена")
    values = payload.model_dump(exclude_unset=True)
    if "title" in values:
        station.title = clean_required(values["title"], "Название")
    if "stream_url" in values:
        station.stream_url = clean_required(values["stream_url"], "Ссылка на поток")
    if "status" in values:
        station.status = (values["status"] or "").strip() or None
    if "is_active" in values:
        station.is_active = values["is_active"]
    await db.commit()
    return {"status": "ok"}


@router.delete("/api/admin/stations/{station_id}")
async def delete_admin_station(station_id: int, db: AsyncSession = Depends(get_db)):
    station = (
        await db.execute(select(Station).where(Station.id == station_id))
    ).scalar_one_or_none()
    if not station:
        raise HTTPException(status_code=404, detail="Станция не найдена")
    used_by = await db.scalar(
        select(func.count(HotelState.hotel_id)).where(HotelState.current_station_id == station_id)
    )
    if used_by:
        raise HTTPException(
            status_code=409,
            detail="Станция используется отелями. Сначала назначьте им другую станцию.",
        )
    await db.delete(station)
    await db.commit()
    return {"status": "ok"}


@router.get("/api/admin/devices")
async def get_admin_devices(db: AsyncSession = Depends(get_db)):
    devices = (await db.execute(select(Device).order_by(Device.last_seen.desc()))).scalars().all()
    hotels = (await db.execute(select(Hotel))).scalars().all()
    hotel_names = {hotel.id: hotel.name for hotel in hotels}
    online_since = utc_now() - timedelta(seconds=90)
    data = []
    for device in devices:
        pairing = (
            await db.execute(
                select(PairingCode)
                .where(PairingCode.device_id == device.id)
                .order_by(PairingCode.created_at.desc())
            )
        ).scalars().first()
        data.append(
            {
                "id": device.id,
                "device_uid": device.device_uid,
                "name": device.name,
                "hotel_id": device.hotel_id,
                "hotel_name": hotel_names.get(device.hotel_id),
                "created_at": device.created_at.isoformat() if device.created_at else None,
                "last_seen": device.last_seen.isoformat() if device.last_seen else None,
                "is_online": bool(device.last_seen and device.last_seen >= online_since),
                "pairing_code": (
                    pairing.code
                    if pairing and pairing.used_at is None and pairing.expires_at > utc_now()
                    else None
                ),
            }
        )
    return {"status": "ok", "devices": data}


@router.patch("/api/admin/devices/{device_id}")
async def update_admin_device(
    device_id: int, payload: DeviceUpdate, db: AsyncSession = Depends(get_db)
):
    device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Телевизор не найден")
    values = payload.model_dump(exclude_unset=True)
    if "name" in values:
        device.name = clean_required(values["name"] or "", "Название")
    if "hotel_id" in values:
        if values["hotel_id"] is not None:
            hotel = (
                await db.execute(select(Hotel).where(Hotel.id == values["hotel_id"]))
            ).scalar_one_or_none()
            if not hotel:
                raise HTTPException(status_code=404, detail="Отель не найден")
        device.hotel_id = values["hotel_id"]
    await db.commit()
    return {"status": "ok"}
