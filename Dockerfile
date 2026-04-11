FROM docker.io/library/python:3.14-slim

# 1. Установка uv напрямую из официального образа (экономит время и место)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Настройки для стабильной работы Python и uv
ENV UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# 2. Создаем пользователя заранее, чтобы не делать тяжелый RUN chown -R в конце
RUN useradd -m appuser && chown appuser /app

# 3. Копируем файлы зависимостей сразу с нужными правами
COPY --chown=appuser:appuser pyproject.toml uv.lock ./

# 4. Установка зависимостей БЕЗ кэша (критично для 5ГБ SSD)
# --no-cache экономит около 200-400МБ внутри образа
RUN uv pip install --no-cache -r pyproject.toml

# 5. Копируем остальной код проекта с правами пользователя
COPY --chown=appuser:appuser . .

# Переключаемся на безопасного пользователя
USER appuser

# Проверьте путь: если ваш main.py лежит в src/presentation/api/,
# то команда запуска должна выглядеть так:
CMD ["uvicorn", "presentation.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
