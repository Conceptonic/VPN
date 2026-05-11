import os
import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/vpn_bot")

# Пул соединений: мин 1, макс 10 (бот однопоточный, но с запасом)
_pool: ThreadedConnectionPool | None = None


def _init_pool() -> None:
    global _pool
    _pool = ThreadedConnectionPool(1, 10, DATABASE_URL)


@contextmanager
def _conn():
    """Берёт соединение из пула, делает commit или rollback, возвращает в пул."""
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


def _fetchone(conn, query: str, params=()) -> dict | None:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, params)
        row = cur.fetchone()
        return dict(row) if row else None


def _fetchall(conn, query: str, params=()) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, params)
        return [dict(r) for r in cur.fetchall()]


def _execute(conn, query: str, params=()) -> None:
    with conn.cursor() as cur:
        cur.execute(query, params)


def _execute_returning(conn, query: str, params=()) -> dict | None:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, params)
        row = cur.fetchone()
        return dict(row) if row else None


# ─────────────────────────── INIT ────────────────────────────

def init_db() -> None:
    _init_pool()
    with _conn() as conn:
        _execute(conn, """
            CREATE TABLE IF NOT EXISTS users (
                id          BIGSERIAL PRIMARY KEY,
                tg_id       BIGINT UNIQUE NOT NULL,
                username    TEXT,
                full_name   TEXT,
                referred_by BIGINT DEFAULT NULL,
                trial_used  BOOLEAN DEFAULT FALSE,
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """)
        _execute(conn, """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id            BIGSERIAL PRIMARY KEY,
                tg_id         BIGINT NOT NULL,
                tariff_key    TEXT NOT NULL,
                xui_client_id TEXT,
                xui_email     TEXT,
                config_link   TEXT,
                sub_link      TEXT,
                status        TEXT DEFAULT 'pending',
                started_at    TIMESTAMP,
                expires_at    TIMESTAMP,
                reminded      SMALLINT DEFAULT 0,
                created_at    TIMESTAMP DEFAULT NOW()
            )
        """)
        _execute(conn, """
            CREATE TABLE IF NOT EXISTS payments (
                id         BIGSERIAL PRIMARY KEY,
                tg_id      BIGINT NOT NULL,
                tariff_key TEXT NOT NULL,
                amount     INTEGER NOT NULL,
                status     TEXT DEFAULT 'waiting',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        _execute(conn, """
            CREATE TABLE IF NOT EXISTS referral_rewards (
                id          BIGSERIAL PRIMARY KEY,
                referrer_id BIGINT NOT NULL,
                referred_id BIGINT NOT NULL,
                days        INTEGER NOT NULL,
                applied     BOOLEAN DEFAULT FALSE,
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """)
        _execute(conn, "CREATE INDEX IF NOT EXISTS idx_ref_rewards_referrer ON referral_rewards (referrer_id, applied)")
        _execute(conn, """
            ALTER TABLE payments ADD COLUMN IF NOT EXISTS disconnect_notified BOOLEAN DEFAULT FALSE
        """)
        # Добавляем колонки если их нет (для уже существующих БД)
        _execute(conn, """
            ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by BIGINT DEFAULT NULL
        """)
        _execute(conn, """
            ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_used BOOLEAN DEFAULT FALSE
        """)
        _execute(conn, """
            ALTER TABLE payments ADD COLUMN IF NOT EXISTS disconnect_notified BOOLEAN DEFAULT FALSE
        """)
        _execute(conn, """
            ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS sub_link TEXT
        """)
        # Отдельное поле sub_id для быстрого поиска в sub_server
        _execute(conn, """
            ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS xui_sub_id TEXT
        """)
        # Индексы для ускорения частых запросов
        _execute(conn, "CREATE INDEX IF NOT EXISTS idx_subs_tg_status ON subscriptions (tg_id, status)")
        _execute(conn, "CREATE INDEX IF NOT EXISTS idx_pays_tg_status ON payments (tg_id, status)")
        _execute(conn, "CREATE INDEX IF NOT EXISTS idx_subs_expires   ON subscriptions (expires_at) WHERE status = 'active'")
        _execute(conn, "CREATE INDEX IF NOT EXISTS idx_subs_sub_id    ON subscriptions (xui_sub_id) WHERE xui_sub_id IS NOT NULL")


# ─────────────────────────── USERS ────────────────────────────

def add_user(tg_id: int, username: str | None, full_name: str | None, referred_by: int | None = None) -> None:
    with _conn() as conn:
        _execute(conn, """
            INSERT INTO users (tg_id, username, full_name, referred_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (tg_id) DO NOTHING
        """, (tg_id, username, full_name, referred_by))


def get_referral_stats(tg_id: int) -> dict:
    """Возвращает статистику рефералов пользователя."""
    with _conn() as conn:
        total = _fetchone(conn, """
            SELECT COUNT(*) AS n FROM users WHERE referred_by = %s
        """, (tg_id,))["n"]
        paid = _fetchone(conn, """
            SELECT COUNT(*) AS n FROM users u
            WHERE u.referred_by = %s
              AND EXISTS (
                SELECT 1 FROM payments p
                WHERE p.tg_id = u.tg_id AND p.status = 'confirmed'
              )
        """, (tg_id,))["n"]
        days_earned = _fetchone(conn, """
            SELECT COALESCE(SUM(days), 0) AS n FROM referral_rewards
            WHERE referrer_id = %s
        """, (tg_id,))["n"]
        days_pending = _fetchone(conn, """
            SELECT COALESCE(SUM(days), 0) AS n FROM referral_rewards
            WHERE referrer_id = %s AND applied = FALSE
        """, (tg_id,))["n"]
        return {
            "total":        total,
            "paid":         paid,
            "days_earned":  days_earned,
            "days_pending": days_pending,
        }


def get_subscriptions_expiring_in_days(days: int) -> list[dict]:
    """Подписки истекающие ровно через days дней (для последнего напоминания).
    reminded >= 1 — первое напоминание уже отправлено, финальное ещё нет (reminded < 2).
    """
    with _conn() as conn:
        return _fetchall(conn, """
            SELECT * FROM subscriptions
            WHERE status    = 'active'
              AND reminded  >= 1
              AND reminded  < 2
              AND expires_at::date = (CURRENT_DATE + (%s * INTERVAL '1 day'))::date
        """, (days,))


def expire_subscription_by_id(sub_id: int) -> None:
    """Помечает конкретную подписку как expired."""
    with _conn() as conn:
        _execute(conn, """
            UPDATE subscriptions SET status = 'expired' WHERE id = %s
        """, (sub_id,))


def get_stale_rejected_payments(days: int) -> list[dict]:
    """
    Возвращает платежи со статусом rejected, которые были отклонены
    более чем days дней назад, у пользователя есть активная подписка,
    и уведомление ещё не отправлялось.

    Защита от ложных срабатываний: берём только тех, у кого отклонённый
    платёж является ПОСЛЕДНИМ подтверждённым или отклонённым платежом
    (т.е. после него не было успешной оплаты).
    """
    with _conn() as conn:
        return _fetchall(conn, """
            SELECT p.*, s.xui_email, s.xui_client_id, s.id AS sub_id
            FROM payments p
            JOIN subscriptions s ON s.tg_id = p.tg_id AND s.status = 'active'
            WHERE p.status = 'rejected'
              AND p.disconnect_notified = FALSE
              AND p.created_at < NOW() - (%s * INTERVAL '1 day')
              AND NOT EXISTS (
                  SELECT 1 FROM payments p2
                  WHERE p2.tg_id = p.tg_id
                    AND p2.status = 'confirmed'
                    AND p2.created_at > p.created_at
              )
        """, (days,))


def mark_disconnect_notified(payment_id: int) -> None:
    """Помечает платёж как уже уведомлённый об отключении."""
    with _conn() as conn:
        _execute(conn, """
            UPDATE payments SET disconnect_notified = TRUE WHERE id = %s
        """, (payment_id,))


def get_referrer(tg_id: int) -> int | None:
    """Возвращает tg_id реферера пользователя или None."""
    with _conn() as conn:
        row = _fetchone(conn, "SELECT referred_by FROM users WHERE tg_id = %s", (tg_id,))
        return row["referred_by"] if row else None


def has_used_trial(tg_id: int) -> bool:
    """Проверяет использовал ли пользователь пробный период."""
    with _conn() as conn:
        row = _fetchone(conn, "SELECT trial_used FROM users WHERE tg_id = %s", (tg_id,))
        return bool(row["trial_used"]) if row else False


def mark_trial_used(tg_id: int) -> None:
    """Помечает что пользователь использовал пробный период."""
    with _conn() as conn:
        _execute(conn, "UPDATE users SET trial_used = TRUE WHERE tg_id = %s", (tg_id,))


def create_referral_reward(referrer_id: int, referred_id: int, days: int) -> None:
    """Создаёт запись о реферальном бонусе."""
    with _conn() as conn:
        _execute(conn, """
            INSERT INTO referral_rewards (referrer_id, referred_id, days)
            VALUES (%s, %s, %s)
        """, (referrer_id, referred_id, days))


def apply_pending_referral_rewards(tg_id: int) -> int:
    """
    Применяет накопленные реферальные дни к активной подписке пользователя.
    Возвращает количество применённых дней (0 если нечего применять).
    """
    with _conn() as conn:
        rows = _fetchall(conn, """
            SELECT id, days FROM referral_rewards
            WHERE referrer_id = %s AND applied = FALSE
        """, (tg_id,))
        if not rows:
            return 0
        total_days = sum(r["days"] for r in rows)
        ids = [r["id"] for r in rows]
        _execute(conn, """
            UPDATE referral_rewards SET applied = TRUE
            WHERE id = ANY(%s)
        """, (ids,))
        # Продлеваем подписку
        _execute(conn, """
            UPDATE subscriptions
            SET expires_at = expires_at + (%s * INTERVAL '1 day')
            WHERE id = (
                SELECT id FROM subscriptions
                WHERE tg_id = %s AND status = 'active'
                ORDER BY created_at DESC LIMIT 1
            )
        """, (total_days, tg_id))
        return total_days


# ─────────────────────────── PAYMENTS ────────────────────────────

def create_payment(tg_id: int, tariff_key: str, amount: int) -> int:
    with _conn() as conn:
        row = _execute_returning(conn, """
            INSERT INTO payments (tg_id, tariff_key, amount)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (tg_id, tariff_key, amount))
        return row["id"]


def get_payment(payment_id: int) -> dict | None:
    with _conn() as conn:
        return _fetchone(conn, "SELECT * FROM payments WHERE id = %s", (payment_id,))


def update_payment_status(payment_id: int, status: str) -> None:
    with _conn() as conn:
        _execute(conn, "UPDATE payments SET status = %s WHERE id = %s", (status, payment_id))


def has_pending_payment(tg_id: int) -> bool:
    with _conn() as conn:
        row = _fetchone(conn, """
            SELECT id FROM payments
            WHERE tg_id = %s AND status = 'waiting'
            ORDER BY created_at DESC LIMIT 1
        """, (tg_id,))
        return row is not None


# ─────────────────────────── SUBSCRIPTIONS ────────────────────────────

def create_subscription(
    tg_id: int,
    tariff_key: str,
    xui_client_id: str,
    xui_email: str,
    config_link: str,
    expires_at: str,
    sub_link: str = "",
    xui_sub_id: str = "",
) -> None:
    with _conn() as conn:
        _execute(conn, """
            INSERT INTO subscriptions
                (tg_id, tariff_key, xui_client_id, xui_email, config_link, sub_link,
                 xui_sub_id, status, started_at, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'active', NOW(), %s)
        """, (tg_id, tariff_key, xui_client_id, xui_email, config_link, sub_link,
              xui_sub_id or None, expires_at))


def extend_subscription(tg_id: int, days: int, tariff_key: str = None) -> dict | None:
    """
    Прибавляет days дней к expires_at активной подписки.
    Если передан tariff_key — обновляет тариф (например, с trial на 1m).
    Сбрасывает reminded, чтобы напоминание пришло повторно.
    Возвращает обновлённую строку или None если нет активной подписки.
    """
    with _conn() as conn:
        if tariff_key:
            return _execute_returning(conn, """
                UPDATE subscriptions
                SET expires_at = expires_at + (%s * INTERVAL '1 day'),
                    reminded   = 0,
                    tariff_key = %s
                WHERE id = (
                    SELECT id FROM subscriptions
                    WHERE tg_id = %s AND status = 'active'
                    ORDER BY created_at DESC LIMIT 1
                )
                RETURNING *
            """, (days, tariff_key, tg_id))
        else:
            return _execute_returning(conn, """
                UPDATE subscriptions
                SET expires_at = expires_at + (%s * INTERVAL '1 day'),
                    reminded   = 0
                WHERE id = (
                    SELECT id FROM subscriptions
                    WHERE tg_id = %s AND status = 'active'
                    ORDER BY created_at DESC LIMIT 1
                )
                RETURNING *
            """, (days, tg_id))


def get_active_subscription(tg_id: int) -> dict | None:
    with _conn() as conn:
        return _fetchone(conn, """
            SELECT * FROM subscriptions
            WHERE tg_id = %s AND status = 'active'
            ORDER BY created_at DESC LIMIT 1
        """, (tg_id,))


def get_expiring_subscriptions(days_before: int) -> list[dict]:
    with _conn() as conn:
        return _fetchall(conn, """
            SELECT * FROM subscriptions
            WHERE status   = 'active'
              AND reminded = 0
              AND expires_at <= NOW() + (%s * INTERVAL '1 day')
              AND expires_at >  NOW()
        """, (days_before,))


def mark_reminded(sub_id: int) -> None:
    with _conn() as conn:
        _execute(conn, "UPDATE subscriptions SET reminded = 1 WHERE id = %s", (sub_id,))


def expire_old_subscriptions() -> list[dict]:
    """
    Атомарно помечает истёкшие подписки как expired (CTE + RETURNING).
    Возвращает только что истёкшие подписки (для удаления из 3x-ui).
    """
    with _conn() as conn:
        return _fetchall(conn, """
            WITH expired AS (
                UPDATE subscriptions
                SET status = 'expired'
                WHERE status = 'active' AND expires_at < NOW()
                RETURNING *
            )
            SELECT * FROM expired
        """)


# ─────────────────────────── ADMIN STATS ────────────────────────────

def get_stats() -> dict:
    with _conn() as conn:
        total_users = _fetchone(conn, "SELECT COUNT(*) AS n FROM users")["n"]
        active_subs = _fetchone(
            conn, "SELECT COUNT(*) AS n FROM subscriptions WHERE status = 'active'"
        )["n"]
        today = _fetchone(conn, """
            SELECT COUNT(*) AS cnt, COALESCE(SUM(amount), 0) AS total
            FROM payments
            WHERE status = 'confirmed' AND DATE(created_at) = CURRENT_DATE
        """)
        total = _fetchone(conn, """
            SELECT COUNT(*) AS cnt, COALESCE(SUM(amount), 0) AS total
            FROM payments WHERE status = 'confirmed'
        """)
        pending = _fetchone(
            conn, "SELECT COUNT(*) AS n FROM payments WHERE status = 'waiting'"
        )["n"]
        return {
            "total_users":          total_users,
            "active_subs":          active_subs,
            "payments_today_count": today["cnt"],
            "payments_today_sum":   today["total"],
            "payments_total_count": total["cnt"],
            "payments_total_sum":   total["total"],
            "pending_payments":     pending,
        }


def get_extended_stats() -> dict:
    """Расширенная статистика для админа: конверсия, отток, средний чек, тарифы."""
    with _conn() as conn:
        # Триал → платный конверсия
        trial_total = _fetchone(conn, """
            SELECT COUNT(*) AS n FROM subscriptions WHERE tariff_key = 'trial'
        """)["n"]
        trial_converted = _fetchone(conn, """
            SELECT COUNT(DISTINCT p.tg_id) AS n
            FROM payments p
            JOIN subscriptions s ON s.tg_id = p.tg_id AND s.tariff_key = 'trial'
            WHERE p.status = 'confirmed'
        """)["n"]

        # Средний чек
        avg_payment = _fetchone(conn, """
            SELECT COALESCE(ROUND(AVG(amount)), 0) AS n
            FROM payments WHERE status = 'confirmed'
        """)["n"]

        # Отток за 30 дней (истекли и не продлили)
        churned = _fetchone(conn, """
            SELECT COUNT(*) AS n FROM subscriptions s
            WHERE s.status = 'expired'
              AND s.expires_at >= NOW() - INTERVAL '30 days'
              AND NOT EXISTS (
                SELECT 1 FROM subscriptions s2
                WHERE s2.tg_id = s.tg_id
                  AND s2.status = 'active'
              )
        """)["n"]

        # Новых пользователей за 7 дней
        new_users_7d = _fetchone(conn, """
            SELECT COUNT(*) AS n FROM users
            WHERE created_at >= NOW() - INTERVAL '7 days'
        """)["n"]

        # Выручка за 7 дней
        revenue_7d = _fetchone(conn, """
            SELECT COALESCE(SUM(amount), 0) AS n FROM payments
            WHERE status = 'confirmed'
              AND created_at >= NOW() - INTERVAL '7 days'
        """)["n"]

        # Выручка за 30 дней
        revenue_30d = _fetchone(conn, """
            SELECT COALESCE(SUM(amount), 0) AS n FROM payments
            WHERE status = 'confirmed'
              AND created_at >= NOW() - INTERVAL '30 days'
        """)["n"]

        # Популярность тарифов
        tariff_stats = _fetchall(conn, """
            SELECT tariff_key, COUNT(*) AS cnt
            FROM payments
            WHERE status = 'confirmed' AND tariff_key != 'trial'
            GROUP BY tariff_key
            ORDER BY cnt DESC
        """)

        # Рефералы
        referral_users = _fetchone(conn, """
            SELECT COUNT(*) AS n FROM users WHERE referred_by IS NOT NULL
        """)["n"]

        return {
            "trial_total":      trial_total,
            "trial_converted":  trial_converted,
            "avg_payment":      int(avg_payment),
            "churned_30d":      churned,
            "new_users_7d":     new_users_7d,
            "revenue_7d":       revenue_7d,
            "revenue_30d":      revenue_30d,
            "tariff_stats":     tariff_stats,
            "referral_users":   referral_users,
        }


def export_users_csv() -> str:
    """Возвращает CSV-строку со всеми пользователями и их подписками."""
    with _conn() as conn:
        rows = _fetchall(conn, """
            SELECT
                u.tg_id, u.username, u.full_name,
                u.trial_used, u.referred_by,
                u.created_at AS registered_at,
                s.tariff_key, s.status AS sub_status,
                s.expires_at,
                COALESCE(p.total_paid, 0) AS total_paid,
                COALESCE(p.payments_count, 0) AS payments_count
            FROM users u
            LEFT JOIN subscriptions s ON s.tg_id = u.tg_id
                AND s.id = (
                    SELECT id FROM subscriptions s2
                    WHERE s2.tg_id = u.tg_id
                    ORDER BY created_at DESC LIMIT 1
                )
            LEFT JOIN (
                SELECT tg_id,
                       SUM(amount) AS total_paid,
                       COUNT(*) AS payments_count
                FROM payments WHERE status = 'confirmed'
                GROUP BY tg_id
            ) p ON p.tg_id = u.tg_id
            ORDER BY u.created_at DESC
        """)

    import io, csv
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "tg_id", "username", "full_name", "trial_used", "referred_by",
        "registered_at", "tariff", "sub_status", "expires_at",
        "total_paid_rub", "payments_count"
    ])
    for r in rows:
        writer.writerow([
            r["tg_id"], r["username"] or "", r["full_name"] or "",
            r["trial_used"], r["referred_by"] or "",
            str(r["registered_at"])[:19] if r["registered_at"] else "",
            r["tariff_key"] or "", r["sub_status"] or "",
            str(r["expires_at"])[:19] if r["expires_at"] else "",
            r["total_paid"], r["payments_count"]
        ])
    return output.getvalue()


