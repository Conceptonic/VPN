import os
from dotenv import load_dotenv

load_dotenv()

# ===== НАСТРОЙКИ БОТА =====
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Реквизиты для оплаты СБП
SBP_PHONE = os.getenv("SBP_PHONE", "")
SBP_NAME  = os.getenv("SBP_NAME", "")

# ===== БАЗА ДАННЫХ =====
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/vpn_bot")

# ===== НАСТРОЙКИ 3X-UI =====
XUI_HOST       = os.getenv("XUI_HOST", "")
XUI_BASE_PATH  = os.getenv("XUI_BASE_PATH", "")
XUI_PORT       = int(os.getenv("XUI_PORT", "443"))
XUI_LOGIN      = os.getenv("XUI_LOGIN", "")
XUI_PASSWORD   = os.getenv("XUI_PASSWORD", "")
XUI_INBOUND_ID = int(os.getenv("XUI_INBOUND_ID", "1"))

# ===== ТАРИФЫ =====
TARIFFS = {
    "1m": {
        "name":       "1 месяц",
        "price":      100,
        "days":       30,
        "traffic_gb": 0,  # 0 = безлимит
    },
    "3m": {
        "name":       "3 месяца (скидка 5%)",
        "price":      285,
        "days":       90,
        "traffic_gb": 0,
    },
    "6m": {
        "name":       "6 месяцев (скидка 10%)",
        "price":      540,
        "days":       180,
        "traffic_gb": 0,
    },
    "12m": {
        "name":       "12 месяцев (скидка 15%)",
        "price":      1020,
        "days":       360,
        "traffic_gb": 0,
    },
    # Добавляй новые тарифы сюда
}

# За сколько дней напоминать об окончании подписки
REMIND_DAYS_BEFORE = 3

# ===== РЕФЕРАЛЬНАЯ СИСТЕМА =====
REFERRAL_BONUS_DAYS = 30  # дней рефереру за каждого оплатившего друга

# ===== ЛИМИТ УСТРОЙСТВ =====
XUI_LIMIT_IP = 3  # максимум одновременных подключений на один конфиг

# ===== ПРОБНЫЙ ПЕРИОД =====
TRIAL_DAYS = 7  # дней бесплатного пробного периода

# ===== АВТООТКЛЮЧЕНИЕ =====
# Дней после отклонения платежа до удаления из 3x-ui (0 = не удалять)
AUTO_DISCONNECT_AFTER_REJECT_DAYS = 3
# Напоминать за 1 день до истечения (дополнительно к REMIND_DAYS_BEFORE)
REMIND_LAST_DAY = True