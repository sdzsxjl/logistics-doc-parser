"""
客户管理模块 - SQLite存储客户信息、API Key、用量追踪
支持多客户管理，每个客户独立API Key和用量配额
"""
import os
import sqlite3
import threading
import hashlib
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field


DB_PATH = Path("data/customers.db")

# 线程本地存储，每个线程独立连接
_local = threading.local()


def get_db() -> sqlite3.Connection:
    """获取当前线程的数据库连接"""
    if not hasattr(_local, "conn") or _local.conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db():
    """初始化数据库表"""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,              -- 客户标识（登录名）
            display_name TEXT NOT NULL,              -- 显示名称
            company TEXT DEFAULT '',                 -- 公司名
            api_key TEXT DEFAULT '',                 -- DeepSeek API Key
            api_key_masked TEXT DEFAULT '',          -- 脱敏显示的Key
            model TEXT DEFAULT 'deepseek-chat',      -- 使用的模型
            monthly_quota INTEGER DEFAULT 5000,      -- 月配额（运单数）
            is_active INTEGER DEFAULT 1,             -- 是否启用
            contact_phone TEXT DEFAULT '',            -- 联系电话
            contact_email TEXT DEFAULT '',            -- 联系邮箱
            notes TEXT DEFAULT '',                    -- 备注
            created_at TEXT DEFAULT (datetime('now','localtime')),
            expires_at TEXT DEFAULT '',               -- 过期日期（空=永不过期）
            last_login TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS usage_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            timestamp TEXT DEFAULT (datetime('now','localtime')),
            pdf_filename TEXT DEFAULT '',
            order_count INTEGER DEFAULT 0,           -- 提取到的运单数
            tokens_input INTEGER DEFAULT 0,           -- 输入token数
            tokens_output INTEGER DEFAULT 0,          -- 输出token数
            parse_method TEXT DEFAULT '',             -- ai / regex / ai_fallback
            success INTEGER DEFAULT 0,               -- 是否成功
            cost_estimate REAL DEFAULT 0.0,          -- 估算费用(元)
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        );

        -- 默认管理员账号（admin / admin123）
        INSERT OR IGNORE INTO customers (name, display_name, company, notes, is_active)
        VALUES ('admin', '系统管理员', '', '默认管理员账号', 1);

        INSERT OR IGNORE INTO settings (key, value) VALUES ('db_version', '1');
        INSERT OR IGNORE INTO settings (key, value) VALUES ('global_api_key', '');
        INSERT OR IGNORE INTO settings (key, value) VALUES ('global_model', 'deepseek-chat');
    """)
    conn.commit()


def hash_password(password: str) -> str:
    """简单的密码哈希（生产环境建议用 bcrypt）"""
    return hashlib.sha256(password.encode() + b"logistics_salt_2024").hexdigest()


# ═══════════════════════════════════════════════════════════
# 客户 CRUD
# ═══════════════════════════════════════════════════════════

class CustomerManager:
    """客户管理器"""

    def __init__(self):
        init_db()

    # ── 查询 ─────────────────────────────────────────────

    def get_all(self, active_only: bool = False) -> List[Dict]:
        """获取所有客户"""
        conn = get_db()
        sql = "SELECT * FROM customers ORDER BY created_at DESC"
        if active_only:
            sql = "SELECT * FROM customers WHERE is_active=1 ORDER BY created_at DESC"
        rows = conn.execute(sql).fetchall()
        return [dict(r) for r in rows]

    def get_by_id(self, customer_id: int) -> Optional[Dict]:
        """按ID获取客户"""
        conn = get_db()
        row = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        return dict(row) if row else None

    def get_by_name(self, name: str) -> Optional[Dict]:
        """按名称获取客户"""
        conn = get_db()
        row = conn.execute("SELECT * FROM customers WHERE name=?", (name,)).fetchone()
        return dict(row) if row else None

    def get_active_api_keys(self) -> Dict[int, str]:
        """获取所有启用客户的API Key映射 {id: api_key}"""
        conn = get_db()
        rows = conn.execute(
            "SELECT id, api_key FROM customers WHERE is_active=1 AND api_key!=''"
        ).fetchall()
        return {r["id"]: r["api_key"] for r in rows}

    # ── 增删改 ───────────────────────────────────────────

    def add(self, name: str, display_name: str, company: str = "",
            api_key: str = "", model: str = "deepseek-chat",
            monthly_quota: int = 5000, contact_phone: str = "",
            contact_email: str = "", notes: str = "",
            expires_at: str = "") -> Optional[int]:
        """添加客户"""
        conn = get_db()
        masked = self._mask_key(api_key)
        try:
            cursor = conn.execute(
                """INSERT INTO customers
                   (name, display_name, company, api_key, api_key_masked, model,
                    monthly_quota, contact_phone, contact_email, notes, expires_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (name, display_name, company, api_key, masked, model,
                 monthly_quota, contact_phone, contact_email, notes, expires_at)
            )
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            return None  # 名称重复

    def update(self, customer_id: int, **kwargs) -> bool:
        """更新客户字段"""
        conn = get_db()
        allowed = {"display_name", "company", "api_key", "api_key_masked",
                    "model", "monthly_quota", "is_active", "contact_phone",
                    "contact_email", "notes", "expires_at", "last_login"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}

        if "api_key" in updates:
            updates["api_key_masked"] = self._mask_key(updates["api_key"])

        if not updates:
            return False

        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [customer_id]
        conn.execute(f"UPDATE customers SET {set_clause} WHERE id=?", values)
        conn.commit()
        return True

    def delete(self, customer_id: int) -> bool:
        """删除客户及其用量记录"""
        conn = get_db()
        conn.execute("DELETE FROM usage_logs WHERE customer_id=?", (customer_id,))
        conn.execute("DELETE FROM customers WHERE id=? AND name!='admin'", (customer_id,))
        conn.commit()
        return True

    def toggle_active(self, customer_id: int) -> bool:
        """切换启用/禁用"""
        conn = get_db()
        row = conn.execute("SELECT is_active FROM customers WHERE id=?", (customer_id,)).fetchone()
        if row:
            new = 0 if row["is_active"] else 1
            conn.execute("UPDATE customers SET is_active=? WHERE id=?", (new, customer_id))
            conn.commit()
            return True
        return False

    # ── 用量追踪 ─────────────────────────────────────────

    def log_usage(self, customer_id: int, pdf_filename: str = "",
                  order_count: int = 0, tokens_input: int = 0,
                  tokens_output: int = 0, parse_method: str = "",
                  success: bool = True):
        """记录一次API用量"""
        conn = get_db()
        # DeepSeek 价格估算: ¥1/百万输入 + ¥2/百万输出
        cost = (tokens_input / 1_000_000) * 1.0 + (tokens_output / 1_000_000) * 2.0
        conn.execute(
            """INSERT INTO usage_logs
               (customer_id, pdf_filename, order_count, tokens_input,
                tokens_output, parse_method, success, cost_estimate)
               VALUES (?,?,?,?,?,?,?,?)""",
            (customer_id, pdf_filename, order_count, tokens_input,
             tokens_output, parse_method, 1 if success else 0, round(cost, 6))
        )
        conn.commit()

    def get_usage(self, customer_id: int, days: int = 30) -> Dict:
        """获取客户用量统计"""
        conn = get_db()
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

        # 总量统计
        total = conn.execute(
            """SELECT COUNT(*) as total_requests,
                      SUM(order_count) as total_orders,
                      SUM(tokens_input) as total_input,
                      SUM(tokens_output) as total_output,
                      SUM(cost_estimate) as total_cost,
                      SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as success_count
               FROM usage_logs
               WHERE customer_id=? AND timestamp >= ?""",
            (customer_id, since)
        ).fetchone()

        # 本月统计
        month_start = datetime.now().replace(day=1).strftime("%Y-%m-%d")
        monthly = conn.execute(
            """SELECT COUNT(*) as requests,
                      SUM(order_count) as orders
               FROM usage_logs
               WHERE customer_id=? AND timestamp >= ?""",
            (customer_id, month_start)
        ).fetchone()

        # 按日统计（最近30天）
        daily = conn.execute(
            """SELECT DATE(timestamp) as date,
                      COUNT(*) as requests,
                      SUM(order_count) as orders,
                      SUM(cost_estimate) as cost
               FROM usage_logs
               WHERE customer_id=? AND timestamp >= ?
               GROUP BY DATE(timestamp)
               ORDER BY date DESC""",
            (customer_id, since)
        ).fetchall()

        customer = self.get_by_id(customer_id)
        quota = customer.get("monthly_quota", 5000) if customer else 5000
        monthly_orders = monthly["orders"] or 0

        return {
            "customer_name": customer.get("display_name", "") if customer else "",
            "period_days": days,
            "total_requests": total["total_requests"] or 0,
            "total_orders": total["total_orders"] or 0,
            "total_input_tokens": total["total_input"] or 0,
            "total_output_tokens": total["total_output"] or 0,
            "total_cost": round(total["total_cost"] or 0, 4),
            "success_rate": f"{total['success_count']/max(total['total_requests'],1)*100:.1f}%",
            "monthly_quota": quota,
            "monthly_used": monthly_orders,
            "quota_pct": f"{monthly_orders/max(quota,1)*100:.1f}%",
            "daily": [dict(r) for r in daily],
        }

    # ── 工具方法 ─────────────────────────────────────────

    def _mask_key(self, api_key: str) -> str:
        """脱敏显示API Key，只保留前后各4位"""
        if not api_key or len(api_key) <= 8:
            return api_key or ""
        return api_key[:4] + "****" + api_key[-4:]

    def verify_name(self, name: str) -> bool:
        """检查客户名称是否可用"""
        row = get_db().execute(
            "SELECT id FROM customers WHERE name=?", (name,)
        ).fetchone()
        return row is None

    # ── 全局设置 ─────────────────────────────────────────

    def get_setting(self, key: str, default: str = "") -> str:
        row = get_db().execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        conn = get_db()
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
            (key, value)
        )
        conn.commit()


# 全局单例
_customer_manager: Optional[CustomerManager] = None


def get_customer_manager() -> CustomerManager:
    global _customer_manager
    if _customer_manager is None:
        _customer_manager = CustomerManager()
    return _customer_manager
