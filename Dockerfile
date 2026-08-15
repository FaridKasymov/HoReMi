FROM python:3.11-slim

WORKDIR /app

# Запрещаем Python писать .pyc файлы на диск и буферизовать stdout/stderr (полезно для логов)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .

# Устанавливаем зависимости без сохранения кеша pip (уменьшает вес образа)
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Открываем порт, на котором будет висеть FastAPI
EXPOSE 8000

# Команда для запуска сервера
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]