from sqlalchemy import text
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
        # create_all не меняет уже существующие SQLite-таблицы.
        columns = await conn.execute(text("PRAGMA table_info(stations)"))
        if "status" not in {row[1] for row in columns.fetchall()}:
            await conn.execute(text("ALTER TABLE stations ADD COLUMN status VARCHAR(120)"))

async def seed_default_stations():
    """Заполняет общий каталог станций после создания схемы базы."""
    from sqlalchemy import select
    from db.models import HotelState, Station

    default_stations = [
        ("atmo", "https://listen10.myradio24.com/atmo", "Радио Атмосфера", "Прямой эфир · Lounge"),
        ("jazz", "https://nashe1.hostingradio.ru/jazz-128.mp3", "Radio Jazz", "Прямой эфир · Jazz"),
        ("lofi", "http://stream.zeno.fm/f3wvbbqmdg8uv", "Lo-Fi Radio", "Прямой эфир · Chill"),
        ("classic", "http://stream.srg-ssr.ch/m/rsc_de/mp3_128", "Swiss Classic", "Прямой эфир · Classical"),
        ("cafe", "https://streams.radio.co/se1a320b47/listen", "Cafe Del Mar", "Прямой эфир · Electronic"),
        ("energy", "http://listen.rpfm.ru:9000/premium128", "Радио Premium", "Прямой эфир · Dance / Pop"),
        ("chillhouse", "https://radiorecord.hostingradio.ru/chillhouse96.aacp", "Chill House", "Прямой эфир · Electronic"),
    ]
    async with AsyncSessionLocal() as session:
        for key, stream_url, title, status in default_stations:
            lookup_urls = [stream_url]
            if key == "lofi":
                lookup_urls.append("https://listen4.myradio24.com/lo-fi")
            stations = (await session.execute(
                select(Station).where(Station.stream_url.in_(lookup_urls)).order_by(Station.id)
            )).scalars().all()
            if stations:
                used_ids = set((await session.execute(select(HotelState.current_station_id))).scalars().all())
                station = next((item for item in stations if item.id in used_ids), stations[0])
                station.stream_url = stream_url
                station.title = title
                station.status = status
                station.is_active = True
                for duplicate in stations:
                    if duplicate.id != station.id and duplicate.id not in used_ids:
                        await session.delete(duplicate)
            else:
                session.add(Station(title=title, stream_url=stream_url, status=status, is_active=True))
        await session.commit()
