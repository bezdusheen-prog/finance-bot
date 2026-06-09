import asyncio
import logging
import os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from dotenv import load_dotenv


load_dotenv()

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set")

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()


DEFAULT_BUDGET_DISTRIBUTION = {
    "Коммуналка": 15,
    "Аренда": 25,
    "Кредиты": 10,
    "Здоровье": 5,
    "Одежда": 3,
    "Образование": 3,
    "Подарки": 2,
    "Другое": 2,
}

user_data = {}


class AddOperation(StatesGroup):
    waiting_amount = State()
    waiting_category = State()
    waiting_comment = State()


class SetSalary(StatesGroup):
    waiting_salary = State()


class EditDistribution(StatesGroup):
    waiting_category = State()
    waiting_new_percent = State()


class AddCategory(StatesGroup):
    waiting_category_name = State()
    waiting_category_percent = State()


class ManageFund(StatesGroup):
    waiting_fund_name = State()
    waiting_amount = State()


def ensure_user(user_id: int):
    if user_id not in user_data:
        user_data[user_id] = {
            "balance": 0.0,
            "salary": 0.0,
            "budget": {},
            "operations": [],
            "categories": list(DEFAULT_BUDGET_DISTRIBUTION.keys()),
            "accounts": ["Наличные", "Карта"],
            "funds": {},
        }


def calculate_budget(salary: float) -> dict:
    budget = {}
    for category, percent in DEFAULT_BUDGET_DISTRIBUTION.items():
        budget[category] = round(salary * percent / 100, 2)
    return budget


def get_spending_tip(remaining: float, category_budget: float) -> str:
    if category_budget == 0:
        return ""

    percent_left = (remaining / category_budget) * 100
    tips = [
        ("Великолепно! Осталось {:.0f}% бюджета 🎉", 75, 101),
        ("Отлично! Осталось {:.0f}% бюджета 😊", 50, 75),
        ("Неплохо, но лучше сэкономить. Осталось {:.0f}% 👀", 25, 50),
        ("Внимание! Бюджет почти исчерпан: {:.0f}% ⚠️", 0, 25),
        ("Бюджет превышен! 😱", -100000, 0),
    ]

    for tip_text, min_p, max_p in tips:
        if min_p <= percent_left < max_p:
            if "{}" in tip_text:
                return tip_text.format(percent_left)
            return tip_text

    return ""


@router.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    ensure_user(user_id)

    await message.answer(
        f"👋 Добро пожаловать, {message.from_user.first_name}!\n\n"
        "💰 Финансовый помощник с бюджетированием.\n\n"
        "Основные команды:\n"
        "/salary - Установить зарплату и бюджет\n"
        "/addincome - Добавить доход\n"
        "/addexpense - Добавить расход\n"
        "/balance - Баланс и бюджет\n"
        "/tips - Напутствия по тратам\n"
        "/history - История\n"
        "/help - Полная справка"
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📚 Помощник по финансам\n\n"
        "/salary - Установить зарплату и автоматически рассчитать бюджет на месяц\n"
        "/addincome - Добавить доход\n"
        "/addexpense - Добавить расход\n"
        "/balance - Текущий баланс и остатки бюджета\n"
        "/tips - Получить напутствия по тратам\n"
        "/editdistribution - Редактировать распределение бюджета\n"
        "/addcategory - Добавить новую категорию\n"
        "/today - Отчёт за сегодня\n"
        "/week - Отчёт за 7 дней\n"
        "/month - Отчёт за 30 дней\n"
        "/history - История операций\n"
        "/categories - Список категорий\n"
        "/accounts - Счета\n"
        "/funds - Просмотр фондов\n"
        "/createfund - Создать фонд\n"
        "/addfund - Пополнить фонд\n"
        "/withdrawfund - Снять с фонда\n"
        "/settings - Настройки"
    )


@router.message(Command("salary"))
async def cmd_salary(message: Message, state: FSMContext):
    await state.set_state(SetSalary.waiting_salary)
    await message.answer("💵 Введите вашу зарплату в рублях:")


