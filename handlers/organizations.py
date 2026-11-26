from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from database import Database


def build_organization_router(database: Database) -> Router:
    router = Router(name="organizations")

    @router.message(Command("orgs"))
    async def organizations(message: Message) -> None:
        entries = database.list_organizations()
        if not entries:
            await message.answer("Организаций пока нет.")
            return
        lines = ["Организации:"]
        for org in entries[:40]:
            leader = (
                f" · руководитель @{org['leader_username']}"
                if org["leader_username"]
                else ""
            )
            lines.append(
                f"#{org['id']} {org['name']} · участников {org['member_count']}{leader}"
            )
        lines.append("\nПодать заявку: /joinorg Название организации")
        await message.answer("\n".join(lines))

    @router.message(Command("joinorg"))
    async def join_organization(message: Message) -> None:
        name = (message.text or "").partition(" ")[2].strip()
        if not name:
            await message.answer("Формат: /joinorg Название организации")
            return
        org = database.find_organization(name)
        if not org:
            await message.answer("Организация не найдена. Посмотрите список через /orgs.")
            return
        ok, result = database.create_application(
            message.from_user.id,
            "organization",
            organization_id=org["id"],
        )
        if not ok:
            messages = {
                "not_registered": "Сначала зарегистрируйтесь командой /start.",
                "banned": "Для вашего аккаунта закрыты игровые действия.",
                "already_member": "Вы уже состоите в этой организации.",
                "pending": "Ваша заявка уже ожидает рассмотрения.",
                "not_found": "Организация больше не существует.",
            }
            await message.answer(messages.get(str(result), "Не удалось отправить заявку."))
            return
        await message.answer(
            f"Заявка №{result} на вступление в «{org['name']}» отправлена администрации."
        )

    @router.message(Command("myorg"))
    async def my_organizations(message: Message) -> None:
        entries = database.get_player_organizations(message.from_user.id)
        if not entries:
            await message.answer("Вы пока не состоите в организациях.")
            return
        await message.answer(
            "Ваши организации:\n"
            + "\n".join(
                f"• {org['name']} — {org['rank']} (ID {org['id']})"
                for org in entries
            )
        )

    @router.message(Command("orgfire"))
    async def remove_member(message: Message) -> None:
        parts = (message.text or "").partition(" ")[2].split(maxsplit=1)
        if len(parts) != 2 or not parts[0].isdigit():
            await message.answer("Формат: /orgfire ID_организации Telegram_ID_игрока")
            return
        organization_id, player_id = int(parts[0]), _extract_id(parts[1])
        if player_id is None:
            await message.answer("Telegram ID игрока должен быть числом.")
            return
        admin = database.is_admin(message.from_user.id)
        ok, reason = database.remove_organization_member(
            organization_id,
            player_id,
            message.from_user.id,
            admin,
        )
        responses = {
            "organization_not_found": "Организация не найдена.",
            "forbidden": "Управлять участниками может лидер организации или администратор.",
            "leader_protected": "Лидер не может исключить самого себя этой командой.",
            "member_not_found": "Указанный игрок не состоит в организации.",
        }
        await message.answer(
            "Игрок исключён из организации."
            if ok
            else responses.get(reason, "Не удалось изменить состав.")
        )

    @router.message(Command("orgrank"))
    async def set_rank(message: Message) -> None:
        parts = (message.text or "").partition(" ")[2].split(maxsplit=2)
        if len(parts) != 3 or not parts[0].isdigit():
            await message.answer("Формат: /orgrank ID_организации Telegram_ID_игрока Ранг")
            return
        organization_id, player_id = int(parts[0]), _extract_id(parts[1])
        rank = parts[2].strip().lstrip("|").strip()
        if player_id is None or not rank or len(rank) > 60:
            await message.answer("Укажите числовой Telegram ID и ранг длиной до 60 символов.")
            return
        ok, reason = database.set_member_rank(
            organization_id,
            player_id,
            rank,
            message.from_user.id,
            database.is_admin(message.from_user.id),
        )
        responses = {
            "organization_not_found": "Организация не найдена.",
            "forbidden": "Назначать ранги может лидер организации или администратор.",
            "member_not_found": "Указанный игрок не состоит в организации.",
        }
        await message.answer(
            f"Ранг обновлён: {rank}."
            if ok
            else responses.get(reason, "Не удалось назначить ранг.")
        )

    return router


def _extract_id(value: str) -> int | None:
    raw = value.strip().lstrip("@")
    try:
        return int(raw)
    except ValueError:
        return None
