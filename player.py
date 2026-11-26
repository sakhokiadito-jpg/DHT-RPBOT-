from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config import Settings
from database import Database
from keyboards.menu import player_menu
from services.formatting import money


def build_player_router(database: Database, settings: Settings) -> Router:
    router = Router(name="players")

    def command_argument(message: Message) -> str:
        return (message.text or "").partition(" ")[2].strip()

    @router.message(Command("start", "register"))
    async def start(message: Message) -> None:
        argument = command_argument(message)
        if not argument:
            player = database.get_player(message.from_user.id)
            if player:
                await message.answer("Вы уже зарегистрированы. Откройте /profile или /help.")
            else:
                await message.answer(
                    "Добро пожаловать в DHT ROLEPLAY.\n"
                    "Для регистрации отправьте:\n"
                    "/start Игровой ник | CPM ID\n"
                    "Пример: /start Alex Stone | 12345678"
                )
            return
        if "|" not in argument:
            await message.answer("Формат регистрации: /start Игровой ник | CPM ID")
            return
        game_name, cpm_id = (part.strip() for part in argument.split("|", maxsplit=1))
        if not 2 <= len(game_name) <= 80:
            await message.answer("Игровой ник должен содержать от 2 до 80 символов.")
            return
        if not 1 <= len(cpm_id) <= 32 or not cpm_id.isdigit():
            await message.answer("CPM ID должен содержать от 1 до 32 цифр.")
            return
        player = database.create_player(
            telegram_id=message.from_user.id,
            username=message.from_user.username or message.from_user.full_name,
            game_name=game_name,
            cpm_id=cpm_id,
            start_balance=settings.start_balance,
        )
        if player["_created"]:
            await message.answer(
                f"Регистрация завершена, {game_name}.\n"
                f"Стартовый баланс: {money(settings.start_balance)}\n"
                "Команды: /profile и /help.",
                reply_markup=player_menu(),
            )
        else:
            await message.answer("Вы уже зарегистрированы. Откройте /profile.")

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        await message.answer(
            "Команды DHT ROLEPLAY\n\n"
            "Игрокам:\n"
            "/start Ник | CPM_ID — регистрация\n"
            "/profile — профиль и имущество\n"
            "/balance — баланс\n"
            "/top — рейтинг игроков\n"
            "/jobs — список работ\n"
            "/applyjob Название — заявка на работу\n"
            "/myjob — текущая работа\n"
            "/work — получить зарплату с ограничением по времени\n"
            "/orgs — организации\n"
            "/joinorg Название — заявка в организацию\n"
            "/myorg — мои организации\n"
            "/cars, /businesses, /properties — каталоги\n"
            "/items [категория] — каталог товаров\n"
            "/buycar ID, /buybusiness ID, /buyproperty ID, /buyitem ID — покупка\n"
            "/mycars, /mybusinesses, /myproperties, /inventory — имущество\n"
            "/collect — доход принадлежащих бизнесов\n"
            "/pay Telegram_ID Сумма — перевод игроку\n\n"
            "Администраторам: /adminhelp",
            reply_markup=player_menu(),
        )

    @router.callback_query(F.data.startswith("menu:"))
    async def menu_action(callback: CallbackQuery) -> None:
        action = (callback.data or "").partition(":")[2]
        if action == "profile":
            player = database.get_player(callback.from_user.id)
            if not player:
                await callback.answer("Сначала зарегистрируйтесь командой /start", show_alert=True)
                return
            await callback.message.answer(await profile_text(database, player))
        elif action == "balance":
            player = database.get_player(callback.from_user.id)
            if not player:
                await callback.answer("Сначала зарегистрируйтесь командой /start", show_alert=True)
                return
            await callback.message.answer(f"Баланс: {money(player['balance'])}")
        elif action == "jobs":
            jobs = database.list_jobs("civil")
            await callback.message.answer(
                "\n".join(f"{job['name']} — {money(job['salary'])}" for job in jobs[:25])
                or "Пока нет доступных работ."
            )
        elif action == "catalog":
            await callback.message.answer("Каталоги: /cars, /businesses, /properties, /items")
        await callback.answer()

    @router.message(Command("profile"))
    async def profile(message: Message) -> None:
        player = database.get_player(message.from_user.id)
        if not player:
            await message.answer("Сначала зарегистрируйтесь командой /start.")
            return
        await message.answer(await profile_text(database, player))

    @router.message(Command("balance"))
    async def balance(message: Message) -> None:
        player = database.get_player(message.from_user.id)
        if not player:
            await message.answer("Сначала зарегистрируйтесь командой /start.")
            return
        await message.answer(f"Баланс: {money(player['balance'])}")

    @router.message(Command("top"))
    async def top(message: Message) -> None:
        leaders = database.top_players(10)
        if not leaders:
            await message.answer("Рейтинг пока пуст.")
            return
        lines = ["Рейтинг игроков по балансу:"]
        for index, player in enumerate(leaders, start=1):
            lines.append(
                f"{index}. {player['game_name']} — {money(player['balance'])} "
                f"(уровень {player['level']})"
            )
        await message.answer("\n".join(lines))

    @router.message(Command("jobs"))
    async def jobs(message: Message) -> None:
        jobs_list = database.list_jobs()
        if not jobs_list:
            await message.answer("Список работ пока пуст.")
            return
        try:
            page = max(1, int(command_argument(message) or "1"))
        except ValueError:
            page = 1
        page_size = 20
        total_pages = max(1, (len(jobs_list) + page_size - 1) // page_size)
        page = min(page, total_pages)
        selected = jobs_list[(page - 1) * page_size : page * page_size]
        lines = [f"Работы, страница {page}/{total_pages}:"]
        for job in selected:
            category = "госслужба" if job["category"] == "government" else "гражданская"
            lines.append(f"#{job['id']} {job['name']} — {money(job['salary'])} ({category})")
        lines.append("\nПодать заявку: /applyjob Название работы")
        await message.answer("\n".join(lines))

    @router.message(Command("applyjob"))
    async def apply_job(message: Message) -> None:
        name = command_argument(message)
        if not name:
            await message.answer("Укажите работу: /applyjob Название работы")
            return
        job = database.get_job_by_name(name)
        if not job:
            await message.answer("Работа не найдена. Посмотрите доступные варианты через /jobs.")
            return
        ok, result = database.create_application(
            message.from_user.id,
            "job",
            job_id=job["id"],
        )
        if not ok:
            messages = {
                "not_registered": "Сначала зарегистрируйтесь командой /start.",
                "banned": "Для вашего аккаунта закрыты игровые действия.",
                "pending": "У вас уже есть ожидающая заявка на эту работу.",
                "not_found": "Работа больше не доступна.",
            }
            await message.answer(messages.get(str(result), "Не удалось создать заявку."))
            return
        await message.answer(f"Заявка №{result} на работу «{job['name']}» отправлена администрации.")

    @router.message(Command("myjob"))
    async def my_job(message: Message) -> None:
        player = database.get_player(message.from_user.id)
        if not player:
            await message.answer("Сначала зарегистрируйтесь командой /start.")
        elif player["job_name"]:
            await message.answer(
                f"Работа: {player['job_name']}\nЗарплата за смену: {money(player['job_salary'])}"
            )
        else:
            await message.answer("У вас пока нет работы. Посмотрите /jobs.")

    @router.message(Command("work"))
    async def work(message: Message) -> None:
        result = database.work(
            message.from_user.id,
            settings.work_cooldown_seconds,
        )
        if result["ok"]:
            await message.answer(
                f"Смена завершена: +{money(result['salary'])}\n"
                f"Работа: {result['job']}\n"
                f"Баланс: {money(result['balance'])}\n"
                f"Опыт: {result['experience']} · уровень {result['level']}"
            )
            return
        if result["reason"] == "cooldown":
            minutes, seconds = divmod(result["remaining"], 60)
            await message.answer(f"Следующая смена доступна через {minutes} мин. {seconds} сек.")
        else:
            messages = {
                "not_registered": "Сначала зарегистрируйтесь командой /start.",
                "banned": "Для вашего аккаунта закрыты игровые действия.",
                "no_job": "Сначала получите работу через /applyjob.",
            }
            await message.answer(messages.get(result["reason"], "Не удалось выполнить работу."))

    @router.message(Command("pay"))
    async def pay(message: Message) -> None:
        parts = command_argument(message).split()
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            await message.answer("Формат: /pay Telegram_ID Сумма")
            return
        recipient_id, amount = map(int, parts)
        ok, reason = database.transfer(message.from_user.id, recipient_id, amount)
        messages = {
            "invalid": "Проверьте сумму. Нельзя переводить себе или отправлять ноль.",
            "not_found": "Оба игрока должны быть зарегистрированы.",
            "banned": "Переводы для заблокированного аккаунта недоступны.",
            "insufficient": "Недостаточно средств.",
        }
        await message.answer(
            f"Перевод {money(amount)} игроку {recipient_id} выполнен."
            if ok
            else messages.get(reason, "Не удалось выполнить перевод.")
        )

    @router.message(Command("mycars"))
    async def my_cars(message: Message) -> None:
        await send_assets(message, database, "car", "Ваши автомобили")

    @router.message(Command("mybusinesses"))
    async def my_businesses(message: Message) -> None:
        await send_assets(message, database, "business", "Ваши бизнесы")

    @router.message(Command("myproperties"))
    async def my_properties(message: Message) -> None:
        await send_assets(message, database, "property", "Ваша недвижимость")

    @router.message(Command("inventory"))
    async def inventory(message: Message) -> None:
        items = database.list_inventory(message.from_user.id)
        if not items:
            await message.answer("Инвентарь пуст.")
            return
        await message.answer(
            "Инвентарь:\n"
            + "\n".join(
                f"• {item['name']} × {item['quantity']} — {item['category'] or 'Без категории'}"
                for item in items
            )
        )

    @router.message(Command("collect"))
    async def collect(message: Message) -> None:
        ok, amount, count = database.collect_business_income(
            message.from_user.id,
            settings.business_payout_seconds,
        )
        if not ok and amount == -1:
            await message.answer("Для вашего аккаунта закрыты игровые действия.")
        elif not ok:
            await message.answer("Сначала зарегистрируйтесь командой /start.")
        elif amount:
            await message.answer(f"Получен доход от {count} бизнесов: {money(amount)}.")
        else:
            await message.answer(
                "Пока нет доступного дохода. Бизнес приносит прибыль раз в "
                f"{max(1, settings.business_payout_seconds // 3600)} ч."
            )

    return router


async def profile_text(database: Database, player: dict) -> str:
    assets = database.list_owned_assets(player["telegram_id"])
    orgs = database.get_player_organizations(player["telegram_id"])
    counts = {
        kind: sum(1 for asset in assets if asset["kind"] == kind)
        for kind in ("car", "property", "business")
    }
    org_text = ", ".join(f"{org['name']} ({org['rank']})" for org in orgs) or "нет"
    return (
        f"Профиль: {player['game_name']}\n"
        f"Telegram ID: {player['telegram_id']}\n"
        f"CPM ID: {player['cpm_id'] or 'не указан'}\n"
        f"Баланс: {money(player['balance'])}\n"
        f"Уровень: {player['level']} · опыт {player['experience']}\n"
        f"Работа: {player['job_name'] or 'нет'}\n"
        f"Организации: {org_text}\n"
        f"Автомобили: {counts['car']} · недвижимость: {counts['property']} "
        f"· бизнесы: {counts['business']}"
    )


async def send_assets(message: Message, database: Database, kind: str, heading: str) -> None:
    assets = database.list_owned_assets(message.from_user.id, kind)
    if not assets:
        await message.answer(f"{heading}: пока нет.")
        return
    lines = [heading + ":"]
    for asset in assets[:50]:
        extra = f" · {asset['power']} л.с." if asset["kind"] == "car" and asset["power"] else ""
        if asset["kind"] == "business":
            extra = f" · доход {money(asset['income'])} за период"
        lines.append(f"• {asset['name']}{extra}")
    await message.answer("\n".join(lines))