def export_payments_csv() -> str:
    """Возвращает CSV-строку со всеми платежами."""
    with _conn() as conn:
        rows = _fetchall(conn, """
            SELECT p.id, p.tg_id, u.username, u.full_name,
                   p.tariff_key, p.amount, p.status, p.created_at
            FROM payments p
            LEFT JOIN users u ON u.tg_id = p.tg_id
            ORDER BY p.created_at DESC
        """)

    import io, csv
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "tg_id", "username", "full_name", "tariff", "amount_rub", "status", "created_at"])
    for r in rows:
        writer.writerow([
            r["id"], r["tg_id"], r["username"] or "", r["full_name"] or "",
            r["tariff_key"], r["amount"], r["status"],
            str(r["created_at"])[:19]
        ])
    return output.getvalue()


def get_all_users(limit: int = 20, offset: int = 0) -> list[dict]:
    with _conn() as conn:
        return _fetchall(conn, """
            SELECT u.*,
                   s.tariff_key, s.expires_at, s.status AS sub_status
            FROM users u
            LEFT JOIN subscriptions s
                   ON s.id = (
                       SELECT id FROM subscriptions s2
                       WHERE s2.tg_id = u.tg_id AND s2.status = 'active'
                       ORDER BY created_at DESC LIMIT 1
                   )
            ORDER BY u.created_at DESC
            LIMIT %s OFFSET %s
        """, (limit, offset))


