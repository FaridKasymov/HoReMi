import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqladmin import Admin
from db.database import engine
from admin import HotelAdmin, StationAdmin, UserAdmin, ScreenSessionAdmin, CustomBlockAdmin

from db.database import init_db
from api.endpoints import router as api_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Этот код выполняется один раз при запуске сервера
    print("Инициализация базы данных...")
    await init_db()
    
    # Создаем папку public, если ее нет (чтобы сервер не упал с ошибкой)
    if not os.path.exists("public"):
        os.makedirs("public")
        
    yield
    print("Сервер остановлен.")

# Создаем само приложение FastAPI
app = FastAPI(title="Hotel Audio SaaS", lifespan=lifespan)

# Подключаем наши маршруты (эндпоинты)
app.include_router(api_router)

# Разрешаем скачивать картинки и видео по ссылке /public/...
app.mount("/public", StaticFiles(directory="public"), name="public")
# Подключаем веб-админку
admin = Admin(app, engine)
admin.add_view(HotelAdmin)
admin.add_view(StationAdmin)
admin.add_view(UserAdmin)
admin.add_view(ScreenSessionAdmin)
admin.add_view(CustomBlockAdmin)