@router.message(SetSalary.waiting_salary)
async def process_salary(message: Message, state: FSMContext):
    try:
        salary = float(message.text.replace(",", ".").replace(" ", ""))
        if salary <= 0:
            await message.answer("❌ Зарплата должна быть больше нуля.")
            return

        user_id = message.from_user.id
        ensure_user(user_id)

        budget = calculate_budget(salary)
        user_data[user_id]["salary"] = salary
        user_data[user_id]["budget"] = budget

        text = f"✅ Зарплата установлена: {salary:.2f} ₽\n\n📊 Бюджет на месяц:\n"
        for cat, amount in budget.items():
            text += f"• {cat}: {amount:.2f} ₽\n"

        await message.answer(text)
        await state.clear()

    except ValueError:
        await message.answer("❌ Неверный формат. Введите число.")


@router.message(Command("editdistribution"))
async def cmd_editdistribution(message: Message, state: FSMContext):
    user_id = message.from_user.id
    ensure_user(user_id)

    if not user_data[user_id].get("budget"):
        await message.answer("⚠️ Сначала установите зарплату с помощью /salary")
        return

    categories_list = "\n".join(
        [
            f"{i + 1}. {cat}: {percent}%"
            for i, (cat, percent) in enumerate(DEFAULT_BUDGET_DISTRIBUTION.items())
        ]
    )
    await message.answer(
        f"📊 Текущее распределение:\n{categories_list}\n\n"
        "Выберите номер категории для редактирования:"
    )
    await state.set_state(EditDistribution.waiting_category)


@router.message(EditDistribution.waiting_category)
async def process_edit_category(message: Message, state: FSMContext):
    try:
        category_num = int(message.text)
        categories = list(DEFAULT_BUDGET_DISTRIBUTION.keys())

        if category_num < 1 or category_num > len(categories):
            await message.answer("❌ Неверный номер категории")
            return

        selected_category = categories[category_num - 1]
        current_percent = DEFAULT_BUDGET_DISTRIBUTION[selected_category]

        await state.update_data(selected_category=selected_category)
        await message.answer(
            f"✏️ Категория: {selected_category}\n"
            f"Текущий %: {current_percent}%\n\n"
            "Введите новый процент:"
        )
        await state.set_state(EditDistribution.waiting_new_percent)

    except ValueError:
        await message.answer("❌ Введите число")


@router.message(EditDistribution.waiting_new_percent)
async def process_new_percent(message: Message, state: FSMContext):
    try:
        new_percent = int(message.text.replace(",", ".").replace(" ", ""))
        if new_percent < 0 or new_percent > 100:
            await message.answer("❌ Процент должен быть от 0 до 100")
            return

        data = await state.get_data()
        selected_category = data.get("selected_category")

        if not selected_category:
            await message.answer("❌ Категория не выбрана")
            await state.clear()
            return

        DEFAULT_BUDGET_DISTRIBUTION[selected_category] = new_percent
        total = sum(DEFAULT_BUDGET_DISTRIBUTION.values())

        await message.answer(
            f"✅ Категория {selected_category} обновлена до {new_percent}%\n"
            f"Сумма всех процентов: {total}%"
        )
        await state.clear()

    except ValueError:
        await message.answer("❌ Введите число")


@router.message(Command("addcategory"))
async def cmd_addcategory(message: Message, state: FSMContext):
    await message.answer("🆕 Введите название новой категории:")
    await state.set_state(AddCategory.waiting_category_name)


@router.message(AddCategory.waiting_category_name)
async def process_category_name(message: Message, state: FSMContext):
    category_name = message.text.strip()

    if not category_name:
        await message.answer("❌ Название категории не может быть пустым")
        return

    if category_name in DEFAULT_BUDGET_DISTRIBUTION:
        await message.answer("⚠️ Категория с таким названием уже существует")
        return

    await state.update_data(category_name=category_name)
    await message.answer(
        f"✏️ Категория: {category_name}\n"
        "Введите процент бюджета для этой категории:"
    )
    await state.set_state(AddCategory.waiting_category_percent)


@router.message(AddCategory.waiting_category_percent)
async def process_category_percent(message: Message, state: FSMContext):
    try:
        percent = int(message.text.replace(",", ".").replace(" ", ""))
        if percent < 0 or percent > 100:
            await message.answer("❌ Процент должен быть от 0 до 100")
            return

        data = await state.get_data()
        category_name = data.get("category_name")

        DEFAULT_BUDGET_DISTRIBUTION[category_name] = percent
        total = sum(DEFAULT_BUDGET_DISTRIBUTION.values())

        await message.answer(
            f"✅ Категория '{category_name}' добавлена с {percent}%\n"
            f"Сумма всех процентов: {total}%"
        )
        await state.clear()

    except ValueError:
        await message.answer("❌ Введите число")


