# Fuel Bot (Telegram)

Telegram-бот для учёта топлива и остатка в баке (SsangYong Korando).

## Возможности
- Заправка с распознаванием одометра по фото (OCR)
- Обновление пробега
- Расчёт остатка топлива
- Статистика и экономия (газ vs бензин)

## Быстрый деплой на Railway (рекомендуется)

1. Зайди на https://railway.app и войди через GitHub
2. **New Project** → **Deploy from GitHub repo** → выбери `fuel-bot`
3. В Variables добавь:
   - `BOT_TOKEN` = твой токен от @BotFather
4. Нажми Deploy

Бот запустится автоматически и будет работать 24/7.

## Локальный запуск

```bash
pip install -r requirements.txt
export BOT_TOKEN="твой_токен"
python bot.py
```

## Кнопки
- ⛽ Заправка
- 📷 Пробег
- 📊 Остаток
- 📈 Статистика
