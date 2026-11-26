from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config import Settings
from database import Database
from services.formatting import money, parse_positive_int


def build_catalog_router(database: Database, settings: Settings) -> Router:
    router = Router(name="catalog")

    async def show_catalog(message: Message, kind: str, title: str, category: str | None = None) -> None:
        items = database.list_catalog(kind, category, limit=40)
        if not items:
            suffix = f" в категории «{category}»" if category else ""
            await message.answer(f"В каталоге пока нет записей{suffix}.")
            return
        lines = [title + (f" · {category}" if category else "") + ":"]
        for item in items:
            detail = ""
            if kind == "car" and item["power"] is not None:
                detail = f" · {item['power']} л.с."
            elif kind == "business":
                detail = f" · доход {money(item['income'])} за период"
            lines.append(
                f"#{item['id']} {item['name']} — {money(item['price'])}{detail}"
            )
            if item["description"]:
                lines.append(f"  {item['description'][:160]}")
        lines.append("\nПокупка доступна командами /buycar, /buybusiness, /buyproperty или /buyitem.")
        text = "\n".join(lines)
        chunks: list[str] = []
        current = ""
        for line in text.splitlines():
            if len(current) + len(line) + 1 > 3500:
                chunks.append(current)
                current = ""
            current += ("\n" if current else "") + line
        if current:
            chunks.append(current)
        for chunk in chunks:
            await message.answer(chunk)

    @router.message(Command("cars"))
    async def cars(message: Message) -> None:
        await show_catalog(message, "car", "Автомобили")

    @router.message(Command("businesses"))
    async def businesses(message: Message) -> None:
        await show_catalog(message, "business", "Бизнесы")

    @router.message(Command("properties"))
    async def properties(message: Message) -> None:
        await show_catalog(message, "property", "Недвижимость")

    @router.message(Command("items"))
    async def items(message: Message) -> None:
        category = (message.text or "").partition(" ")[2].strip() or None
        if category:
            await show_catalog(message, "item", "Товары", category)
            return
        categories = database.categories()
        if categories:
            await message.answer(
                "Категории товаров:\n"
                + "\n".join(f"• {name}" for name in categories)
                + "\n\nЧтобы открыть категорию: /items Название категории"
            )
        else:
            await message.answer("Категорий товаров пока нет.")

    async def buy(message: Message, kind: str) -> None:
        raw_id = (message.text or "").partition(" ")[2].strip()
        try:
            item_id = parse_positive_int(raw_id, "ID товара")
        except ValueError as exc:
            await message.answer(f"{exc}\nФормат: /buy{kind} ID")
            return
        ok, result, amount = database.purchase(message.from_user.id, item_id, kind)
        if ok:
            await message.answer(f"Покупка «{result}» завершена. Списано {money(amount or 0)}.")
            return
        messages = {
            "not_registered": "Сначала зарегистрируйтесь командой /start.",
            "banned": "Для вашего аккаунта закрыты игровые действия.",
            "not_found": "Запись не найдена или больше не продаётся.",
            "insufficient": f"Недостаточно средств. Цена: {money(amount or 0)}.",
            "invalid_kind": "Неизвестный тип товара.",
        }
        await message.answer(messages.get(result, "Не удалось выполнить покупку."))

    @router.message(Command("buycar"))
    async def buy_car(message: Message) -> None:
        await buy(message, "car")

    @router.message(Command("buybusiness"))
    async def buy_business(message: Message) -> None:
        await buy(message, "business")

    @router.message(Command("buyproperty"))
    async def buy_property(message: Message) -> None:
        await buy(message, "property")

    @router.message(Command("buyitem"))
    async def buy_item(message: Message) -> None:
        await buy(message, "item")

    return router