@router.message(Command("tips"))
async def cmd_tips(message: Message):
    user_id = message.from_user.id
    ensure_user(user_id)

    if not user_data[user_id].get("budget"):
        await message.answer("⚠️ Сначала установите зарплату с помощью /salary")
        return

    budget = user_data[user_id]["budget"]
    spent_by_category = {}

    for op in user_data[user_id].get("operations", []):
        if op["type"] == "expense":
            cat = op["category"]
            spent_by_category[cat] = spent_by_category.get(cat, 0) + op["amount"]

    text = "💡 Напутствия по тратам:\n\n"
    for cat, budget_amount in budget.items():
        spent = spent_by_category.get(cat, 0)
        remaining = budget_amount - spent
        tip = get_spending_tip(remaining, budget_amount)
        text += f"• {cat}: {remaining:.2f} ₽ / {budget_amount:.2f} ₽\n"
        if tip:
            text += f"  {tip}\n"

    await message.answer(text)


@router.message(Command("addincome"))
async def cmd_addincome(message: Message, state: FSMContext):
    await state.set_state(AddOperation.waiting_amount)
    await state.update_data(operation_type="income")
    await message.answer("💵 Введите сумму дохода:")


@router.message(Command("addexpense"))
async def cmd_addexpense(message: Message, state: FSMContext):
    await state.set_state(AddOperation.waiting_amount)
    await state.update_data(operation_type="expense")
    await message.answer("💸 Введите сумму расхода:")


@router.message(AddOperation.waiting_amount)
async def process_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", ".").replace(" ", ""))
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше нуля")
            return

        await state.update_data(amount=amount)
        await state.set_state(AddOperation.waiting_category)

        user_id = message.from_user.id
        ensure_user(user_id)
        cats = user_data[user_id]["categories"]

        await message.answer(
            f"✅ Сумма: {amount:.2f} ₽\n\n"
            "Введите категорию из списка или свою:\n"
            + "\n".join([f"• {c}" for c in cats])
        )

    except ValueError:
        await message.answer("❌ Неверный формат суммы")


@router.message(AddOperation.waiting_category)
async def process_category(message: Message, state: FSMContext):
    category = message.text.strip()
    if not category:
        await message.answer("❌ Категория не может быть пустой")
        return

    await state.update_data(category=category)
    await state.set_state(AddOperation.waiting_comment)
    await message.answer("📝 Комментарий (или '-' если без комментария):")


@router.message(AddOperation.waiting_comment)
async def process_comment(message: Message, state: FSMContext):
    comment = message.text.strip()
    if comment == "-":
        comment = ""

    data = await state.get_data()
    user_id = message.from_user.id
    ensure_user(user_id)

    operation = {
        "type": data["operation_type"],
        "amount": data["amount"],
        "category": data["category"],
        "comment": comment,
        "date": datetime.now(),
    }

    user_data[user_id]["operations"].append(operation)

    if data["operation_type"] == "income":
        user_data[user_id]["balance"] += data["amount"]
        emoji = "💰"
        op_type = "Доход"
    else:
        user_data[user_id]["balance"] -= data["amount"]
        emoji = "💸"
        op_type = "Расход"

    await message.answer(
        f"{emoji} {op_type} добавлен\n"
        f"Сумма: {data['amount']:.2f} ₽\n"
        f"Категория: {data['category']}\n"
        f"Баланс: {user_data[user_id]['balance']:.2f} ₽"
    )
    await state.clear()


@router.message(Command("balance"))
async def cmd_balance(message: Message):
    user_id = message.from_user.id
    ensure_user(user_id)

    bal = user_data[user_id]["balance"]
    text = f"💰 Баланс: {bal:.2f} ₽\n\n"

    if user_data[user_id].get("budget"):
        text += "📊 Остатки бюджета:\n"
        for cat, budg in user_data[user_id]["budget"].items():
            spent = sum(
                op["amount"]
                for op in user_data[user_id].get("operations", [])
                if op["type"] == "expense" and op["category"] == cat
            )
            text += f"• {cat}: {budg - spent:.2f} / {budg:.2f} ₽\n"

    await message.answer(text)


