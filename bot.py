import logging
import urllib3
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

import config
import database as db
import xui_api as xui

urllib3.disable_warnings()

# Отключаем httpx INFO-логи — они пишут полный URL включая токен бота
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("hpack").setLevel(logging.WARNING)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)


# ─────────────────────────── HELPERS ────────────────────────────

def format_sub_message(sub_link: str, config_link: str, tariff_name: str, expire_date: str, is_new: bool = True) -> tuple[str, str]:
    """
    Формирует два сообщения:
    - первое: информация о подписке + инструкция
    - второе: ссылка отдельно для удобного копирования
    """
    action = "активирован" if is_new else "продлена"
    header = f"✅ <b>Оплата подтверждена! Доступ {action}.</b>" if is_new else f"✅ <b>Подписка {action}!</b>"
    date_word = "Действует" if is_new else "Активна"

    main_text = (
        f"{header}\n\n"
        f"📦 Тариф: {tariff_name}\n"
        f"📅 {date_word} до: {expire_date}\n\n"
    )

    if sub_link:
        sub_link_display = sub_link.replace("/s/", "/sub/")
        link_text = f"📲 Инструкция для подключения: <a href=\"{sub_link_display}\">{sub_link_display}</a>"
    else:
        link_text = f"<code>{config_link}</code>"

    return main_text, link_text


def parse_dt(val) -> datetime:
    """
    Универсальный парсер даты.
    PostgreSQL возвращает datetime-объект, SQLite возвращал строку —
    эта функция обрабатывает оба варианта.
    """
    if isinstance(val, datetime):
        return val
    return datetime.strptime(str(val)[:19], "%Y-%m-%d %H:%M:%S")


def is_admin(user_id: int) -> bool:
    return user_id == config.ADMIN_ID


def tariff_keyboard():
    buttons = []
    for key, t in config.TARIFFS.items():
        buttons.append([InlineKeyboardButton(
            f"📦 {t['name']} — {t['price']} ₽",
            callback_data=f"buy_{key}"
        )])
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(buttons)


def main_keyboard(user_id: int = None):
    buttons = [
        [InlineKeyboardButton("🛒 Купить VPN", callback_data="show_tariffs")],
        [InlineKeyboardButton("🎁 Попробовать бесплатно (7 дней)", callback_data="trial")],
        [InlineKeyboardButton("📊 Мой статус", callback_data="my_status")],
        [InlineKeyboardButton("👥 Рефералы", callback_data="referrals")],
        [InlineKeyboardButton("📖 Инструкция", callback_data="instruction")],
        [InlineKeyboardButton("💬 Поддержка", url=f"https://t.me/{config.ADMIN_USERNAME}")],
    ]
    if user_id and is_admin(user_id):
        buttons.append([InlineKeyboardButton("🖥 Статистика сервера", callback_data="server_stats")])
    return InlineKeyboardMarkup(buttons)


def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Статистика", callback_data="admin_stats"),
         InlineKeyboardButton("📊 Аналитика", callback_data="admin_analytics")],
        [InlineKeyboardButton("👥 Пользователи", callback_data="admin_users_0")],
        [InlineKeyboardButton("💰 Платежи", callback_data="admin_payments_0")],
        [InlineKeyboardButton("📦 Подписки", callback_data="admin_subs_0")],
        [InlineKeyboardButton("📥 Экспорт CSV", callback_data="admin_export")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_main")],
    ])


def main_text(first_name: str) -> str:
    return (
        f"👋 Привет, <b>{first_name}</b>!\n\n"
        f"🔐 Это бот для покупки VPN.\n"
        f"Быстрый, стабильный, сервер в Германии 🇩🇪\n\n"
        f"Выбери действие:"
    )


def status_emoji(status: str) -> str:
    return {"confirmed": "✅", "waiting": "⏳", "rejected": "❌"}.get(status, "❓")


