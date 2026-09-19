import os

# ============================================================
# НАСТРОЙКИ БОТА
# ============================================================
BOT_TOKEN = "8813946651:AAESyWudhb919ff31FZiBtI0Ohs9TkEZ5EI"

YOUR_ID = 7823802800          # твой Telegram ID
HER_ID = 5724121519                # её ID (узнаешь после /start — увидишь в логах)

# 📅 Даты
START_DATE = "2026-04-17 03:23"       # когда начали встречаться
DATE_EVENT = "2026-10-14 03:23"       # романтический вечер
HER_BIRTHDAY = "2026-11-17"           # её ДР (год-месяц-день)
YOUR_BIRTHDAY = "2026-03-05"          # твой ДР

# ⏰ Уведомления
MORNING_TIME = "09:00"
DAY_COMPLIMENT_TIME = "12:00"
NIGHT_TIME = "22:00"

# 📁 БД
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "data.json")