def get_all_payments(limit: int = 20, offset: int = 0) -> list[dict]:
    with _conn() as conn:
        return _fetchall(conn, """
            SELECT p.*, u.username, u.full_name
            FROM payments p
            LEFT JOIN users u ON p.tg_id = u.tg_id
            ORDER BY p.created_at DESC
            LIMIT %s OFFSET %s
        """, (limit, offset))


def get_all_subscriptions(limit: int = 20, offset: int = 0) -> list[dict]:
    with _conn() as conn:
        return _fetchall(conn, """
            SELECT s.*, u.username, u.full_name
            FROM subscriptions s
            LEFT JOIN users u ON s.tg_id = u.tg_id
            WHERE s.status = 'active'
            ORDER BY s.expires_at ASC
            LIMIT %s OFFSET %s
        """, (limit, offset))


def find_user(tg_id: int) -> dict | None:
    with _conn() as conn:
        user = _fetchone(conn, "SELECT * FROM users WHERE tg_id = %s", (tg_id,))
        if not user:
            return None
        sub = _fetchone(conn, """
            SELECT * FROM subscriptions WHERE tg_id = %s
            ORDER BY created_at DESC LIMIT 1
        """, (tg_id,))
        payments = _fetchall(conn, """
            SELECT * FROM payments WHERE tg_id = %s
            ORDER BY created_at DESC LIMIT 5
        """, (tg_id,))
        return {"user": user, "subscription": sub, "payments": payments}