def get_server_stats() -> str:
    import requests as req
    try:
        def query(q):
            r = req.get("http://localhost:9090/api/v1/query",
                        params={"query": q}, timeout=5)
            result = r.json().get("data", {}).get("result", [])
            return float(result[0]["value"][1]) if result else 0

        vpn_clients = int(query('sum(xui_online_clients) or vector(0)'))
        cpu = query('100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[2m])) * 100)')
        ram_used = query('node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes')
        ram_total = query('node_memory_MemTotal_bytes')
        ram_pct = (ram_used / ram_total * 100) if ram_total > 0 else 0
        disk_used = query('node_filesystem_size_bytes{mountpoint="/"} - node_filesystem_free_bytes{mountpoint="/"}')
        disk_total = query('node_filesystem_size_bytes{mountpoint="/"}')
        disk_pct = (disk_used / disk_total * 100) if disk_total > 0 else 0
        net_in = query('rate(node_network_receive_bytes_total{device="eth0"}[2m])')
        net_out = query('rate(node_network_transmit_bytes_total{device="eth0"}[2m])')
        uptime = query('node_time_seconds - node_boot_time_seconds')

        uptime_h = int(uptime // 3600)
        uptime_m = int((uptime % 3600) // 60)

        def mb(b): return f"{b / 1024 / 1024:.1f} МБ/с"
        def gb(b): return f"{b / 1024 / 1024 / 1024:.1f} ГБ"

        return (
            f"🖥 <b>Статистика сервера</b>\n"
            f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"⏱ Uptime: <b>{uptime_h}ч {uptime_m}м</b>\n"
            f"🔵 VPN клиенты онлайн: <b>{vpn_clients}</b>\n\n"
            f"💻 CPU: <b>{cpu:.1f}%</b>\n"
            f"🧠 RAM: <b>{ram_pct:.1f}%</b> ({gb(ram_used)} / {gb(ram_total)})\n"
            f"💾 Диск: <b>{disk_pct:.1f}%</b> ({gb(disk_used)} / {gb(disk_total)})\n"
            f"⬇ Сеть in: <b>{mb(net_in)}</b>\n"
            f"⬆ Сеть out: <b>{mb(net_out)}</b>"
        )
    except Exception as e:
        logger.error(f"Ошибка получения метрик: {e}")
        return "❌ Не удалось получить метрики сервера."


async def notify_admin(context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None):
    try:
        await context.bot.send_message(
            chat_id=config.ADMIN_ID,
            text=text,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления админа: {e}")


# ─────────────────────────── ADMIN HANDLERS ────────────────────────────

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Нет доступа.")
        return
    await update.message.reply_text(
        "🔧 <b>Админ-панель</b>",
        reply_markup=admin_keyboard(),
        parse_mode="HTML"
    )


async def find_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Нет доступа.")
        return

    if not context.args:
        await update.message.reply_text("Использование: /find <tg_id>\nПример: /find 123456789")
        return

    try:
        tg_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Неверный ID. Укажи числовой Telegram ID.")
        return

    data = db.find_user(tg_id)
    if not data:
        await update.message.reply_text(
            f"❌ Пользователь <code>{tg_id}</code> не найден.", parse_mode="HTML"
        )
        return

    user = data["user"]
    sub  = data["subscription"]
    payments = data["payments"]

    text = (
        f"👤 <b>Пользователь</b>\n"
        f"🆔 ID: <code>{user['tg_id']}</code>\n"
        f"👤 Имя: {user['full_name'] or '—'}\n"
        f"📎 Username: @{user['username'] or '—'}\n"
        f"📅 Регистрация: {str(user['created_at'])[:10]}\n\n"
    )

    if sub:
        tariff = config.TARIFFS.get(sub["tariff_key"], {})
        expires = parse_dt(sub["expires_at"])
        days_left = (expires - datetime.now()).days
        sub_status = "✅ Активна" if sub["status"] == "active" else "❌ Истекла"
        text += (
            f"📦 <b>Подписка</b>\n"
            f"Тариф: {tariff.get('name', sub['tariff_key'])}\n"
            f"Статус: {sub_status}\n"
            f"До: {expires.strftime('%d.%m.%Y')} ({days_left} дн.)\n"
            f"Конфиг: <code>{sub['config_link']}</code>\n\n"
        )
    else:
        text += "📦 <b>Подписка:</b> нет\n\n"

    if payments:
        text += "💰 <b>Последние оплаты:</b>\n"
        for p in payments:
            emoji = status_emoji(p["status"])
            tariff = config.TARIFFS.get(p["tariff_key"], {})
            text += f"{emoji} {str(p['created_at'])[:10]} — {tariff.get('name', p['tariff_key'])} — {p['amount']} ₽\n"
    else:
        text += "💰 <b>Оплат нет</b>"

    await update.message.reply_text(text, parse_mode="HTML")


# ─────────────────────────── HANDLERS ────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # Обрабатываем реферальную ссылку /start ref_12345
    referred_by = None
    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            try:
                referrer_id = int(arg[4:])
                if referrer_id != user.id:  # нельзя пригласить самого себя
                    referred_by = referrer_id
            except ValueError:
                pass

    db.add_user(user.id, user.username, user.full_name, referred_by)

    if referred_by:
        await update.message.reply_text(
            f"👋 Привет, <b>{user.first_name}</b>!\n\n"
            f"🎁 Ты пришёл по реферальной ссылке — твой друг получит бонус когда ты купишь подписку!\n\n"
            f"Выбери действие:",
            reply_markup=main_keyboard(user.id),
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            main_text(user.first_name),
            reply_markup=main_keyboard(user.id),
            parse_mode="HTML"
        )


async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Нажмите /start для начала",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Старт", callback_data="back_main")]
        ])
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user

    # ── Статистика сервера (только админ) ──
    if data == "server_stats":
        if not is_admin(user.id):
            await query.answer("⛔ Нет доступа", show_alert=True)
            return
        await query.edit_message_text("⏳ Получаю метрики...", parse_mode="HTML")
        stats = get_server_stats()
        await query.edit_message_text(
            stats,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Обновить", callback_data="server_stats")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="back_main")],
            ]),
            parse_mode="HTML"
        )

    # ── Админ-панель ──
    elif data == "admin_menu":
        if not is_admin(user.id):
            await query.answer("⛔ Нет доступа", show_alert=True)
            return
        await query.edit_message_text(
            "🔧 <b>Админ-панель</b>",
            reply_markup=admin_keyboard(),
            parse_mode="HTML"
        )

    # ── Статистика бизнеса ──
    elif data == "admin_stats":
        if not is_admin(user.id):
            return
        stats = db.get_stats()
        text = (
            f"📈 <b>Статистика</b>\n"
            f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"👥 Пользователей: <b>{stats['total_users']}</b>\n"
            f"📦 Активных подписок: <b>{stats['active_subs']}</b>\n\n"
            f"💰 Оплат сегодня: <b>{stats['payments_today_count']}</b>\n"
            f"💸 Выручка сегодня: <b>{stats['payments_today_sum']} ₽</b>\n\n"
            f"💰 Оплат всего: <b>{stats['payments_total_count']}</b>\n"
            f"💸 Выручка всего: <b>{stats['payments_total_sum']} ₽</b>\n\n"
            f"⏳ Ожидают подтверждения: <b>{stats['pending_payments']}</b>"
        )
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Обновить", callback_data="admin_stats")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")],
            ]),
            parse_mode="HTML"
        )

    # ── Расширенная аналитика ──
    elif data == "admin_analytics":
        if not is_admin(user.id):
            return
        s = db.get_extended_stats()
        conv_pct = round(s["trial_converted"] / s["trial_total"] * 100) if s["trial_total"] > 0 else 0
        tariff_lines = ""
        for t in s["tariff_stats"]:
            name = config.TARIFFS.get(t["tariff_key"], {}).get("name", t["tariff_key"])
            tariff_lines += f"  {name}: <b>{t['cnt']}</b>\n"
        if not tariff_lines:
            tariff_lines = "  нет данных\n"
        text = (
            f"📊 <b>Аналитика</b>\n"
            f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"👥 <b>Пользователи</b>\n"
            f"  Новых за 7 дней: <b>{s['new_users_7d']}</b>\n"
            f"  Пришли по реферальной: <b>{s['referral_users']}</b>\n\n"
            f"💰 <b>Выручка</b>\n"
            f"  За 7 дней: <b>{s['revenue_7d']} ₽</b>\n"
            f"  За 30 дней: <b>{s['revenue_30d']} ₽</b>\n"
            f"  Средний чек: <b>{s['avg_payment']} ₽</b>\n\n"
            f"🎁 <b>Пробный период</b>\n"
            f"  Активировано: <b>{s['trial_total']}</b>\n"
            f"  Конвертировано: <b>{s['trial_converted']}</b> ({conv_pct}%)\n\n"
            f"📉 <b>Отток за 30 дней</b>: <b>{s['churned_30d']}</b>\n\n"
            f"🏆 <b>Популярные тарифы</b>\n{tariff_lines}"
        )
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Обновить", callback_data="admin_analytics")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")],
            ]),
            parse_mode="HTML"
        )

    # ── Экспорт CSV ──
    elif data == "admin_export":
        if not is_admin(user.id):
            return
        await query.edit_message_text("⏳ Генерирую файлы...", parse_mode="HTML")
        import io
        try:
            users_csv = db.export_users_csv()
            payments_csv = db.export_payments_csv()
            date_str = datetime.now().strftime("%Y-%m-%d")
            await context.bot.send_document(
                chat_id=user.id,
                document=io.BytesIO(users_csv.encode("utf-8-sig")),
                filename=f"users_{date_str}.csv",
                caption="👥 Пользователи и подписки"
            )
            await context.bot.send_document(
                chat_id=user.id,
                document=io.BytesIO(payments_csv.encode("utf-8-sig")),
                filename=f"payments_{date_str}.csv",
                caption="💰 Платежи"
            )
            await query.edit_message_text(
                "✅ Файлы отправлены выше 👆",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]
                ]),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка экспорта CSV: {e}")
            await query.edit_message_text(f"❌ Ошибка: {e}")

    # ── Список пользователей ──
    elif data.startswith("admin_users_"):
        if not is_admin(user.id):
            return
        offset = int(data.split("_")[-1])
        users = db.get_all_users(limit=5, offset=offset)

        if not users:
            await query.edit_message_text(
                "👥 Пользователей нет.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]])
            )
            return

        text = f"👥 <b>Пользователи</b> (с {offset + 1}):\n\n"
        for u in users:
            sub_mark = "✅" if u.get("sub_status") == "active" else "—"
            text += (
                f"{sub_mark} <code>{u['tg_id']}</code> — {u['full_name'] or '—'}"
                f" (@{u['username'] or '—'})\n"
            )

        nav = []
        if offset > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"admin_users_{offset - 5}"))
        if len(users) == 5:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"admin_users_{offset + 5}"))

        keyboard = []
        if nav:
            keyboard.append(nav)
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    # ── Список платежей ──
    elif data.startswith("admin_payments_"):
        if not is_admin(user.id):
            return
        offset = int(data.split("_")[-1])
        payments = db.get_all_payments(limit=5, offset=offset)

        if not payments:
            await query.edit_message_text(
                "💰 Платежей нет.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]])
            )
            return

        text = f"💰 <b>Платежи</b> (с {offset + 1}):\n\n"
        for p in payments:
            emoji = status_emoji(p["status"])
            tariff = config.TARIFFS.get(p["tariff_key"], {})
            text += (
                f"{emoji} {str(p['created_at'])[:10]} — {p['full_name'] or p['tg_id']}\n"
                f"   {tariff.get('name', p['tariff_key'])} — <b>{p['amount']} ₽</b>\n\n"
            )

        nav = []
        if offset > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"admin_payments_{offset - 5}"))
        if len(payments) == 5:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"admin_payments_{offset + 5}"))

        keyboard = []
        if nav:
            keyboard.append(nav)
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    # ── Список подписок ──
    elif data.startswith("admin_subs_"):
        if not is_admin(user.id):
            return
        offset = int(data.split("_")[-1])
        subs = db.get_all_subscriptions(limit=5, offset=offset)

        if not subs:
            await query.edit_message_text(
                "📦 Активных подписок нет.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]])
            )
            return

        text = f"📦 <b>Активные подписки</b> (с {offset + 1}):\n\n"
        for s in subs:
            tariff = config.TARIFFS.get(s["tariff_key"], {})
            expires = parse_dt(s["expires_at"])
            days_left = (expires - datetime.now()).days
            warning = "⚠️ " if days_left <= 3 else ""
            text += (
                f"{warning}<code>{s['tg_id']}</code> — {s['full_name'] or '—'}\n"
                f"   {tariff.get('name', s['tariff_key'])} — до {expires.strftime('%d.%m.%Y')} ({days_left} дн.)\n\n"
            )

        nav = []
        if offset > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"admin_subs_{offset - 5}"))
        if len(subs) == 5:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"admin_subs_{offset + 5}"))

        keyboard = []
        if nav:
            keyboard.append(nav)
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    # ── Показать тарифы ──
    elif data == "show_tariffs":
        sub = db.get_active_subscription(user.id)
        if sub:
            tariff = config.TARIFFS.get(sub["tariff_key"], {})
            expires = parse_dt(sub["expires_at"])
            days_left = (expires - datetime.now()).days
            header = (
                f"🔄 <b>Продление подписки</b>\n\n"
                f"📦 Текущий тариф: {tariff.get('name', sub['tariff_key'])}\n"
                f"📅 Активна до: {expires.strftime('%d.%m.%Y')} (ещё {days_left} дн.)\n\n"
                f"Выбери тариф — новые дни добавятся к текущей дате окончания.\n\n"
                f"💼 <b>Выбери тариф для продления:</b>"
            )
        else:
            header = "💼 <b>Выбери тариф:</b>"

        await query.edit_message_text(
            header,
            reply_markup=tariff_keyboard(),
            parse_mode="HTML"
        )

    # ── Выбор тарифа ──
    elif data.startswith("buy_"):
        tariff_key = data.replace("buy_", "")
        tariff = config.TARIFFS.get(tariff_key)
        if not tariff:
            await query.edit_message_text("❌ Тариф не найден.")
            return

        traffic_text = f"{tariff['traffic_gb']} ГБ" if tariff['traffic_gb'] > 0 else "Безлимит"
        text = (
            f"📦 <b>{tariff['name']}</b>\n"
            f"💰 Сумма: <b>{tariff['price']} ₽</b>\n"
            f"📡 Трафик: {traffic_text}\n\n"
            f"💳 <b>Оплата через СБП:</b>\n"
            f"📱 Номер: <code>{config.SBP_PHONE}</code>\n"
            f"👤 Получатель: {config.SBP_NAME}\n\n"
            f"После оплаты нажми кнопку ниже 👇"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Я оплатил", callback_data=f"paid_{tariff_key}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="show_tariffs")],
        ])
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")

    # ── Клиент нажал "Оплатил" ──
    elif data.startswith("paid_"):
        tariff_key = data.replace("paid_", "")
        tariff = config.TARIFFS.get(tariff_key)

        # Rate limit: не более 3 заявок за 10 минут
        if not db.check_rate_limit(user.id, "paid_click", max_count=3, window_seconds=600):
            await query.answer(
                "⏳ Слишком много заявок. Подожди несколько минут.",
                show_alert=True
            )
            return

        if db.has_pending_payment(user.id):
            await query.edit_message_text(
                "⏳ <b>У тебя уже есть заявка на рассмотрении.</b>\n\n"
                "Дождись подтверждения от администратора.\n"
                "Если прошло много времени — напиши: @" + config.ADMIN_USERNAME,
                parse_mode="HTML"
            )
            return

        payment_id = db.create_payment(user.id, tariff_key, tariff["price"])

        existing_sub = db.get_active_subscription(user.id)
        action_label = "🔄 Продление" if existing_sub else "🆕 Новая подписка"

        admin_text = (
            f"💰 <b>Новая оплата!</b> {action_label}\n\n"
            f"👤 Клиент: {user.full_name} (@{user.username or 'нет'})\n"
            f"🆔 ID: <code>{user.id}</code>\n"
            f"📦 Тариф: {tariff['name']}\n"
            f"💵 Сумма: {tariff['price']} ₽\n"
            f"🕐 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        admin_keyboard_pay = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_{payment_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{payment_id}"),
            ]
        ])
        await notify_admin(context, admin_text, admin_keyboard_pay)
        await query.edit_message_text(
            "⏳ <b>Ожидаем подтверждения оплаты.</b>\n\n"
            "Обычно это занимает несколько минут.\n"
            "После проверки ты получишь конфиг для подключения 🔐",
            parse_mode="HTML"
        )

    # ── Админ подтверждает оплату ──
    elif data.startswith("confirm_"):
        payment_id = int(data.replace("confirm_", ""))
        payment = db.get_payment(payment_id)

        if not payment or payment["status"] != "waiting":
            await query.edit_message_text("⚠️ Платёж уже обработан.")
            return

        tariff = config.TARIFFS[payment["tariff_key"]]
        tg_id = payment["tg_id"]
        db.update_payment_status(payment_id, "confirmed")

        try:
            existing_sub = db.get_active_subscription(tg_id)

            if existing_sub:
                # ── ПРОДЛЕНИЕ ──
                updated_sub = db.extend_subscription(tg_id, tariff["days"], tariff_key=payment["tariff_key"])
                new_expires = parse_dt(updated_sub["expires_at"])
                new_expire_ms = int(new_expires.timestamp() * 1000)

                ok = xui.update_client_expiry(existing_sub["xui_client_id"], new_expire_ms)
                if not ok:
                    logger.warning(f"Не удалось обновить expiry в 3x-ui для {existing_sub['xui_email']}")

                client_text = format_sub_message(
                    sub_link=existing_sub.get("sub_link", ""),
                    config_link=existing_sub["config_link"],
                    tariff_name=tariff["name"],
                    expire_date=new_expires.strftime("%d.%m.%Y"),
                    is_new=False,
                )
            else:
                # ── НОВАЯ ПОДПИСКА ──
                result = xui.add_client(
                    name=f"user_{tg_id}",
                    days=tariff["days"],
                    traffic_gb=tariff["traffic_gb"]
                )
                expires_at = (datetime.now() + timedelta(days=tariff["days"])).strftime("%Y-%m-%d %H:%M:%S")
                db.create_subscription(
                    tg_id=tg_id,
                    tariff_key=payment["tariff_key"],
                    xui_client_id=result["client_id"],
                    xui_email=result["email"],
                    config_link=result["link"],
                    expires_at=expires_at,
                    sub_link=result.get("sub_link", ""),
                    xui_sub_id=result.get("sub_id", ""),
                )
                # Применяем накопленные реферальные дни если есть
                pending = db.apply_pending_referral_rewards(tg_id)
                if pending:
                    updated_sub = db.get_active_subscription(tg_id)
                    new_exp = parse_dt(updated_sub["expires_at"])
                    xui.update_client_expiry(result["client_id"], int(new_exp.timestamp() * 1000))
                    expires_at = new_exp.strftime("%Y-%m-%d %H:%M:%S")
                expire_date = parse_dt(expires_at).strftime("%d.%m.%Y")
                client_text = format_sub_message(
                    sub_link=result.get("sub_link", ""),
                    config_link=result["link"],
                    tariff_name=tariff["name"],
                    expire_date=expire_date,
                    is_new=True,
                )

            client_text, link_text = client_text
            await context.bot.send_message(tg_id, client_text, parse_mode="HTML")
            await context.bot.send_message(tg_id, link_text, parse_mode="HTML")

            # ── Реферальный бонус ──
            referrer_id = db.get_referrer(tg_id)
            if referrer_id and not existing_sub:
                # Начисляем бонус только за первую покупку
                bonus_days = config.REFERRAL_BONUS_DAYS
                db.create_referral_reward(referrer_id, tg_id, bonus_days)
                referrer_sub = db.get_active_subscription(referrer_id)
                if referrer_sub:
                    # У реферера есть подписка — применяем сразу
                    applied = db.apply_pending_referral_rewards(referrer_id)
                    if applied:
                        try:
                            updated = db.get_active_subscription(referrer_id)
                            new_exp = parse_dt(updated["expires_at"])
                            new_exp_ms = int(new_exp.timestamp() * 1000)
                            xui.update_client_expiry(referrer_sub["xui_client_id"], new_exp_ms)
                            await context.bot.send_message(
                                referrer_id,
                                f"🎉 <b>Реферальный бонус!</b>\n\n"
                                f"Твой друг купил подписку.\n"
                                f"+{applied} дней добавлено к твоей подписке 🚀\n"
                                f"Подписка активна до: {new_exp.strftime('%d.%m.%Y')}",
                                parse_mode="HTML"
                            )
                        except Exception as e:
                            logger.error(f"Ошибка начисления реферального бонуса: {e}")
                else:
                    # У реферера нет подписки — дни копятся
                    try:
                        await context.bot.send_message(
                            referrer_id,
                            f"🎉 <b>Реферальный бонус!</b>\n\n"
                            f"Твой друг купил подписку.\n"
                            f"+{bonus_days} дней сохранены и будут применены\n"
                            f"автоматически когда ты купишь подписку 🎁",
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.error(f"Ошибка уведомления реферера {referrer_id}: {e}")

            await query.edit_message_text(
                query.message.text + "\n\n✅ <b>Подтверждено. Уведомление отправлено.</b>",
                parse_mode="HTML"
            )

        except Exception as e:
            db.update_payment_status(payment_id, "waiting")
            logger.error(f"Ошибка обработки платежа {payment_id}: {e}")
            await query.edit_message_text(f"❌ Ошибка: {e}\n\nПлатёж возвращён в очередь.")

    # ── Админ отклоняет оплату ──
    elif data.startswith("reject_"):
        payment_id = int(data.replace("reject_", ""))
        payment = db.get_payment(payment_id)

        if not payment or payment["status"] != "waiting":
            await query.edit_message_text("⚠️ Платёж уже обработан.")
            return

        db.update_payment_status(payment_id, "rejected")
        await context.bot.send_message(
            payment["tg_id"],
            "❌ <b>Оплата не подтверждена.</b>\n\n"
            "Если ты уверен что оплатил — напиши нам: @" + config.ADMIN_USERNAME,
            parse_mode="HTML"
        )
        await query.edit_message_text(
            query.message.text + "\n\n❌ <b>Отклонено.</b>",
            parse_mode="HTML"
        )

    # ── Мой статус ──
    elif data == "my_status":
        sub = db.get_active_subscription(user.id)
        if not sub:
            await query.edit_message_text(
                "📭 У тебя нет активной подписки.\n\n"
                "Купи VPN и пользуйся без ограничений!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 Купить", callback_data="show_tariffs")],
                    [InlineKeyboardButton("⬅️ Назад", callback_data="back_main")],
                ])
            )
        else:
            tariff = config.TARIFFS.get(sub["tariff_key"], {})
            expires = parse_dt(sub["expires_at"])
            days_left = (expires - datetime.now()).days
            buttons = []
            buttons.append([InlineKeyboardButton("🔄 Продлить", callback_data="show_tariffs")])
            buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_main")])
            await query.edit_message_text(
                f"📊 <b>Твоя подписка:</b>\n\n"
                f"📦 Тариф: {tariff.get('name', sub['tariff_key'])}\n"
                f"📅 До: {expires.strftime('%d.%m.%Y')}\n"
                f"⏳ Осталось: {days_left} дн.",
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode="HTML"
            )


    # ── Отправить ссылку подписки отдельным сообщением ──
    elif data == "get_sub_link":
        sub = db.get_active_subscription(user.id)
        if not sub:
            await query.answer("Подписка не найдена", show_alert=True)
            return
        if sub.get("sub_link"):
            sub_link_display = sub["sub_link"].replace("/s/", "/sub/")
            await context.bot.send_message(
                user.id,
                f"📲 Инструкция для подключения: <a href=\"{sub_link_display}\">{sub_link_display}</a>",
                parse_mode="HTML"
            )
        else:
            await context.bot.send_message(
                user.id,
                f"<code>{sub['config_link']}</code>",
                parse_mode="HTML"
            )
        await query.answer("Ссылка отправлена ⬆️")

    # ── Пробный период ──
    elif data == "trial":
        # Rate limit: не более 2 попыток за час
        if not db.check_rate_limit(user.id, "trial_click", max_count=2, window_seconds=3600):
            await query.answer("⏳ Слишком много попыток. Попробуй позже.", show_alert=True)
            return
        # Проверяем что триал не использован и нет активной подписки
        if db.has_used_trial(user.id):
            await query.edit_message_text(
                "❌ <b>Пробный период уже использован.</b>\n\n"
                "Каждый пользователь может воспользоваться им только один раз.\n"
                "Выбери тариф для продолжения:",
                reply_markup=tariff_keyboard(),
                parse_mode="HTML"
            )
            return
        if db.get_active_subscription(user.id):
            await query.edit_message_text(
                "ℹ️ У тебя уже есть активная подписка.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📊 Мой статус", callback_data="my_status")],
                    [InlineKeyboardButton("⬅️ Назад", callback_data="back_main")],
                ]),
                parse_mode="HTML"
            )
            return

        await query.edit_message_text("⏳ Создаём пробный доступ...", parse_mode="HTML")
        try:
            result = xui.add_client(
                name=f"trial_{user.id}",
                days=config.TRIAL_DAYS,
                traffic_gb=0
            )
            expires_at = (datetime.now() + timedelta(days=config.TRIAL_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
            db.create_subscription(
                tg_id=user.id,
                tariff_key="trial",
                xui_client_id=result["client_id"],
                xui_email=result["email"],
                config_link=result["link"],
                expires_at=expires_at,
                sub_link=result.get("sub_link", ""),
                xui_sub_id=result.get("sub_id", ""),
            )
            db.mark_trial_used(user.id)
            expire_date = (datetime.now() + timedelta(days=config.TRIAL_DAYS)).strftime("%d.%m.%Y")
            trial_main, trial_link = format_sub_message(
                sub_link=result.get("sub_link", ""),
                config_link=result["link"],
                tariff_name=f"Пробный период ({config.TRIAL_DAYS} дней)",
                expire_date=expire_date,
                is_new=True,
            )
            trial_main += "\n💡 После окончания триала можно купить полную подписку."

            await query.edit_message_text(
                trial_main,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 Купить подписку", callback_data="show_tariffs")],
                ]),
                parse_mode="HTML"
            )
            await context.bot.send_message(user.id, trial_link, parse_mode="HTML")

            # Уведомляем админа
            await notify_admin(
                context,
                f"🎁 <b>Новый триал!</b>\n\n"
                f"👤 {user.full_name} (@{user.username or 'нет'})\n"
                f"🆔 <code>{user.id}</code>\n"
                f"📅 До: {expire_date}"
            )
        except Exception as e:
            import traceback
            logger.error(f"Ошибка активации триала для {user.id}: {e}\n{traceback.format_exc()}")
            await query.edit_message_text(
                f"❌ Ошибка активации. Напиши администратору: @{config.ADMIN_USERNAME}",
                parse_mode="HTML"
            )

    # ── Рефералы ──
    elif data == "referrals":
        bot_info = await context.bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref_{user.id}"
        stats = db.get_referral_stats(user.id)
        text = (
            f"👥 <b>Реферальная программа</b>\n\n"
            f"Приглашай друзей и получай <b>+{config.REFERRAL_BONUS_DAYS} дней</b> за каждого оплатившего!\n\n"
            f"🔗 <b>Твоя ссылка:</b>\n"
            f"<code>{ref_link}</code>\n\n"
            f"📊 <b>Твоя статистика:</b>\n"
            f"👤 Приглашено: <b>{stats['total']}</b>\n"
            f"💰 Оплатили: <b>{stats['paid']}</b>\n"
            f"🎁 Заработано дней: <b>{stats['days_earned']}</b>\n"
        )
        if stats["days_pending"] > 0:
            text += f"⏳ Ждут подписки: <b>{stats['days_pending']} дн.</b>\n"
        text += (
            f"\n💡 <b>Как это работает:</b>\n"
            f"1. Отправь ссылку другу\n"
            f"2. Друг регистрируется и покупает подписку\n"
            f"3. Тебе автоматически начисляется +{config.REFERRAL_BONUS_DAYS} дней 🚀"
        )
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="back_main")],
            ]),
            parse_mode="HTML"
        )

    # ── Инструкция ──
    elif data == "instruction":
        sub = db.get_active_subscription(user.id)
        if sub and sub.get("sub_link"):
            sub_link_display = sub["sub_link"].replace("/s/", "/sub/")
            await query.edit_message_text(
                f"📲 Инструкция для подключения: <a href=\"{sub_link_display}\">{sub_link_display}</a>",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Назад", callback_data="back_main")],
                ]),
                parse_mode="HTML"
            )
        else:
            await query.edit_message_text(
                "📭 У тебя нет активной подписки.\n\nКупи VPN и получи ссылку для подключения!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 Купить", callback_data="show_tariffs")],
                    [InlineKeyboardButton("⬅️ Назад", callback_data="back_main")],
                ])
            )

    # ── Назад в главное меню ──
    elif data == "back_main":
        await query.edit_message_text(
            main_text(user.first_name),
            reply_markup=main_keyboard(user.id),
            parse_mode="HTML"
        )


