import asyncio
import logging
import os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
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

AUTO_DISTRIBUTION = {
    "Еда": 35,
    "Транспорт": 10,
    "Накопления": 25,
    "Развлечения": 10,
    "Здоровье": 10,
    "Прочее": 10,
}

user_data = {}


class AddIncome(StatesGroup):
    waiting_amount = State()
    waiting_comment = State()


class AddExpense(StatesGroup):
    waiting_amount = State()
    waiting_category = State()
    waiting_comment = State()


class BudgetFlow(StatesGroup):
    waiting_salary = State()
    waiting_rent = State()
    waiting_utilities = State()
    preview = State()


def ensure_user(user_id: int):
    if user_id not in user_data:
        user_data[user_id] = {
            "balance": 0.0,
            "operations": [],
            "budget": {},
            "menu_stack": ["main"],
        }


def get_current_month_key():
    return datetime.now().strftime("%Y-%m")


def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💰 Доход"), KeyboardButton(text="💸 Расход")],
            [KeyboardButton(text="📊 Бюджет"), KeyboardButton(text="💼 Баланс")],
            [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📆 Неделя")],
            [KeyboardButton(text="🗓 Месяц"), KeyboardButton(text="📜 История")],
            [KeyboardButton(text="📂 Бюджет месяца"), KeyboardButton(text="📚 Архив бюджетов")],
        ],
        resize_keyboard=True,
    )


def cancel_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⬅️ Назад"), KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
    )


def expense_categories_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🍔 Еда"), KeyboardButton(text="🚌 Транспорт")],
            [KeyboardButton(text="🎉 Развлечения"), KeyboardButton(text="💊 Здоровье")],
            [KeyboardButton(text="🧾 Прочее")],
            [KeyboardButton(text="⬅️ Назад"), KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
    )


def budget_preview_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Сохранить бюджет")],
            [KeyboardButton(text="🔁 Пересчитать бюджет")],
            [KeyboardButton(text="⬅️ Назад"), KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
    )


def parse_amount(text: str) -> float:
    return float(text.replace(" ", "").replace(",", "."))


def push_menu(user_id: int, menu_name: str):
    ensure_user(user_id)
    stack = user_data[user_id]["menu_stack"]
    if not stack or stack[-1] != menu_name:
        stack.append(menu_name)


def pop_menu(user_id: int):
    ensure_user(user_id)
    stack = user_data[user_id]["menu_stack"]
    if len(stack) > 1:
        stack.pop()
    return stack[-1]


def calculate_auto_budget(salary: float, rent: float, utilities: float):
    fixed_total = rent + utilities
    remaining = salary - fixed_total

    if remaining < 0:
        return None

    auto_budget = {}
    for category, percent in AUTO_DISTRIBUTION.items():
        auto_budget[category] = round(remaining * percent / 100, 2)

    return {
        "salary": salary,
        "rent": rent,
        "utilities": utilities,
        "fixed_total": fixed_total,
        "remaining": remaining,
        "auto_budget": auto_budget,
    }


def build_budget_text(budget_data: dict) -> str:
    month_label = budget_data.get("month", "текущий месяц")

    text = (
        f"📊 Бюджет на месяц: {month_label}\n\n"
        f"Доход: {budget_data['salary']:.2f} ₽\n"
        f"Фиксированные траты:\n"
        f"• Аренда: {budget_data['fixed']['Аренда']:.2f} ₽\n"
        f"• Коммуналка: {budget_data['fixed']['Коммуналка']:.2f} ₽\n"
        f"Итого fixed: {budget_data['fixed_total']:.2f} ₽\n\n"
        f"Остаток для авто-распределения: {budget_data['remaining']:.2f} ₽\n\n"
        f"Авто-распределение:\n"
    )

    for category, amount in budget_data["auto_budget"].items():
        text += f"• {category}: {amount:.2f} ₽\n"

    return text


