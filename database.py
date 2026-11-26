from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


CATALOG_KINDS = frozenset({"car", "business", "property", "item"})
APPLICATION_KINDS = frozenset({"job", "organization"})


class Database:
    """Small SQLite data layer. All economy-changing methods use transactions."""

    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    @staticmethod
    def _rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        return [dict(row) for row in rows]

    def initialize(
        self,
        admin_ids: frozenset[int],
        start_balance: int,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    salary INTEGER NOT NULL CHECK (salary >= 0),
                    category TEXT NOT NULL DEFAULT 'civil'
                        CHECK (category IN ('civil', 'government')),
                    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                    created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS catalog_categories (
                    name TEXT PRIMARY KEY COLLATE NOCASE,
                    created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS catalog_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL
                        CHECK (kind IN ('car', 'business', 'property', 'item')),
                    name TEXT NOT NULL COLLATE NOCASE,
                    price INTEGER NOT NULL CHECK (price >= 0),
                    power INTEGER,
                    income INTEGER NOT NULL DEFAULT 0 CHECK (income >= 0),
                    category TEXT,
                    description TEXT NOT NULL DEFAULT '',
                    legacy_id INTEGER,
                    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                    created_at INTEGER NOT NULL,
                    UNIQUE (kind, name),
                    UNIQUE (kind, legacy_id)
                );

                CREATE TABLE IF NOT EXISTS players (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL DEFAULT '',
                    game_name TEXT NOT NULL,
                    cpm_id TEXT NOT NULL DEFAULT '',
                    balance INTEGER NOT NULL DEFAULT 0 CHECK (balance >= 0),
                    experience INTEGER NOT NULL DEFAULT 0 CHECK (experience >= 0),
                    level INTEGER NOT NULL DEFAULT 1 CHECK (level >= 1),
                    current_job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
                    last_work_at INTEGER NOT NULL DEFAULT 0,
                    banned INTEGER NOT NULL DEFAULT 0 CHECK (banned IN (0, 1)),
                    created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS administrators (
                    telegram_id INTEGER PRIMARY KEY,
                    added_by INTEGER,
                    created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS organizations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    leader_id INTEGER REFERENCES players(telegram_id) ON DELETE SET NULL,
                    created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS organization_members (
                    organization_id INTEGER NOT NULL
                        REFERENCES organizations(id) ON DELETE CASCADE,
                    player_id INTEGER NOT NULL
                        REFERENCES players(telegram_id) ON DELETE CASCADE,
                    rank TEXT NOT NULL DEFAULT 'Участник',
                    joined_at INTEGER NOT NULL,
                    PRIMARY KEY (organization_id, player_id)
                );

                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id INTEGER NOT NULL
                        REFERENCES players(telegram_id) ON DELETE CASCADE,
                    kind TEXT NOT NULL CHECK (kind IN ('job', 'organization')),
                    job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
                    organization_id INTEGER
                        REFERENCES organizations(id) ON DELETE SET NULL,
                    submitted_at INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'approved', 'rejected')),
                    decided_at INTEGER,
                    decided_by INTEGER,
                    note TEXT NOT NULL DEFAULT '',
                    CHECK (
                        (kind = 'job' AND job_id IS NOT NULL AND organization_id IS NULL)
                        OR
                        (kind = 'organization' AND organization_id IS NOT NULL AND job_id IS NULL)
                    )
                );

                CREATE TABLE IF NOT EXISTS owned_assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id INTEGER NOT NULL
                        REFERENCES players(telegram_id) ON DELETE CASCADE,
                    catalog_item_id INTEGER NOT NULL
                        REFERENCES catalog_items(id) ON DELETE RESTRICT,
                    kind TEXT NOT NULL
                        CHECK (kind IN ('car', 'business', 'property')),
                    purchased_at INTEGER NOT NULL,
                    last_income_at INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS inventory (
                    player_id INTEGER NOT NULL
                        REFERENCES players(telegram_id) ON DELETE CASCADE,
                    catalog_item_id INTEGER NOT NULL
                        REFERENCES catalog_items(id) ON DELETE RESTRICT,
                    quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
                    PRIMARY KEY (player_id, catalog_item_id)
                );

                CREATE TABLE IF NOT EXISTS transaction_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id INTEGER NOT NULL
                        REFERENCES players(telegram_id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    actor_id INTEGER,
                    created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS admin_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    target_id INTEGER,
                    details TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_applications_status
                    ON applications(status, submitted_at);
                CREATE INDEX IF NOT EXISTS idx_owned_assets_player
                    ON owned_assets(player_id, kind);
                CREATE INDEX IF NOT EXISTS idx_history_player
                    ON transaction_history(player_id, created_at);
                """
            )

        now = int(time.time())
        with self._transaction() as connection:
            for category in (
                "Запчасти",
                "Одежда и брюки",
                "Аксессуары",
                "Прочие товары",
            ):
                connection.execute(
                    "INSERT OR IGNORE INTO catalog_categories(name, created_at) VALUES (?, ?)",
                    (category, now),
                )
            for admin_id in admin_ids:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO administrators(telegram_id, added_by, created_at)
                    VALUES (?, NULL, ?)
                    """,
                    (admin_id, now),
                )
            self._seed_organizations(connection, now)
            self._seed_catalog(connection, now)
            connection.execute(
                """
                INSERT OR IGNORE INTO jobs(name, salary, category, active, created_at)
                VALUES ('Министерство здравоохранения', 5000, 'government', 1, ?)
                """,
                (now,),
            )
            for name, salary in (
                ("Водитель автобуса", 2300),
                ("Водитель эвакуатора", 2400),
                ("Механик", 2000),
                ("Дальнобойщик", 2500),
                ("Инкассатор", 2200),
                ("Строитель", 2150),
                ("Фермер", 2100),
                ("Курьер", 2150),
                ("Таксист", 2200),
            ):
                connection.execute(
                    """
                    INSERT OR IGNORE INTO jobs(name, salary, category, active, created_at)
                    VALUES (?, ?, 'civil', 1, ?)
                    """,
                    (name, salary, now),
                )
            if start_balance < 0:
                raise ValueError("Starting balance must not be negative")

    @staticmethod
    def _seed_organizations(connection: sqlite3.Connection, now: int) -> None:
        for name in (
            "Министерство здравоохранения",
            "МВД",
            "ФСБ",
            "Прокуратура",
            "Правительство",
        ):
            connection.execute(
                "INSERT OR IGNORE INTO organizations(name, created_at) VALUES (?, ?)",
                (name, now),
            )

    @staticmethod
    def _seed_catalog(connection: sqlite3.Connection, now: int) -> None:
        path = Path(__file__).resolve().parent / "data" / "legacy_catalog.json"
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        for kind in ("car", "business", "property"):
            for item in data.get(kind, []):
                connection.execute(
                    """
                    INSERT OR IGNORE INTO catalog_items(
                        kind, name, price, power, income, description, legacy_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        kind,
                        item["name"],
                        int(item["price"]),
                        item.get("power"),
                        int(item.get("income", 0)),
                        item.get("description", ""),
                        item.get("legacy_id"),
                        now,
                    ),
                )
        for category, items in data.get("jobs", {}).items():
            for item in items:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO jobs(name, salary, category, active, created_at)
                    VALUES (?, ?, ?, 1, ?)
                    """,
                    (
                        item["name"],
                        int(item["salary"]),
                        "government" if category == "government" else "civil",
                        now,
                    ),
                )

    def create_player(
        self,
        telegram_id: int,
        username: str,
        game_name: str,
        cpm_id: str,
        start_balance: int,
    ) -> dict[str, Any]:
        now = int(time.time())
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT 1 FROM players WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            cursor = connection.execute(
                """
                INSERT INTO players(
                    telegram_id, username, game_name, cpm_id, balance, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET username = excluded.username
                """,
                (telegram_id, username, game_name, cpm_id, start_balance, now),
            )
            created = existing is None
            if created:
                connection.execute(
                    """
                    INSERT INTO transaction_history(player_id, kind, amount, note, created_at)
                    VALUES (?, 'registration', ?, 'Стартовый баланс', ?)
                    """,
                    (telegram_id, start_balance, now),
                )
            row = connection.execute(
                "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
        return {**dict(row), "_created": created}

    def get_player(self, telegram_id: int) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT p.*, j.name AS job_name, j.salary AS job_salary,
                       j.category AS job_category
                FROM players p
                LEFT JOIN jobs j ON j.id = p.current_job_id
                WHERE p.telegram_id = ?
                """,
                (telegram_id,),
            ).fetchone()
        return self._dict(row)

    def get_job_by_name(self, name: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE name = ? AND active = 1", (name.strip(),)
            ).fetchone()
        return self._dict(row)

    def list_jobs(self, category: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM jobs WHERE active = 1"
        params: tuple[Any, ...] = ()
        if category in {"civil", "government"}:
            query += " AND category = ?"
            params = (category,)
        query += " ORDER BY category, salary, name"
        with self._connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return self._rows(rows)

    def add_job(self, name: str, salary: int, category: str = "civil") -> int:
        if not name.strip() or salary < 0 or category not in {"civil", "government"}:
            raise ValueError("Invalid job data")
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO jobs(name, salary, category, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (name.strip(), salary, category, int(time.time())),
            )
            return int(cursor.lastrowid)

    def set_job_salary(self, job_id: int, salary: int) -> bool:
        if salary < 0:
            raise ValueError("Salary must not be negative")
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET salary = ? WHERE id = ? AND active = 1",
                (salary, job_id),
            )
            return cursor.rowcount == 1

    def deactivate_job(self, job_id: int, admin_id: int) -> bool:
        now = int(time.time())
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET active = 0 WHERE id = ? AND active = 1",
                (job_id,),
            )
            if cursor.rowcount != 1:
                return False
            connection.execute(
                "UPDATE players SET current_job_id = NULL WHERE current_job_id = ?",
                (job_id,),
            )
            connection.execute(
                """
                UPDATE applications
                SET status = 'rejected', decided_at = ?, decided_by = ?,
                    note = 'Работа отключена администратором'
                WHERE job_id = ? AND kind = 'job' AND status = 'pending'
                """,
                (now, admin_id, job_id),
            )
            connection.execute(
                """
                INSERT INTO admin_audit(admin_id, action, target_id, details, created_at)
                VALUES (?, 'job_delete', ?, '', ?)
                """,
                (admin_id, job_id, now),
            )
            return True

    def assign_job(self, player_id: int, job_name: str | None) -> bool:
        with self._transaction() as connection:
            job_id = None
            if job_name:
                row = connection.execute(
                    "SELECT id FROM jobs WHERE name = ? AND active = 1",
                    (job_name.strip(),),
                ).fetchone()
                if not row:
                    return False
                job_id = row["id"]
            cursor = connection.execute(
                "UPDATE players SET current_job_id = ? WHERE telegram_id = ?",
                (job_id, player_id),
            )
            return cursor.rowcount == 1

    def work(self, player_id: int, cooldown_seconds: int, now: int | None = None) -> dict[str, Any]:
        if now is None:
            now = int(time.time())
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT p.balance, p.experience, p.last_work_at, p.banned,
                       j.id AS job_id, j.name AS job_name, j.salary
                FROM players p
                LEFT JOIN jobs j ON j.id = p.current_job_id AND j.active = 1
                WHERE p.telegram_id = ?
                """,
                (player_id,),
            ).fetchone()
            if not row:
                return {"ok": False, "reason": "not_registered"}
            if row["banned"]:
                return {"ok": False, "reason": "banned"}
            if not row["job_id"]:
                return {"ok": False, "reason": "no_job"}
            remaining = cooldown_seconds - (now - row["last_work_at"])
            if remaining > 0:
                return {"ok": False, "reason": "cooldown", "remaining": remaining}
            salary = int(row["salary"])
            experience = int(row["experience"]) + 25
            level = 1 + experience // 100
            connection.execute(
                """
                UPDATE players
                SET balance = balance + ?, experience = ?, level = ?, last_work_at = ?
                WHERE telegram_id = ?
                """,
                (salary, experience, level, now, player_id),
            )
            connection.execute(
                """
                INSERT INTO transaction_history(player_id, kind, amount, note, created_at)
                VALUES (?, 'salary', ?, ?, ?)
                """,
                (player_id, salary, f"Работа: {row['job_name']}", now),
            )
            new_balance = int(row["balance"]) + salary
        return {
            "ok": True,
            "salary": salary,
            "balance": new_balance,
            "experience": experience,
            "level": level,
            "job": row["job_name"],
        }

    def transfer(self, sender_id: int, recipient_id: int, amount: int) -> tuple[bool, str]:
        if amount <= 0 or sender_id == recipient_id:
            return False, "invalid"
        now = int(time.time())
        with self._transaction() as connection:
            sender = connection.execute(
                "SELECT balance, banned FROM players WHERE telegram_id = ?",
                (sender_id,),
            ).fetchone()
            recipient = connection.execute(
                "SELECT telegram_id, banned FROM players WHERE telegram_id = ?",
                (recipient_id,),
            ).fetchone()
            if not sender or not recipient:
                return False, "not_found"
            if sender["banned"] or recipient["banned"]:
                return False, "banned"
            cursor = connection.execute(
                "UPDATE players SET balance = balance - ? WHERE telegram_id = ? AND balance >= ?",
                (amount, sender_id, amount),
            )
            if cursor.rowcount != 1:
                return False, "insufficient"
            connection.execute(
                "UPDATE players SET balance = balance + ? WHERE telegram_id = ?",
                (amount, recipient_id),
            )
            connection.executemany(
                """
                INSERT INTO transaction_history(player_id, kind, amount, note, actor_id, created_at)
                VALUES (?, 'transfer', ?, ?, ?, ?)
                """,
                [
                    (sender_id, -amount, f"Перевод игроку {recipient_id}", sender_id, now),
                    (recipient_id, amount, f"Перевод от игрока {sender_id}", sender_id, now),
                ],
            )
        return True, "ok"

    def adjust_balance(
        self,
        player_id: int,
        amount: int,
        action: str,
        admin_id: int,
    ) -> tuple[bool, int | str]:
        if amount <= 0:
            return False, "invalid"
        delta = amount if action == "give" else -amount
        now = int(time.time())
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT balance FROM players WHERE telegram_id = ?", (player_id,)
            ).fetchone()
            if not row:
                return False, "not_found"
            updated = int(row["balance"]) + delta
            if updated < 0:
                return False, "insufficient"
            connection.execute(
                "UPDATE players SET balance = ? WHERE telegram_id = ?",
                (updated, player_id),
            )
            connection.execute(
                """
                INSERT INTO transaction_history(
                    player_id, kind, amount, note, actor_id, created_at
                ) VALUES (?, ?, ?, 'Изменение баланса администрацией', ?, ?)
                """,
                (player_id, f"admin_{action}", delta, admin_id, now),
            )
            connection.execute(
                """
                INSERT INTO admin_audit(admin_id, action, target_id, details, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (admin_id, f"balance_{action}", player_id, str(amount), now),
            )
        return True, updated

    def top_players(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT telegram_id, username, game_name, balance, level, experience
                FROM players WHERE banned = 0
                ORDER BY balance DESC, experience DESC, telegram_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return self._rows(rows)

    def add_catalog_item(
        self,
        kind: str,
        name: str,
        price: int,
        *,
        power: int | None = None,
        income: int = 0,
        category: str | None = None,
        description: str = "",
    ) -> int:
        if kind not in CATALOG_KINDS:
            raise ValueError("Unknown catalog type")
        if not name.strip() or price < 0 or income < 0 or (power is not None and power < 0):
            raise ValueError("Invalid catalog item")
        now = int(time.time())
        with self._transaction() as connection:
            if kind == "item":
                category = (category or "Прочие товары").strip()
                connection.execute(
                    "INSERT OR IGNORE INTO catalog_categories(name, created_at) VALUES (?, ?)",
                    (category, now),
                )
            cursor = connection.execute(
                """
                INSERT INTO catalog_items(
                    kind, name, price, power, income, category, description, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kind,
                    name.strip(),
                    price,
                    power,
                    income,
                    category,
                    description.strip(),
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def list_catalog(
        self,
        kind: str,
        category: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        if kind not in CATALOG_KINDS:
            return []
        query = "SELECT * FROM catalog_items WHERE kind = ? AND active = 1"
        params: list[Any] = [kind]
        if category and kind == "item":
            query += " AND category = ? COLLATE NOCASE"
            params.append(category)
        query += " ORDER BY id LIMIT ?"
        params.append(limit)
        with self._connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return self._rows(rows)

    def get_catalog_item(self, item_id: int, kind: str | None = None) -> dict[str, Any] | None:
        query = "SELECT * FROM catalog_items WHERE id = ? AND active = 1"
        params: list[Any] = [item_id]
        if kind in CATALOG_KINDS:
            query += " AND kind = ?"
            params.append(kind)
        with self._connection() as connection:
            row = connection.execute(query, params).fetchone()
        return self._dict(row)

    def edit_catalog_price(self, kind: str, item_id: int, price: int) -> bool:
        if kind not in CATALOG_KINDS or price < 0:
            return False
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE catalog_items SET price = ? WHERE id = ? AND kind = ? AND active = 1",
                (price, item_id, kind),
            )
            return cursor.rowcount == 1

    def deactivate_catalog_item(self, kind: str, item_id: int) -> bool:
        if kind not in CATALOG_KINDS:
            return False
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE catalog_items SET active = 0 WHERE id = ? AND kind = ? AND active = 1",
                (item_id, kind),
            )
            return cursor.rowcount == 1

    def categories(self) -> list[str]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT name FROM catalog_categories ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [row["name"] for row in rows]

    def purchase(self, player_id: int, item_id: int, kind: str) -> tuple[bool, str, int | None]:
        if kind not in {"car", "business", "property", "item"}:
            return False, "invalid_kind", None
        now = int(time.time())
        with self._transaction() as connection:
            player = connection.execute(
                "SELECT balance, banned FROM players WHERE telegram_id = ?",
                (player_id,),
            ).fetchone()
            item = connection.execute(
                """
                SELECT * FROM catalog_items
                WHERE id = ? AND kind = ? AND active = 1
                """,
                (item_id, kind),
            ).fetchone()
            if not player:
                return False, "not_registered", None
            if player["banned"]:
                return False, "banned", None
            if not item:
                return False, "not_found", None
            price = int(item["price"])
            if int(player["balance"]) < price:
                return False, "insufficient", price
            connection.execute(
                "UPDATE players SET balance = balance - ? WHERE telegram_id = ?",
                (price, player_id),
            )
            if kind == "item":
                connection.execute(
                    """
                    INSERT INTO inventory(player_id, catalog_item_id, quantity)
                    VALUES (?, ?, 1)
                    ON CONFLICT(player_id, catalog_item_id)
                    DO UPDATE SET quantity = quantity + 1
                    """,
                    (player_id, item_id),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO owned_assets(
                        player_id, catalog_item_id, kind, purchased_at, last_income_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (player_id, item_id, kind, now, now),
                )
            connection.execute(
                """
                INSERT INTO transaction_history(player_id, kind, amount, note, created_at)
                VALUES (?, 'purchase', ?, ?, ?)
                """,
                (player_id, -price, f"{kind}: {item['name']}", now),
            )
        return True, str(item["name"]), price

    def list_owned_assets(self, player_id: int, kind: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT oa.id, oa.kind, oa.purchased_at, oa.last_income_at,
                   ci.id AS item_id, ci.name, ci.price, ci.power, ci.income,
                   ci.description
            FROM owned_assets oa
            JOIN catalog_items ci ON ci.id = oa.catalog_item_id
            WHERE oa.player_id = ?
        """
        params: list[Any] = [player_id]
        if kind in {"car", "business", "property"}:
            query += " AND oa.kind = ?"
            params.append(kind)
        query += " ORDER BY oa.kind, oa.id"
        with self._connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return self._rows(rows)

    def list_inventory(self, player_id: int) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT ci.name, ci.category, ci.description, inventory.quantity
                FROM inventory
                JOIN catalog_items ci ON ci.id = inventory.catalog_item_id
                WHERE inventory.player_id = ? AND inventory.quantity > 0
                ORDER BY ci.category, ci.name
                """,
                (player_id,),
            ).fetchall()
        return self._rows(rows)

    def collect_business_income(
        self,
        player_id: int,
        payout_seconds: int,
        now: int | None = None,
    ) -> tuple[bool, int, int]:
        if now is None:
            now = int(time.time())
        with self._transaction() as connection:
            player = connection.execute(
                "SELECT banned FROM players WHERE telegram_id = ?", (player_id,)
            ).fetchone()
            if not player:
                return False, 0, 0
            if player["banned"]:
                return False, -1, 0
            rows = connection.execute(
                """
                SELECT oa.id, oa.last_income_at, ci.income, ci.name
                FROM owned_assets oa
                JOIN catalog_items ci ON ci.id = oa.catalog_item_id
                WHERE oa.player_id = ? AND oa.kind = 'business'
                """,
                (player_id,),
            ).fetchall()
            amount = 0
            collected = 0
            for row in rows:
                elapsed = now - int(row["last_income_at"])
                periods = elapsed // payout_seconds
                if periods < 1:
                    continue
                earned = int(row["income"]) * periods
                amount += earned
                collected += 1
                connection.execute(
                    "UPDATE owned_assets SET last_income_at = ? WHERE id = ?",
                    (int(row["last_income_at"]) + periods * payout_seconds, row["id"]),
                )
            if amount:
                connection.execute(
                    "UPDATE players SET balance = balance + ? WHERE telegram_id = ?",
                    (amount, player_id),
                )
                connection.execute(
                    """
                    INSERT INTO transaction_history(player_id, kind, amount, note, created_at)
                    VALUES (?, 'business_income', ?, 'Доход от бизнеса', ?)
                    """,
                    (player_id, amount, now),
                )
        return True, amount, collected

    def create_application(
        self,
        player_id: int,
        kind: str,
        *,
        job_id: int | None = None,
        organization_id: int | None = None,
    ) -> tuple[bool, int | str]:
        if kind not in APPLICATION_KINDS:
            return False, "invalid"
        now = int(time.time())
        with self._transaction() as connection:
            player = connection.execute(
                "SELECT banned FROM players WHERE telegram_id = ?", (player_id,)
            ).fetchone()
            if not player:
                return False, "not_registered"
            if player["banned"]:
                return False, "banned"
            if kind == "job":
                target = connection.execute(
                    "SELECT id FROM jobs WHERE id = ? AND active = 1", (job_id,)
                ).fetchone()
                if not target:
                    return False, "not_found"
            else:
                target = connection.execute(
                    "SELECT id FROM organizations WHERE id = ?", (organization_id,)
                ).fetchone()
                if not target:
                    return False, "not_found"
                member = connection.execute(
                    """
                    SELECT 1 FROM organization_members
                    WHERE organization_id = ? AND player_id = ?
                    """,
                    (organization_id, player_id),
                ).fetchone()
                if member:
                    return False, "already_member"
            duplicate = connection.execute(
                """
                SELECT id FROM applications
                WHERE player_id = ? AND kind = ? AND status = 'pending'
                  AND ((job_id IS NOT NULL AND job_id = ?)
                    OR (organization_id IS NOT NULL AND organization_id = ?))
                """,
                (player_id, kind, job_id, organization_id),
            ).fetchone()
            if duplicate:
                return False, "pending"
            cursor = connection.execute(
                """
                INSERT INTO applications(
                    player_id, kind, job_id, organization_id, submitted_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (player_id, kind, job_id, organization_id, now),
            )
            return True, int(cursor.lastrowid)

    def list_applications(self, pending_only: bool = True, limit: int = 30) -> list[dict[str, Any]]:
        query = """
            SELECT a.*, p.username, p.game_name, j.name AS job_name,
                   o.name AS organization_name
            FROM applications a
            JOIN players p ON p.telegram_id = a.player_id
            LEFT JOIN jobs j ON j.id = a.job_id
            LEFT JOIN organizations o ON o.id = a.organization_id
        """
        if pending_only:
            query += " WHERE a.status = 'pending'"
        query += " ORDER BY a.submitted_at, a.id LIMIT ?"
        with self._connection() as connection:
            rows = connection.execute(query, (limit,)).fetchall()
        return self._rows(rows)

    def review_application(
        self,
        application_id: int,
        approve: bool,
        admin_id: int,
        note: str = "",
    ) -> dict[str, Any] | None:
        now = int(time.time())
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT a.*, j.name AS job_name, o.name AS organization_name
                FROM applications a
                LEFT JOIN jobs j ON j.id = a.job_id
                LEFT JOIN organizations o ON o.id = a.organization_id
                WHERE a.id = ? AND a.status = 'pending'
                """,
                (application_id,),
            ).fetchone()
            if not row:
                return None
            status = "approved" if approve else "rejected"
            if approve and row["kind"] == "job":
                connection.execute(
                    "UPDATE players SET current_job_id = ? WHERE telegram_id = ?",
                    (row["job_id"], row["player_id"]),
                )
            elif approve:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO organization_members(
                        organization_id, player_id, rank, joined_at
                    ) VALUES (?, ?, 'Участник', ?)
                    """,
                    (row["organization_id"], row["player_id"], now),
                )
            connection.execute(
                """
                UPDATE applications
                SET status = ?, decided_at = ?, decided_by = ?, note = ?
                WHERE id = ? AND status = 'pending'
                """,
                (status, now, admin_id, note[:500], application_id),
            )
            connection.execute(
                """
                INSERT INTO admin_audit(admin_id, action, target_id, details, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (admin_id, f"application_{status}", row["player_id"], str(application_id), now),
            )
            result = dict(row)
            result["status"] = status
        return result

    def list_organizations(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT o.id, o.name, o.leader_id, p.username AS leader_username,
                       COUNT(m.player_id) AS member_count
                FROM organizations o
                LEFT JOIN players p ON p.telegram_id = o.leader_id
                LEFT JOIN organization_members m ON m.organization_id = o.id
                GROUP BY o.id
                ORDER BY o.name COLLATE NOCASE
                """
            ).fetchall()
        return self._rows(rows)

    def create_organization(self, name: str, leader_id: int, admin_id: int) -> int:
        now = int(time.time())
        with self._transaction() as connection:
            if not connection.execute(
                "SELECT 1 FROM players WHERE telegram_id = ?", (leader_id,)
            ).fetchone():
                raise ValueError("Игрок-лидер не зарегистрирован.")
            cursor = connection.execute(
                "INSERT INTO organizations(name, leader_id, created_at) VALUES (?, ?, ?)",
                (name.strip(), leader_id, now),
            )
            organization_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO organization_members(organization_id, player_id, rank, joined_at)
                VALUES (?, ?, 'Руководитель', ?)
                """,
                (organization_id, leader_id, now),
            )
            connection.execute(
                """
                INSERT INTO admin_audit(admin_id, action, target_id, details, created_at)
                VALUES (?, 'organization_create', ?, ?, ?)
                """,
                (admin_id, leader_id, name.strip(), now),
            )
            return organization_id

    def set_organization_leader(
        self,
        organization_id: int,
        leader_id: int,
        admin_id: int,
    ) -> bool:
        now = int(time.time())
        with self._transaction() as connection:
            org = connection.execute(
                "SELECT id, leader_id FROM organizations WHERE id = ?", (organization_id,)
            ).fetchone()
            player = connection.execute(
                "SELECT telegram_id FROM players WHERE telegram_id = ?", (leader_id,)
            ).fetchone()
            if not org or not player:
                return False
            if org["leader_id"] and org["leader_id"] != leader_id:
                connection.execute(
                    """
                    UPDATE organization_members SET rank = 'Участник'
                    WHERE organization_id = ? AND player_id = ? AND rank = 'Руководитель'
                    """,
                    (organization_id, org["leader_id"]),
                )
            connection.execute(
                "UPDATE organizations SET leader_id = ? WHERE id = ?",
                (leader_id, organization_id),
            )
            connection.execute(
                """
                INSERT INTO organization_members(organization_id, player_id, rank, joined_at)
                VALUES (?, ?, 'Руководитель', ?)
                ON CONFLICT(organization_id, player_id)
                DO UPDATE SET rank = 'Руководитель'
                """,
                (organization_id, leader_id, now),
            )
            connection.execute(
                """
                INSERT INTO admin_audit(admin_id, action, target_id, details, created_at)
                VALUES (?, 'organization_leader', ?, ?, ?)
                """,
                (admin_id, leader_id, str(organization_id), now),
            )
            return True

    def get_player_organizations(self, player_id: int) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT o.id, o.name, o.leader_id, m.rank
                FROM organization_members m
                JOIN organizations o ON o.id = m.organization_id
                WHERE m.player_id = ?
                ORDER BY o.name COLLATE NOCASE
                """,
                (player_id,),
            ).fetchall()
        return self._rows(rows)

    def find_organization(self, name: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM organizations WHERE name = ?", (name.strip(),)
            ).fetchone()
        return self._dict(row)

    def set_member_rank(
        self,
        organization_id: int,
        player_id: int,
        rank: str,
        actor_id: int,
        is_admin: bool,
    ) -> tuple[bool, str]:
        now = int(time.time())
        with self._transaction() as connection:
            org = connection.execute(
                "SELECT leader_id, name FROM organizations WHERE id = ?",
                (organization_id,),
            ).fetchone()
            if not org:
                return False, "organization_not_found"
            if not is_admin and org["leader_id"] != actor_id:
                return False, "forbidden"
            cursor = connection.execute(
                """
                UPDATE organization_members SET rank = ?
                WHERE organization_id = ? AND player_id = ?
                """,
                (rank.strip(), organization_id, player_id),
            )
            if cursor.rowcount != 1:
                return False, "member_not_found"
            connection.execute(
                """
                INSERT INTO admin_audit(admin_id, action, target_id, details, created_at)
                VALUES (?, 'organization_rank', ?, ?, ?)
                """,
                (actor_id, str(organization_id), f"{player_id}: {rank.strip()}", now),
            )
        return True, "ok"

    def remove_organization_member(
        self,
        organization_id: int,
        player_id: int,
        actor_id: int,
        is_admin: bool,
    ) -> tuple[bool, str]:
        now = int(time.time())
        with self._transaction() as connection:
            org = connection.execute(
                "SELECT leader_id, name FROM organizations WHERE id = ?",
                (organization_id,),
            ).fetchone()
            if not org:
                return False, "organization_not_found"
            if not is_admin and org["leader_id"] != actor_id:
                return False, "forbidden"
            if player_id == org["leader_id"] and not is_admin:
                return False, "leader_protected"
            cursor = connection.execute(
                """
                DELETE FROM organization_members
                WHERE organization_id = ? AND player_id = ?
                """,
                (organization_id, player_id),
            )
            if cursor.rowcount != 1:
                return False, "member_not_found"
            connection.execute(
                """
                INSERT INTO admin_audit(admin_id, action, target_id, details, created_at)
                VALUES (?, 'organization_remove_member', ?, ?, ?)
                """,
                (actor_id, player_id, str(organization_id), now),
            )
        return True, "ok"

    def set_banned(self, player_id: int, banned: bool, admin_id: int) -> bool:
        now = int(time.time())
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE players SET banned = ? WHERE telegram_id = ?",
                (int(banned), player_id),
            )
            if cursor.rowcount != 1:
                return False
            connection.execute(
                """
                INSERT INTO admin_audit(admin_id, action, target_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (admin_id, "ban" if banned else "unban", player_id, now),
            )
            return True

    def is_admin(self, telegram_id: int, env_admin_ids: frozenset[int] = frozenset()) -> bool:
        if telegram_id in env_admin_ids:
            return True
        with self._connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM administrators WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
        return row is not None

    def is_owner(self, telegram_id: int, owner_ids: frozenset[int]) -> bool:
        return telegram_id in owner_ids

    def add_admin(self, telegram_id: int, actor_id: int) -> None:
        now = int(time.time())
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO administrators(telegram_id, added_by, created_at)
                VALUES (?, ?, ?)
                """,
                (telegram_id, actor_id, now),
            )
            connection.execute(
                """
                INSERT INTO admin_audit(admin_id, action, target_id, created_at)
                VALUES (?, 'admin_add', ?, ?)
                """,
                (actor_id, telegram_id, now),
            )

    def remove_admin(self, telegram_id: int, actor_id: int) -> bool:
        now = int(time.time())
        with self._transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM administrators WHERE telegram_id = ?", (telegram_id,)
            )
            connection.execute(
                """
                INSERT INTO admin_audit(admin_id, action, target_id, created_at)
                VALUES (?, 'admin_remove', ?, ?)
                """,
                (actor_id, telegram_id, now),
            )
            return cursor.rowcount == 1

    def list_admins(self, env_admin_ids: frozenset[int] = frozenset()) -> list[int]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT telegram_id FROM administrators ORDER BY telegram_id"
            ).fetchall()
        return sorted(set(env_admin_ids) | {int(row["telegram_id"]) for row in rows})

    def audit_admin(
        self,
        admin_id: int,
        action: str,
        target_id: int | None = None,
        details: str = "",
    ) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO admin_audit(admin_id, action, target_id, details, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (admin_id, action, target_id, details[:1000], int(time.time())),
            )

    def stats(self) -> dict[str, int]:
        with self._connection() as connection:
            return {
                "players": connection.execute(
                    "SELECT COUNT(*) FROM players WHERE banned = 0"
                ).fetchone()[0],
                "banned": connection.execute(
                    "SELECT COUNT(*) FROM players WHERE banned = 1"
                ).fetchone()[0],
                "cars": connection.execute(
                    "SELECT COUNT(*) FROM catalog_items WHERE kind = 'car' AND active = 1"
                ).fetchone()[0],
                "businesses": connection.execute(
                    "SELECT COUNT(*) FROM catalog_items WHERE kind = 'business' AND active = 1"
                ).fetchone()[0],
                "properties": connection.execute(
                    "SELECT COUNT(*) FROM catalog_items WHERE kind = 'property' AND active = 1"
                ).fetchone()[0],
                "jobs": connection.execute(
                    "SELECT COUNT(*) FROM jobs WHERE active = 1"
                ).fetchone()[0],
                "organizations": connection.execute(
                    "SELECT COUNT(*) FROM organizations"
                ).fetchone()[0],
                "pending_applications": connection.execute(
                    "SELECT COUNT(*) FROM applications WHERE status = 'pending'"
                ).fetchone()[0],
            }