# ─────────────────────────── SCHEDULER ────────────────────────────

async def write_heartbeat(context: ContextTypes.DEFAULT_TYPE):
    """Записывает timestamp в файл — признак что бот живой."""
    try:
        with open("/opt/vpn_bot/heartbeat", "w") as f:
            f.write(str(datetime.now().timestamp()))
    except Exception as e:
        logger.error(f"Ошибка записи heartbeat: {e}")


async def check_expiring(context: ContextTypes.DEFAULT_TYPE):
    # ── 1. Удаляем истёкшие подписки из 3x-ui и уведомляем пользователей ──
    expired = db.expire_old_subscriptions()
    for sub in expired:
        try:
            xui.delete_client(sub["xui_email"])
            logger.info(f"Удалён истёкший клиент 3x-ui: {sub['xui_email']} (tg_id={sub['tg_id']})")
        except Exception as e:
            logger.error(f"Ошибка удаления клиента {sub['xui_email']} из 3x-ui: {e}")

        # Уведомляем пользователя об отключении
        try:
            await context.bot.send_message(
                sub["tg_id"],
                "🔴 <b>Подписка истекла — доступ к VPN отключён.</b>\n\n"
                "Чтобы продолжить пользоваться — продли подписку 👇",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 Купить подписку", callback_data="show_tariffs")]
                ]),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления об отключении пользователю {sub['tg_id']}: {e}")

    # ── 2. Напоминание за REMIND_DAYS_BEFORE дней ──
    expiring = db.get_expiring_subscriptions(config.REMIND_DAYS_BEFORE)
    for sub in expiring:
        expires = parse_dt(sub["expires_at"])
        days_left = (expires - datetime.now()).days + 1
        try:
            await context.bot.send_message(
                sub["tg_id"],
                f"⏰ <b>Подписка заканчивается через {days_left} дн.!</b>\n\n"
                f"Не забудь продлить, чтобы не потерять доступ 👇",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Продлить", callback_data="show_tariffs")]
                ]),
                parse_mode="HTML"
            )
            db.mark_reminded(sub["id"])
        except Exception as e:
            logger.error(f"Ошибка напоминания пользователю {sub['tg_id']}: {e}")

    # ── 3. Финальное напоминание за 1 день ──
    if config.REMIND_LAST_DAY:
        last_day_subs = db.get_subscriptions_expiring_in_days(1)
        for sub in last_day_subs:
            try:
                await context.bot.send_message(
                    sub["tg_id"],
                    "🚨 <b>Последний день подписки!</b>\n\n"
                    "Завтра доступ к VPN будет отключён.\n"
                    "Продли прямо сейчас 👇",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Продлить сейчас", callback_data="show_tariffs")]
                    ]),
                    parse_mode="HTML"
                )
                # Помечаем что напоминание уже отправлено — больше не спамим
                db.mark_last_day_reminded(sub["id"])
                logger.info(f"Финальное напоминание отправлено: tg_id={sub['tg_id']}")
            except Exception as e:
                logger.error(f"Ошибка финального напоминания пользователю {sub['tg_id']}: {e}")

    # ── 4. Автоотключение за отклонённые платежи ──
    if config.AUTO_DISCONNECT_AFTER_REJECT_DAYS > 0:
        stale = db.get_stale_rejected_payments(config.AUTO_DISCONNECT_AFTER_REJECT_DAYS)
        for row in stale:
            try:
                xui.delete_client(row["xui_email"])
                db.expire_subscription_by_id(row["sub_id"])
                # Помечаем что уведомление отправлено — не будем спамить повторно
                db.mark_disconnect_notified(row["id"])
                logger.info(
                    f"Автоотключение за неоплату: tg_id={row['tg_id']}, email={row['xui_email']}"
                )
                await context.bot.send_message(
                    row["tg_id"],
                    "🔴 <b>Доступ к VPN отключён.</b>\n\n"
                    f"Платёж был отклонён {config.AUTO_DISCONNECT_AFTER_REJECT_DAYS} дня назад "
                    f"и так и не был повторён.\n\n"
                    "Чтобы восстановить доступ — купи подписку 👇",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🛒 Купить подписку", callback_data="show_tariffs")]
                    ]),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Ошибка автоотключения tg_id={row['tg_id']}: {e}")


# ─────────────────────────── MAIN ────────────────────────────

async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("start", "Запустить бота"),
        BotCommand("admin", "Админ-панель"),
        BotCommand("find", "Найти пользователя"),
    ])


if __name__ == "__main__":
    db.init_db()

    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("find", find_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))

    app.job_queue.run_daily(check_expiring, time=datetime.strptime("10:00", "%H:%M").time())
    app.job_queue.run_repeating(write_heartbeat, interval=60, first=10)

    logger.info("Бот запущен!")
    app.run_polling()