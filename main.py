import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from db.database import init_db, seed_default_stations
from api.endpoints import router as api_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Этот код выполняется один раз при запуске сервера
    print("Инициализация базы данных...")
    await init_db()
    await seed_default_stations()
    
    # Создаем папку public, если ее нет (чтобы сервер не упал с ошибкой)
    if not os.path.exists("public"):
        os.makedirs("public")
        
    yield
    print("Сервер остановлен.")

# Создаем само приложение FastAPI
app = FastAPI(title="Hotel Audio SaaS", lifespan=lifespan)

# Подключаем наши маршруты (эндпоинты)
app.include_router(api_router)

@app.get("/", include_in_schema=False)
async def landing_page():
    return FileResponse("public/landing.html")

@app.get("/demo", include_in_schema=False)
async def demo_display():
    return RedirectResponse("/public/index.html?hotel=plaza", status_code=307)

@app.get("/admin", include_in_schema=False)
async def admin_panel():
    return FileResponse("public/admin.html")

@app.get("/dashboard", include_in_schema=False)
async def legacy_dashboard_redirect():
    return RedirectResponse("/admin", status_code=307)

# Разрешаем скачивать картинки и видео по ссылке /public/...
app.mount("/public", StaticFiles(directory="public"), name="public")