async def show_main_menu(message: Message, text: str = "Главное меню"):
    await message.answer(text, reply_markup=main_menu())


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    ensure_user(message.from_user.id)
    user_data[message.from_user.id]["menu_stack"] = ["main"]
    await state.clear()
    await message.answer(
        "👋 Добро пожаловать в финансового бота.\n"
        "Выберите действие в меню ниже.",
        reply_markup=main_menu(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Основные действия доступны кнопками:\n"
        "💰 Доход\n"
        "💸 Расход\n"
        "📊 Бюджет\n"
        "💼 Баланс\n"
        "📅 Сегодня\n"
        "📆 Неделя\n"
        "🗓 Месяц\n"
        "📜 История\n"
        "📂 Бюджет месяца\n"
        "📚 Архив бюджетов"
    )


@router.message(F.text == "❌ Отмена")
async def cancel_handler(message: Message, state: FSMContext):
    ensure_user(message.from_user.id)
    user_data[message.from_user.id]["menu_stack"] = ["main"]
    await state.clear()
    await show_main_menu(message, "❌ Действие отменено.")


@router.message(F.text == "⬅️ Назад")
async def back_handler(message: Message, state: FSMContext):
    user_id = message.from_user.id
    ensure_user(user_id)
    pop_menu(user_id)
    await state.clear()
    await show_main_menu(message, "⬅️ Возврат в главное меню.")


@router.message(F.text == "💰 Доход")
async def income_button(message: Message, state: FSMContext):
    ensure_user(message.from_user.id)
    push_menu(message.from_user.id, "income")
    await state.set_state(AddIncome.waiting_amount)
    await message.answer("Введите сумму дохода в рублях:", reply_markup=cancel_menu())


@router.message(AddIncome.waiting_amount)
async def process_income_amount(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text)
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0", reply_markup=cancel_menu())
            return

        await state.update_data(amount=amount)
        await state.set_state(AddIncome.waiting_comment)
        await message.answer(
            "Введите комментарий к доходу или '-' если без комментария:",
            reply_markup=cancel_menu(),
        )
    except ValueError:
        await message.answer("❌ Введите сумму числом", reply_markup=cancel_menu())


@router.message(AddIncome.waiting_comment)
async def process_income_comment(message: Message, state: FSMContext):
    ensure_user(message.from_user.id)
    data = await state.get_data()

    comment = message.text.strip()
    if comment == "-":
        comment = ""

    operation = {
        "type": "income",
        "amount": data["amount"],
        "category": "Доход",
        "comment": comment,
        "date": datetime.now(),
    }

    user_data[message.from_user.id]["operations"].append(operation)
    user_data[message.from_user.id]["balance"] += data["amount"]
    user_data[message.from_user.id]["menu_stack"] = ["main"]

    await state.clear()
    await message.answer(
        f"✅ Доход добавлен\n"
        f"Сумма: {data['amount']:.2f} ₽\n"
        f"Баланс: {user_data[message.from_user.id]['balance']:.2f} ₽",
        reply_markup=main_menu(),
    )


@router.message(F.text == "💸 Расход")
async def expense_button(message: Message, state: FSMContext):
    ensure_user(message.from_user.id)
    push_menu(message.from_user.id, "expense")
    await state.set_state(AddExpense.waiting_amount)
    await message.answer("Введите сумму расхода в рублях:", reply_markup=cancel_menu())


@router.message(AddExpense.waiting_amount)
async def process_expense_amount(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text)
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0", reply_markup=cancel_menu())
            return

        await state.update_data(amount=amount)
        await state.set_state(AddExpense.waiting_category)
        await message.answer("Выберите категорию расхода:", reply_markup=expense_categories_menu())
    except ValueError:
        await message.answer("❌ Введите сумму числом", reply_markup=cancel_menu())


@router.message(AddExpense.waiting_category)
async def process_expense_category(message: Message, state: FSMContext):
    category_map = {
        "🍔 Еда": "Еда",
        "🚌 Транспорт": "Транспорт",
        "🎉 Развлечения": "Развлечения",
        "💊 Здоровье": "Здоровье",
        "🧾 Прочее": "Прочее",
    }

    category = category_map.get(message.text.strip(), message.text.strip())

    if not category:
        await message.answer("❌ Категория не может быть пустой", reply_markup=expense_categories_menu())
        return

    await state.update_data(category=category)
    await state.set_state(AddExpense.waiting_comment)
    await message.answer(
        "Введите комментарий к расходу или '-' если без комментария:",
        reply_markup=cancel_menu(),
    )


@router.message(AddExpense.waiting_comment)
async def process_expense_comment(message: Message, state: FSMContext):
    ensure_user(message.from_user.id)
    data = await state.get_data()

    comment = message.text.strip()
    if comment == "-":
        comment = ""

    operation = {
        "type": "expense",
        "amount": data["amount"],
        "category": data["category"],
        "comment": comment,
        "date": datetime.now(),
    }

    user_data[message.from_user.id]["operations"].append(operation)
    user_data[message.from_user.id]["balance"] -= data["amount"]
    user_data[message.from_user.id]["menu_stack"] = ["main"]

    await state.clear()
    await message.answer(
        f"✅ Расход добавлен\n"
        f"Сумма: {data['amount']:.2f} ₽\n"
        f"Категория: {data['category']}\n"
        f"Баланс: {user_data[message.from_user.id]['balance']:.2f} ₽",
        reply_markup=main_menu(),
    )


@router.message(F.text == "📊 Бюджет")
async def start_budget_flow(message: Message, state: FSMContext):
    ensure_user(message.from_user.id)
    push_menu(message.from_user.id, "budget")
    month_key = get_current_month_key()

    existing_budget = user_data[message.from_user.id]["budget"].get(month_key)
    if existing_budget:
        await message.answer(
            f"На {month_key} бюджет уже существует.\n\n"
            f"{build_budget_text(existing_budget)}\n"
            f"Введите новую зарплату, если хотите пересчитать бюджет заново.",
            reply_markup=cancel_menu(),
        )
    else:
        await message.answer(
            f"Начинаем расчет бюджета на {month_key}.\nВведите вашу зарплату за месяц в рублях:",
            reply_markup=cancel_menu(),
        )

    await state.set_state(BudgetFlow.waiting_salary)


@router.message(BudgetFlow.waiting_salary)
async def process_budget_salary(message: Message, state: FSMContext):
    try:
        salary = parse_amount(message.text)
        if salary <= 0:
            await message.answer("❌ Зарплата должна быть больше 0", reply_markup=cancel_menu())
            return

        await state.update_data(salary=salary)
        await state.set_state(BudgetFlow.waiting_rent)
        await message.answer("Введите сумму аренды в рублях:", reply_markup=cancel_menu())
    except ValueError:
        await message.answer("❌ Введите сумму числом", reply_markup=cancel_menu())


@router.message(BudgetFlow.waiting_rent)
async def process_budget_rent(message: Message, state: FSMContext):
    try:
        rent = parse_amount(message.text)
        if rent < 0:
            await message.answer("❌ Сумма не может быть отрицательной", reply_markup=cancel_menu())
            return

        await state.update_data(rent=rent)
        await state.set_state(BudgetFlow.waiting_utilities)
        await message.answer("Введите сумму коммуналки в рублях:", reply_markup=cancel_menu())
    except ValueError:
        await message.answer("❌ Введите сумму числом", reply_markup=cancel_menu())


@router.message(BudgetFlow.waiting_utilities)
async def process_budget_utilities(message: Message, state: FSMContext):
    try:
        utilities = parse_amount(message.text)
        if utilities < 0:
            await message.answer("❌ Сумма не может быть отрицательной", reply_markup=cancel_menu())
            return

        data = await state.get_data()
        salary = data["salary"]
        rent = data["rent"]

        result = calculate_auto_budget(salary, rent, utilities)
        if result is None:
            await message.answer(
                "❌ Фиксированные расходы превышают доход.\n"
                "Нажмите «❌ Отмена» или введите корректные суммы заново.",
                reply_markup=cancel_menu(),
            )
            return

        month_key = get_current_month_key()
        preview_budget = {
            "month": month_key,
            "created_at": datetime.now(),
            "salary": result["salary"],
            "fixed": {
                "Аренда": result["rent"],
                "Коммуналка": result["utilities"],
            },
            "fixed_total": result["fixed_total"],
            "remaining": result["remaining"],
            "auto_budget": result["auto_budget"],
        }

        await state.update_data(preview_budget=preview_budget)
        await state.set_state(BudgetFlow.preview)

        await message.answer(
            "📋 Предпросмотр бюджета:\n\n" + build_budget_text(preview_budget),
            reply_markup=budget_preview_menu(),
        )

    except ValueError:
        await message.answer("❌ Введите сумму числом", reply_markup=cancel_menu())


@router.message(BudgetFlow.preview, F.text == "✅ Сохранить бюджет")
async def save_budget_preview(message: Message, state: FSMContext):
    ensure_user(message.from_user.id)
    data = await state.get_data()
    preview_budget = data.get("preview_budget")

    if not preview_budget:
        await message.answer("❌ Не найден бюджет для сохранения.", reply_markup=main_menu())
        await state.clear()
        return

    month_key = preview_budget["month"]
    user_data[message.from_user.id]["budget"][month_key] = preview_budget
    user_data[message.from_user.id]["menu_stack"] = ["main"]

    await state.clear()
    await message.answer(
        f"✅ Бюджет на {month_key} сохранен.\n\n{build_budget_text(preview_budget)}",
        reply_markup=main_menu(),
    )


@router.message(BudgetFlow.preview, F.text == "🔁 Пересчитать бюджет")
async def recalc_budget_preview(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(BudgetFlow.waiting_salary)
    await message.answer(
        "Введите новую зарплату за месяц в рублях:",
        reply_markup=cancel_menu(),
    )


@router.message(F.text == "📂 Бюджет месяца")
async def current_budget_button(message: Message):
    ensure_user(message.from_user.id)
    month_key = get_current_month_key()
    budget = user_data[message.from_user.id]["budget"].get(month_key)

    if not budget:
        await message.answer(
            f"На {month_key} бюджет пока не создан.",
            reply_markup=main_menu(),
        )
        return

    await message.answer(build_budget_text(budget), reply_markup=main_menu())


@router.message(F.text == "📚 Архив бюджетов")
async def budget_archive_button(message: Message):
    ensure_user(message.from_user.id)
    budgets = user_data[message.from_user.id]["budget"]

    if not budgets:
        await message.answer("Архив бюджетов пуст.", reply_markup=main_menu())
        return

    sorted_months = sorted(budgets.keys(), reverse=True)
    text = "📚 Архив бюджетов:\n\n"

    for month_key in sorted_months:
        budget = budgets[month_key]
        text += (
            f"• {month_key}: доход {budget['salary']:.2f} ₽, "
            f"fixed {budget['fixed_total']:.2f} ₽, "
            f"остаток {budget['remaining']:.2f} ₽\n"
        )

    await message.answer(text, reply_markup=main_menu())


@router.message(F.text == "💼 Баланс")
async def balance_button(message: Message):
    ensure_user(message.from_user.id)
    balance = user_data[message.from_user.id]["balance"]
    month_key = get_current_month_key()
    budget = user_data[message.from_user.id]["budget"].get(month_key)

    text = f"💼 Текущий баланс: {balance:.2f} ₽\n\n"
    if budget:
        text += f"Активный бюджет за {month_key}\n\n"
        text += build_budget_text(budget)
    else:
        text += f"Бюджет на {month_key} пока не рассчитан."

    await message.answer(text, reply_markup=main_menu())


@router.message(F.text == "📅 Сегодня")
async def today_button(message: Message):
    ensure_user(message.from_user.id)
    today = datetime.now().date()
    ops = [op for op in user_data[message.from_user.id]["operations"] if op["date"].date() == today]

    if not ops:
        await message.answer("За сегодня операций нет.", reply_markup=main_menu())
        return

    income = sum(op["amount"] for op in ops if op["type"] == "income")
    expense = sum(op["amount"] for op in ops if op["type"] == "expense")

    await message.answer(
        f"📅 Сегодня\n"
        f"Доходы: {income:.2f} ₽\n"
        f"Расходы: {expense:.2f} ₽\n"
        f"Итог: {income - expense:.2f} ₽",
        reply_markup=main_menu(),
    )


@router.message(F.text == "📆 Неделя")
async def week_button(message: Message):
    ensure_user(message.from_user.id)
    date_from = datetime.now() - timedelta(days=7)
    ops = [op for op in user_data[message.from_user.id]["operations"] if op["date"] >= date_from]

    if not ops:
        await message.answer("За неделю операций нет.", reply_markup=main_menu())
        return

    income = sum(op["amount"] for op in ops if op["type"] == "income")
    expense = sum(op["amount"] for op in ops if op["type"] == "expense")

    await message.answer(
        f"📆 Неделя\n"
        f"Доходы: {income:.2f} ₽\n"
        f"Расходы: {expense:.2f} ₽\n"
        f"Итог: {income - expense:.2f} ₽",
        reply_markup=main_menu(),
    )


@router.message(F.text == "🗓 Месяц")
async def month_button(message: Message):
    ensure_user(message.from_user.id)
    date_from = datetime.now() - timedelta(days=30)
    ops = [op for op in user_data[message.from_user.id]["operations"] if op["date"] >= date_from]

    if not ops:
        await message.answer("За месяц операций нет.", reply_markup=main_menu())
        return

    income = sum(op["amount"] for op in ops if op["type"] == "income")
    expense = sum(op["amount"] for op in ops if op["type"] == "expense")

    await message.answer(
        f"🗓 Месяц\n"
        f"Доходы: {income:.2f} ₽\n"
        f"Расходы: {expense:.2f} ₽\n"
        f"Итог: {income - expense:.2f} ₽",
        reply_markup=main_menu(),
    )


@router.message(F.text == "📜 История")
async def history_button(message: Message):
    ensure_user(message.from_user.id)
    operations = user_data[message.from_user.id]["operations"]

    if not operations:
        await message.answer("История операций пуста.", reply_markup=main_menu())
        return

    text = "📜 Последние операции:\n\n"
    for op in operations[-10:]:
        emoji = "💰" if op["type"] == "income" else "💸"
        comment = f" ({op['comment']})" if op["comment"] else ""
        text += (
            f"{emoji} {op['amount']:.2f} ₽ | {op['category']} | "
            f"{op['date'].strftime('%d.%m %H:%M')}{comment}\n"
        )

    await message.answer(text, reply_markup=main_menu())


@router.message()
async def fallback_handler(message: Message):
    await message.answer(
        "Используйте кнопки меню ниже.",
        reply_markup=main_menu(),
    )


async def main():
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
