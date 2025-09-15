# Используем базовый образ с Python
FROM python:3.12-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем зависимости
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код приложения
COPY app/ .

# Указываем порт, который будет использовать приложение
EXPOSE 8000

# Определяем команду для запуска приложения
CMD ["python", "onec_rest_server.py"]