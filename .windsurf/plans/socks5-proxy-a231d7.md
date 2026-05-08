# Настройка SOCKS5 proxy на proxy-сервере

Поднять go-socks5-proxy в Docker на proxy-сервере с авторизацией и автоматическим перезапуском для использования из chatflow-ai.

## Параметры
- **Порт:** 1080 (стандарт SOCKS5, но не 80/443)
- **Пользователь:** `cfai_proxy`
- **Пароль:** случайный 16-символьный

## Шаги
1. Удалить старый контейнер `socks5` на proxy-сервере
2. Запустить `serjs/go-socks5-proxy` с `restart: always`, `PROXY_USER`, `PROXY_PASSWORD`, порт 1080
3. Проверить доступность с prod-сервера (`curl --socks5`)
4. Обновить `src/infrastructure/config.py` — добавить `PROXY_URL` для чтения из env
5. Обновить HTTP-клиенты (TelegramAdapter, OpenRouterAdapter) — пробрасывать `proxies` в `httpx.AsyncClient`
6. Обновить `.env` шаблон и CI/CD secrets