@router.message(Command("today"))
async def cmd_today(message: Message):
    user_id = message.from_user.id
    ensure_user(user_id)

    if not user_data[user_id]["operations"]:
        await message.answer("📊 Операций нет")
        return

    today = datetime.now().date()
    ops = [o for o in user_data[user_id]["operations"] if o["date"].date() == today]

    if not ops:
        await message.answer("📊 Операций за сегодня нет")
        return

    inc = sum(o["amount"] for o in ops if o["type"] == "income")
    exp = sum(o["amount"] for o in ops if o["type"] == "expense")

    await message.answer(
        f"📊 Сегодня:\n"
        f"💰 +{inc:.2f} ₽\n"
        f"💸 -{exp:.2f} ₽\n"
        f"📈 Итого: {inc - exp:.2f} ₽"
    )


@router.message(Command("week"))
async def cmd_week(message: Message):
    user_id = message.from_user.id
    ensure_user(user_id)

    week_ago = datetime.now() - timedelta(days=7)
    ops = [o for o in user_data[user_id]["operations"] if o["date"] >= week_ago]

    if not ops:
        await message.answer("📊 За неделю операций нет")
        return

    inc = sum(o["amount"] for o in ops if o["type"] == "income")
    exp = sum(o["amount"] for o in ops if o["type"] == "expense")

    await message.answer(
        f"📊 Неделя:\n"
        f"💰 +{inc:.2f} ₽\n"
        f"💸 -{exp:.2f} ₽\n"
        f"📈 Итого: {inc - exp:.2f} ₽"
    )


@router.message(Command("month"))
async def cmd_month(message: Message):
    user_id = message.from_user.id
    ensure_user(user_id)

    month_ago = datetime.now() - timedelta(days=30)
    ops = [o for o in user_data[user_id]["operations"] if o["date"] >= month_ago]

    if not ops:
        await message.answer("📊 За месяц операций нет")
        return

    inc = sum(o["amount"] for o in ops if o["type"] == "income")
    exp = sum(o["amount"] for o in ops if o["type"] == "expense")

    await message.answer(
        f"📊 Месяц:\n"
        f"💰 +{inc:.2f} ₽\n"
        f"💸 -{exp:.2f} ₽\n"
        f"📈 Итого: {inc - exp:.2f} ₽"
    )


@router.message(Command("history"))
async def cmd_history(message: Message):
    user_id = message.from_user.id
    ensure_user(user_id)

    if not user_data[user_id]["operations"]:
        await message.answer("📜 История пуста")
        return

    ops = user_data[user_id]["operations"][-15:]
    text = "📜 Последние 15 операций:\n\n"

    for o in reversed(ops):
        emoji = "💰" if o["type"] == "income" else "💸"
        dt = o["date"].strftime("%d.%m %H:%M")
        comment_part = f" — {o['comment']}" if o["comment"] else ""
        text += (
            f"{emoji} {o['amount']:.2f} ₽ | {o['category']} | {dt}{comment_part}\n"
        )

    await message.answer(text)


@router.message(Command("categories"))
async def cmd_categories(message: Message):
    user_id = message.from_user.id
    ensure_user(user_id)

    cats = user_data[user_id]["categories"]
    await message.answer(
        "📂 Категории:\n" + "\n".join([f"{i + 1}. {c}" for i, c in enumerate(cats)])
    )


@router.message(Command("accounts"))
async def cmd_accounts(message: Message):
    await message.answer("💳 Счета:\n1. Наличные\n2. Карта")


@router.message(Command("funds"))
async def cmd_funds(message: Message):
    user_id = message.from_user.id
    ensure_user(user_id)

    funds = user_data[user_id].get("funds", {})
    if not funds:
        await message.answer(
            "🏛️ Фонды\n\n"
            "У вас пока нет фондов.\n"
            "Используйте /createfund для создания."
        )
        return

    funds_list = "\n".join([f"💰 {name}: {amount:.2f} ₽" for name, amount in funds.items()])
    total = sum(funds.values())

    await message.answer(
        f"🏛️ Фонды\n\n{funds_list}\n\n"
        f"📊 Итого: {total:.2f} ₽\n\n"
        "Команды:\n"
        "/createfund - создать фонд\n"
        "/addfund - пополнить фонд\n"
        "/withdrawfund - снять с фонда"
    )