def mark_last_day_reminded(sub_id: int) -> None:
    """Помечает что финальное напоминание (последний день) уже отправлено."""
    with _conn() as conn:
        _execute(conn, "UPDATE subscriptions SET reminded = 2 WHERE id = %s", (sub_id,))


def get_subscription_by_sub_id(sub_id: str) -> dict | None:
    """Быстрый поиск подписки по xui_sub_id (с fallback на LIKE по sub_link)."""
    with _conn() as conn:
        # Сначала пробуем точный поиск по индексу
        row = _fetchone(conn, """
            SELECT s.*, u.full_name, u.username
            FROM subscriptions s
            LEFT JOIN users u ON u.tg_id = s.tg_id
            WHERE s.xui_sub_id = %s AND s.status = 'active'
            LIMIT 1
        """, (sub_id,))
        if row:
            return row
        # Fallback: ищем по sub_link (для старых записей без xui_sub_id)
        return _fetchone(conn, """
            SELECT s.*, u.full_name, u.username
            FROM subscriptions s
            LEFT JOIN users u ON u.tg_id = s.tg_id
            WHERE (
                s.sub_link LIKE %s
                OR s.sub_link LIKE %s
                OR s.sub_link LIKE %s
            )
            AND s.status = 'active'
            LIMIT 1
        """, (f"%/s/{sub_id}", f"%/sub/{sub_id}", f"%/{sub_id}"))


