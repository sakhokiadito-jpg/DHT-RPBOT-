from __future__ import annotations

import sqlite3

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config import Settings
from database import Database
from services.formatting import money


KIND_NAMES = {
    "car": "автомобиль",
    "business": "бизнес",
    "property": "недвижимость",
    "item": "товар",
}


def build_admin_router(database: Database, settings: Settings) -> Router:
    router = Router(name="admin")
    all_admin_ids = settings.admin_ids | settings.owner_ids

    def allowed(message: Message) -> bool:
        return database.is_admin(message.from_user.id, all_admin_ids)

    async def require_admin(message: Message) -> bool:
        if allowed(message):
            return True
        await message.answer("Команда доступна только администраторам.")
        return False

    def argument(message: Message) -> str:
        return (message.text or "").partition(" ")[2].strip()

    @router.message(Command("adminhelp"))
    async def admin_help(message: Message) -> None:
        if not await require_admin(message):
            return
        await message.answer(
            "Административные команды:\n\n"
            "/addcar Название | Цена | Мощность | Описание\n"
            "/addbusiness Название | Цена | Доход | Описание\n"
            "/addproperty Название | Цена | Описание\n"
            "/addjob Название | Зарплата | civil или government\n"
            "/additem Категория | Название | Цена | Описание\n"
            "/setsalary Название работы | Зарплата\n"
            "/deletejob ID\n"
            "/editprice car|business|property|item ID Цена\n"
            "/deletecatalog car|business|property|item ID\n"
            "/listcatalog car|business|property|item\n"
            "/givemoney Telegram_ID Сумма\n"
            "/takemoney Telegram_ID Сумма\n"
            "/setjob Telegram_ID | Название работы\n"
            "/removejob Telegram_ID\n"
            "/ban Telegram_ID · /unban Telegram_ID\n"
            "/applications · /approve ID · /reject ID Причина\n"
            "/orgcreate Название | Telegram_ID лидера\n"
            "/orgleader ID_организации Telegram_ID\n"
            "/orgrank ID_организации Telegram_ID Ранг\n"
            "/orgfire ID_организации Telegram_ID\n"
            "/stats\n\n"
            "Владельцам:\n/adminadd Telegram_ID · /adminremove Telegram_ID"
        )

    @router.message(Command("addcar"))
    async def add_car(message: Message) -> None:
        if not await require_admin(message):
            return
        fields = argument(message).split("|")
        if len(fields) not in {3, 4}:
            await message.answer("Формат: /addcar Название | Цена | Мощность | Описание")
            return
        try:
            name, price_text, power_text = (item.strip() for item in fields[:3])
            item_id = database.add_catalog_item(
                "car",
                name,
                int(price_text),
                power=int(power_text),
                description=fields[3].strip() if len(fields) == 4 else "",
            )
        except (ValueError, sqlite3.IntegrityError):
            await message.answer("Не удалось добавить авто. Проверьте данные и уникальность названия.")
            return
        database.audit_admin(message.from_user.id, "catalog_add", details=f"car:{item_id}")
        await message.answer(f"Автомобиль добавлен в SQLite. ID: {item_id}.")

    @router.message(Command("addbusiness"))
    async def add_business(message: Message) -> None:
        if not await require_admin(message):
            return
        fields = argument(message).split("|")
        if len(fields) not in {3, 4}:
            await message.answer("Формат: /addbusiness Название | Цена | Доход | Описание")
            return
        try:
            name, price_text, income_text = (item.strip() for item in fields[:3])
            item_id = database.add_catalog_item(
                "business",
                name,
                int(price_text),
                income=int(income_text),
                description=fields[3].strip() if len(fields) == 4 else "",
            )
        except (ValueError, sqlite3.IntegrityError):
            await message.answer("Не удалось добавить бизнес. Проверьте числа и название.")
            return
        database.audit_admin(message.from_user.id, "catalog_add", details=f"business:{item_id}")
        await message.answer(f"Бизнес добавлен в SQLite. ID: {item_id}.")

    @router.message(Command("addproperty"))
    async def add_property(message: Message) -> None:
        if not await require_admin(message):
            return
        fields = argument(message).split("|")
        if len(fields) not in {2, 3}:
            await message.answer("Формат: /addproperty Название | Цена | Описание")
            return
        try:
            item_id = database.add_catalog_item(
                "property",
                fields[0].strip(),
                int(fields[1].strip()),
                description=fields[2].strip() if len(fields) == 3 else "",
            )
        except (ValueError, sqlite3.IntegrityError):
            await message.answer("Не удалось добавить недвижимость. Проверьте данные.")
            return
        database.audit_admin(message.from_user.id, "catalog_add", details=f"property:{item_id}")
        await message.answer(f"Недвижимость добавлена в SQLite. ID: {item_id}.")

    @router.message(Command("additem"))
    async def add_item(message: Message) -> None:
        if not await require_admin(message):
            return
        fields = argument(message).split("|")
        if len(fields) != 4:
            await message.answer("Формат: /additem Категория | Название | Цена | Описание")
            return
        try:
            category, name, price_text, description = (item.strip() for item in fields)
            item_id = database.add_catalog_item(
                "item",
                name,
                int(price_text),
                category=category,
                description=description,
            )
        except (ValueError, sqlite3.IntegrityError):
            await message.answer("Не удалось добавить товар. Проверьте данные и название.")
            return
        database.audit_admin(message.from_user.id, "catalog_add", details=f"item:{item_id}")
        await message.answer(f"Товар добавлен в категорию «{category}». ID: {item_id}.")

    @router.message(Command("addjob"))
    async def add_job(message: Message) -> None:
        if not await require_admin(message):
            return
        fields = argument(message).split("|")
        if len(fields) not in {2, 3}:
            await message.answer("Формат: /addjob Название | Зарплата | civil или government")
            return
        category = fields[2].strip().lower() if len(fields) == 3 else "civil"
        if category in {"gov", "гос", "государственная"}:
            category = "government"
        if category in {"гражданская", "обычная"}:
            category = "civil"
        try:
            job_id = database.add_job(
                fields[0].strip(),
                int(fields[1].strip()),
                category,
            )
        except (ValueError, sqlite3.IntegrityError):
            await message.answer("Не удалось добавить работу. Проверьте зарплату и название.")
            return
        database.audit_admin(message.from_user.id, "job_add", details=f"job:{job_id}")
        await message.answer(f"Работа добавлена в SQLite. ID: {job_id}.")

    @router.message(Command("setsalary"))
    async def set_salary(message: Message) -> None:
        if not await require_admin(message):
            return
        fields = argument(message).rsplit("|", maxsplit=1)
        if len(fields) != 2:
            await message.answer("Формат: /setsalary Название работы | Зарплата")
            return
        job = database.get_job_by_name(fields[0].strip())
        try:
            salary = int(fields[1].strip())
        except ValueError:
            salary = -1
        if not job or salary < 0 or not database.set_job_salary(job["id"], salary):
            await message.answer("Работа не найдена или зарплата указана неверно.")
            return
        database.audit_admin(
            message.from_user.id,
            "job_salary",
            details=f"{job['name']}:{salary}",
        )
        await message.answer(f"Зарплата работы «{job['name']}» установлена: {money(salary)}.")

    @router.message(Command("deletejob"))
    async def delete_job(message: Message) -> None:
        if not await require_admin(message):
            return
        try:
            job_id = int(argument(message))
        except ValueError:
            await message.answer("Формат: /deletejob ID_работы")
            return
        if not database.deactivate_job(job_id, message.from_user.id):
            await message.answer("Активная работа с таким ID не найдена.")
            return
        await message.answer(
            "Работа отключена. Назначения сняты, ожидающие заявки отклонены."
        )

    @router.message(Command("editprice"))
    async def edit_price(message: Message) -> None:
        if not await require_admin(message):
            return
        parts = argument(message).split()
        if len(parts) != 3:
            await message.answer("Формат: /editprice car|business|property|item ID Цена")
            return
        kind, item_id_text, price_text = parts
        try:
            item_id, price = int(item_id_text), int(price_text)
        except ValueError:
            item_id, price = 0, -1
        if not database.edit_catalog_price(kind.lower(), item_id, price):
            await message.answer("Запись не найдена или цена указана неверно.")
            return
        database.audit_admin(
            message.from_user.id, "catalog_price", details=f"{kind}:{item_id}:{price}"
        )
        await message.answer(f"Цена обновлена: {KIND_NAMES.get(kind, kind)} #{item_id}.")

    @router.message(Command("deletecatalog"))
    async def delete_catalog(message: Message) -> None:
        if not await require_admin(message):
            return
        parts = argument(message).split()
        if len(parts) != 2 or not parts[1].isdigit():
            await message.answer("Формат: /deletecatalog car|business|property|item ID")
            return
        kind, item_id = parts[0].lower(), int(parts[1])
        if not database.deactivate_catalog_item(kind, item_id):
            await message.answer("Запись не найдена.")
            return
        database.audit_admin(
            message.from_user.id, "catalog_delete", details=f"{kind}:{item_id}"
        )
        await message.answer("Запись скрыта из каталога. История покупок сохранена.")

    @router.message(Command("listcatalog"))
    async def list_catalog(message: Message) -> None:
        if not await require_admin(message):
            return
        kind = argument(message).lower()
        if kind not in KIND_NAMES:
            await message.answer("Укажите тип: car, business, property или item.")
            return
        items = database.list_catalog(kind, limit=60)
        await message.answer(
            f"Каталог «{kind}» (первые {len(items)} записей):\n"
            + ("\n".join(f"#{item['id']} {item['name']} — {money(item['price'])}" for item in items)
               or "Каталог пуст.")
        )

    async def adjust_money(message: Message, action: str) -> None:
        if not await require_admin(message):
            return
        parts = argument(message).split()
        if len(parts) != 2:
            await message.answer(f"Формат: /{action} Telegram_ID Сумма")
            return
        try:
            target_id, amount = int(parts[0]), int(parts[1])
        except ValueError:
            await message.answer("Telegram ID и сумма должны быть целыми числами.")
            return
        ok, result = database.adjust_balance(
            target_id,
            amount,
            "give" if action == "givemoney" else "take",
            message.from_user.id,
        )
        if not ok:
            response = {
                "invalid": "Сумма должна быть больше нуля.",
                "not_found": "Игрок не найден.",
                "insufficient": "У игрока недостаточно средств.",
            }.get(str(result), "Не удалось изменить баланс.")
            await message.answer(response)
            return
        await message.answer(f"Баланс игрока {target_id}: {money(int(result))}.")

    @router.message(Command("givemoney"))
    async def give_money(message: Message) -> None:
        await adjust_money(message, "givemoney")

    @router.message(Command("takemoney"))
    async def take_money(message: Message) -> None:
        await adjust_money(message, "takemoney")

    @router.message(Command("setjob"))
    async def set_job(message: Message) -> None:
        if not await require_admin(message):
            return
        fields = argument(message).split("|", maxsplit=1)
        if len(fields) != 2:
            await message.answer("Формат: /setjob Telegram_ID | Название работы")
            return
        try:
            target_id = int(fields[0].strip())
        except ValueError:
            await message.answer("Telegram ID должен быть числом.")
            return
        job = database.get_job_by_name(fields[1].strip())
        if not job or not database.assign_job(target_id, job["name"]):
            await message.answer("Работа или игрок не найдены.")
            return
        database.audit_admin(
            message.from_user.id, "job_assign", target_id, job["name"]
        )
        await message.answer(f"Игроку {target_id} назначена работа «{job['name']}».")

    @router.message(Command("removejob"))
    async def remove_job(message: Message) -> None:
        if not await require_admin(message):
            return
        try:
            target_id = int(argument(message))
        except ValueError:
            await message.answer("Формат: /removejob Telegram_ID")
            return
        if not database.assign_job(target_id, None):
            await message.answer("Игрок не найден.")
            return
        database.audit_admin(message.from_user.id, "job_remove", target_id)
        await message.answer(f"Работа игрока {target_id} снята.")

    async def set_ban(message: Message, banned: bool) -> None:
        if not await require_admin(message):
            return
        try:
            target_id = int(argument(message))
        except ValueError:
            await message.answer("Укажите Telegram ID игрока.")
            return
        if not database.set_banned(target_id, banned, message.from_user.id):
            await message.answer("Игрок не найден.")
            return
        await message.answer(
            f"Игрок {target_id} заблокирован."
            if banned
            else f"Игрок {target_id} разблокирован."
        )

    @router.message(Command("ban"))
    async def ban(message: Message) -> None:
        await set_ban(message, True)

    @router.message(Command("unban"))
    async def unban(message: Message) -> None:
        await set_ban(message, False)

    @router.message(Command("applications"))
    async def applications(message: Message) -> None:
        if not await require_admin(message):
            return
        entries = database.list_applications()
        if not entries:
            await message.answer("Ожидающих заявок нет.")
            return
        lines = ["Заявки на рассмотрении:"]
        for item in entries:
            target = item["job_name"] if item["kind"] == "job" else item["organization_name"]
            lines.append(
                f"#{item['id']} · {item['kind']} · {item['game_name']} "
                f"(ID {item['player_id']}) → {target}"
            )
        lines.append("\nРешение: /approve ID или /reject ID Причина")
        await message.answer("\n".join(lines))

    async def review(message: Message, approve: bool) -> None:
        if not await require_admin(message):
            return
        parts = argument(message).split(maxsplit=1)
        if not parts or not parts[0].isdigit():
            await message.answer("Укажите ID заявки.")
            return
        note = parts[1] if len(parts) > 1 else ""
        application = database.review_application(
            int(parts[0]),
            approve,
            message.from_user.id,
            note,
        )
        if not application:
            await message.answer("Ожидающая заявка с таким ID не найдена.")
            return
        decision = "одобрена" if approve else "отклонена"
        target = application["job_name"] or application["organization_name"] or ""
        await message.answer(f"Заявка #{application['id']} {decision}.")
        try:
            await message.bot.send_message(
                application["player_id"],
                f"Ваша заявка на «{target}» {decision}."
                + (f"\nКомментарий: {note[:500]}" if note and not approve else ""),
            )
        except Exception:
            pass

    @router.message(Command("approve"))
    async def approve(message: Message) -> None:
        await review(message, True)

    @router.message(Command("reject"))
    async def reject(message: Message) -> None:
        await review(message, False)

    @router.message(Command("orgcreate"))
    async def create_organization(message: Message) -> None:
        if not await require_admin(message):
            return
        fields = argument(message).split("|", maxsplit=1)
        if len(fields) != 2:
            await message.answer("Формат: /orgcreate Название | Telegram_ID лидера")
            return
        try:
            leader_id = int(fields[1].strip())
            organization_id = database.create_organization(
                fields[0].strip(), leader_id, message.from_user.id
            )
        except ValueError as exc:
            await message.answer(str(exc))
            return
        except sqlite3.IntegrityError:
            await message.answer("Организация с таким названием уже есть.")
            return
        await message.answer(f"Организация создана. ID: {organization_id}.")

    @router.message(Command("orgleader"))
    async def set_organization_leader(message: Message) -> None:
        if not await require_admin(message):
            return
        parts = argument(message).split()
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            await message.answer("Формат: /orgleader ID_организации Telegram_ID")
            return
        organization_id, leader_id = map(int, parts)
        if not database.set_organization_leader(
            organization_id, leader_id, message.from_user.id
        ):
            await message.answer("Организация или игрок не найдены.")
            return
        await message.answer(f"Руководитель организации #{organization_id} назначен.")

    @router.message(Command("stats"))
    async def stats(message: Message) -> None:
        if not await require_admin(message):
            return
        result = database.stats()
        await message.answer(
            "Статистика сервера:\n"
            f"Игроки: {result['players']} · заблокированы: {result['banned']}\n"
            f"Автомобили: {result['cars']} · бизнесы: {result['businesses']} "
            f"· недвижимость: {result['properties']}\n"
            f"Работы: {result['jobs']} · организации: {result['organizations']}\n"
            f"Заявки ожидают решения: {result['pending_applications']}"
        )

    @router.message(Command("adminadd"))
    async def add_admin(message: Message) -> None:
        if not database.is_owner(message.from_user.id, settings.owner_ids):
            await message.answer("Добавлять администраторов может только владелец.")
            return
        try:
            target_id = int(argument(message))
        except ValueError:
            await message.answer("Формат: /adminadd Telegram_ID")
            return
        database.add_admin(target_id, message.from_user.id)
        await message.answer(f"Права администратора выданы ID {target_id}.")

    @router.message(Command("adminremove"))
    async def remove_admin(message: Message) -> None:
        if not database.is_owner(message.from_user.id, settings.owner_ids):
            await message.answer("Снимать права администратора может только владелец.")
            return
        try:
            target_id = int(argument(message))
        except ValueError:
            await message.answer("Формат: /adminremove Telegram_ID")
            return
        if target_id in all_admin_ids:
            await message.answer(
                "Этот ID задан через ADMIN_IDS/OWNER_IDS. Удалите его из переменных окружения."
            )
            return
        removed = database.remove_admin(target_id, message.from_user.id)
        await message.answer(
            f"Права администратора сняты у ID {target_id}."
            if removed
            else "Этот ID не найден в списке администраторов."
        )

    return router