@router.message(Command("createfund"))
async def cmd_createfund(message: Message, state: FSMContext):
    user_id = message.from_user.id
    ensure_user(user_id)

    await message.answer(
        "🏛️ Создание фонда\n"
        "Введите название фонда, например: Отпуск, Ремонт, Образование"
    )
    await state.set_state(ManageFund.waiting_fund_name)
    await state.update_data(action="create")


@router.message(Command("addfund"))
async def cmd_addfund(message: Message, state: FSMContext):
    user_id = message.from_user.id
    ensure_user(user_id)

    funds = user_data[user_id].get("funds", {})
    if not funds:
        await message.answer("⚠️ Сначала создайте фонд с помощью /createfund")
        return

    funds_list = "\n".join([f"• {name}" for name in funds.keys()])
    await message.answer(f"💸 Пополнение фонда\nВыберите фонд по имени:\n{funds_list}")
    await state.set_state(ManageFund.waiting_fund_name)
    await state.update_data(action="add")


@router.message(Command("withdrawfund"))
async def cmd_withdrawfund(message: Message, state: FSMContext):
    user_id = message.from_user.id
    ensure_user(user_id)

    funds = user_data[user_id].get("funds", {})
    if not funds:
        await message.answer("⚠️ Сначала создайте фонд с помощью /createfund")
        return

    funds_list = "\n".join([f"• {name}: {amount:.2f} ₽" for name, amount in funds.items()])
    await message.answer(f"💵 Снятие с фонда\nВыберите фонд по имени:\n{funds_list}")
    await state.set_state(ManageFund.waiting_fund_name)
    await state.update_data(action="withdraw")


@router.message(ManageFund.waiting_fund_name)
async def process_fund_name(message: Message, state: FSMContext):
    user_id = message.from_user.id
    ensure_user(user_id)

    data = await state.get_data()
    action = data.get("action")
    fund_name = message.text.strip()

    if not fund_name:
        await message.answer("❌ Название фонда не может быть пустым")
        return

    if action == "create":
        if fund_name in user_data[user_id].get("funds", {}):
            await message.answer("⚠️ Фонд с таким названием уже существует")
            return

        user_data[user_id]["funds"][fund_name] = 0.0
        await message.answer(f"✅ Фонд '{fund_name}' создан")
        await state.clear()
        return

    funds = user_data[user_id].get("funds", {})
    if fund_name not in funds:
        await message.answer("❌ Фонд не найден. Введите существующее название.")
        return

    await state.update_data(fund_name=fund_name)
    await state.set_state(ManageFund.waiting_amount)
    await message.answer("💰 Введите сумму:")


@router.message(ManageFund.waiting_amount)
async def process_fund_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", ".").replace(" ", ""))
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0")
            return

        user_id = message.from_user.id
        ensure_user(user_id)

        data = await state.get_data()
        action = data.get("action")
        fund_name = data.get("fund_name")

        if not fund_name:
            await message.answer("❌ Фонд не выбран")
            await state.clear()
            return

        if action == "add":
            user_data[user_id]["funds"][fund_name] += amount
            await message.answer(
                f"✅ Фонд '{fund_name}' пополнен на {amount:.2f} ₽\n"
                f"Текущий баланс: {user_data[user_id]['funds'][fund_name]:.2f} ₽"
            )

        elif action == "withdraw":
            if user_data[user_id]["funds"][fund_name] < amount:
                await message.answer(
                    f"❌ Недостаточно средств в фонде.\n"
                    f"Доступно: {user_data[user_id]['funds'][fund_name]:.2f} ₽"
                )
                return

            user_data[user_id]["funds"][fund_name] -= amount
            await message.answer(
                f"✅ Снято {amount:.2f} ₽ с фонда '{fund_name}'\n"
                f"Осталось: {user_data[user_id]['funds'][fund_name]:.2f} ₽"
            )

        else:
            await message.answer("❌ Неизвестное действие")
            await state.clear()
            return

        await state.clear()

    except ValueError:
        await message.answer("❌ Введите число")


@router.message(Command("settings"))
async def cmd_settings(message: Message):
    await message.answer(
        "⚙️ Настройки:\n"
        "• Язык: Русский\n"
        "• Валюта: ₽"
    )


@router.message()
async def echo_handler(message: Message):
    await message.answer("Я вас не понял. Используйте /help")


async def main():
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