# ─────────────────────────── RATE LIMITING ────────────────────────────

def check_rate_limit(tg_id: int, action: str, max_count: int, window_seconds: int) -> bool:
    """
    Проверяет не превышен ли лимит действий для пользователя.
    Возвращает True если действие разрешено, False если лимит превышен.
    Хранит счётчики в таблице rate_limits.
    """
    with _conn() as conn:
        # Создаём таблицу если нет (выполняется быстро благодаря IF NOT EXISTS)
        _execute(conn, """
            CREATE TABLE IF NOT EXISTS rate_limits (
                id         BIGSERIAL PRIMARY KEY,
                tg_id      BIGINT NOT NULL,
                action     TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        _execute(conn, """
            CREATE INDEX IF NOT EXISTS idx_rate_limits ON rate_limits (tg_id, action, created_at)
        """)
        # Считаем действия в окне
        row = _fetchone(conn, """
            SELECT COUNT(*) AS n FROM rate_limits
            WHERE tg_id = %s AND action = %s
              AND created_at > NOW() - (%s * INTERVAL '1 second')
        """, (tg_id, action, window_seconds))
        if row["n"] >= max_count:
            return False
        # Записываем действие
        _execute(conn, """
            INSERT INTO rate_limits (tg_id, action) VALUES (%s, %s)
        """, (tg_id, action))
        # Чистим старые записи (раз в ~50 вызовов через вероятность, чтобы не чистить каждый раз)
        import random
        if random.random() < 0.02:
            _execute(conn, """
                DELETE FROM rate_limits
                WHERE created_at < NOW() - INTERVAL '1 hour'
            """)
        return True