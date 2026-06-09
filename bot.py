import asyncio
import logging
import os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
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


def ensure_user(user_id: int):
    if user_id not in user_data:
        user_data[user_id] = {
            "balance": 0.0,
            "operations": [],
            "budget": None,
        }


def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💰 Доход"), KeyboardButton(text="💸 Расход")],
            [KeyboardButton(text="📊 Бюджет"), KeyboardButton(text="💼 Баланс")],
            [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📆 Неделя")],
            [KeyboardButton(text="🗓 Месяц"), KeyboardButton(text="📜 История")],
        ],
        resize_keyboard=True,
    )


def parse_amount(text: str) -> float:
    return float(text.replace(" ", "").replace(",", "."))


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
    text = (
        f"📊 Бюджет на месяц\n\n"
        f"Доход: {budget_data['salary']:.2f} ₽\n\n"
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


@router.message(CommandStart())
async def cmd_start(message: Message):
    ensure_user(message.from_user.id)
    await message.answer(
        "👋 Добро пожаловать в финансового бота.\n"
        "Теперь основное управление идет через кнопки ниже.",
        reply_markup=get_main_menu(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Доступно:\n"
        "• 💰 Доход — добавить доход\n"
        "• 💸 Расход — добавить расход\n"
        "• 📊 Бюджет — рассчитать месячный бюджет\n"
        "• 💼 Баланс — текущий баланс\n"
        "• 📅 Сегодня — отчет за сегодня\n"
        "• 📆 Неделя — отчет за 7 дней\n"
        "• 🗓 Месяц — отчет за 30 дней\n"
        "• 📜 История — последние операции"
    )


@router.message(F.text == "💰 Доход")
async def income_button(message: Message, state: FSMContext):
    await state.set_state(AddIncome.waiting_amount)
    await message.answer("Введите сумму дохода в рублях:")


@router.message(AddIncome.waiting_amount)
async def process_income_amount(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text)
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0")
            return

        await state.update_data(amount=amount)
        await state.set_state(AddIncome.waiting_comment)
        await message.answer("Введите комментарий к доходу или '-' если без комментария:")

    except ValueError:
        await message.answer("❌ Введите сумму числом")


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

    await message.answer(
        f"✅ Доход добавлен\n"
        f"Сумма: {data['amount']:.2f} ₽\n"
        f"Баланс: {user_data[message.from_user.id]['balance']:.2f} ₽",
        reply_markup=get_main_menu(),
    )
    await state.clear()


@router.message(F.text == "💸 Расход")
async def expense_button(message: Message, state: FSMContext):
    await state.set_state(AddExpense.waiting_amount)
    await message.answer("Введите сумму расхода в рублях:")


@router.message(AddExpense.waiting_amount)
async def process_expense_amount(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text)
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0")
            return

        await state.update_data(amount=amount)
        await state.set_state(AddExpense.waiting_category)
        await message.answer(
            "Введите категорию расхода.\n"
            "Например: Еда, Транспорт, Развлечения, Здоровье, Прочее"
        )

    except ValueError:
        await message.answer("❌ Введите сумму числом")


@router.message(AddExpense.waiting_category)
async def process_expense_category(message: Message, state: FSMContext):
    category = message.text.strip()
    if not category:
        await message.answer("❌ Категория не может быть пустой")
        return

    await state.update_data(category=category)
    await state.set_state(AddExpense.waiting_comment)
    await message.answer("Введите комментарий к расходу или '-' если без комментария:")


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

    await message.answer(
        f"✅ Расход добавлен\n"
        f"Сумма: {data['amount']:.2f} ₽\n"
        f"Категория: {data['category']}\n"
        f"Баланс: {user_data[message.from_user.id]['balance']:.2f} ₽",
        reply_markup=get_main_menu(),
    )
    await state.clear()


@router.message(F.text == "📊 Бюджет")
async def start_budget_flow(message: Message, state: FSMContext):
    await state.set_state(BudgetFlow.waiting_salary)
    await message.answer("Введите вашу зарплату за месяц в рублях:")


@router.message(BudgetFlow.waiting_salary)
async def process_budget_salary(message: Message, state: FSMContext):
    try:
        salary = parse_amount(message.text)
        if salary <= 0:
            await message.answer("❌ Зарплата должна быть больше 0")
            return

        await state.update_data(salary=salary)
        await state.set_state(BudgetFlow.waiting_rent)
        await message.answer("Введите сумму аренды в рублях:")

    except ValueError:
        await message.answer("❌ Введите сумму числом")


@router.message(BudgetFlow.waiting_rent)
async def process_budget_rent(message: Message, state: FSMContext):
    try:
        rent = parse_amount(message.text)
        if rent < 0:
            await message.answer("❌ Сумма не может быть отрицательной")
            return

        await state.update_data(rent=rent)
        await state.set_state(BudgetFlow.waiting_utilities)
        await message.answer("Введите сумму коммуналки в рублях:")

    except ValueError:
        await message.answer("❌ Введите сумму числом")


@router.message(BudgetFlow.waiting_utilities)
async def process_budget_utilities(message: Message, state: FSMContext):
    try:
        utilities = parse_amount(message.text)
        if utilities < 0:
            await message.answer("❌ Сумма не может быть отрицательной")
            return

        data = await state.get_data()
        salary = data["salary"]
        rent = data["rent"]

        result = calculate_auto_budget(salary, rent, utilities)
        if result is None:
            await message.answer(
                "❌ Фиксированные расходы превышают доход.\n"
                "Введите /start и попробуйте заново с корректными суммами.",
                reply_markup=get_main_menu(),
            )
            await state.clear()
            return

        ensure_user(message.from_user.id)

        budget_data = {
            "salary": result["salary"],
            "fixed": {
                "Аренда": result["rent"],
                "Коммуналка": result["utilities"],
            },
            "fixed_total": result["fixed_total"],
            "remaining": result["remaining"],
            "auto_budget": result["auto_budget"],
        }

        user_data[message.from_user.id]["budget"] = budget_data

        await message.answer(
            build_budget_text(budget_data),
            reply_markup=get_main_menu(),
        )
        await state.clear()

    except ValueError:
        await message.answer("❌ Введите сумму числом")


@router.message(F.text == "💼 Баланс")
async def balance_button(message: Message):
    ensure_user(message.from_user.id)
    balance = user_data[message.from_user.id]["balance"]
    budget = user_data[message.from_user.id].get("budget")

    text = f"💼 Текущий баланс: {balance:.2f} ₽\n\n"
    if budget:
        text += build_budget_text(budget)
    else:
        text += "Бюджет пока не рассчитан."

    await message.answer(text, reply_markup=get_main_menu())


@router.message(F.text == "📅 Сегодня")
async def today_button(message: Message):
    ensure_user(message.from_user.id)

    today = datetime.now().date()
    ops = [
        op for op in user_data[message.from_user.id]["operations"]
        if op["date"].date() == today
    ]

    if not ops:
        await message.answer("За сегодня операций нет.", reply_markup=get_main_menu())
        return

    income = sum(op["amount"] for op in ops if op["type"] == "income")
    expense = sum(op["amount"] for op in ops if op["type"] == "expense")

    await message.answer(
        f"📅 Сегодня\n"
        f"Доходы: {income:.2f} ₽\n"
        f"Расходы: {expense:.2f} ₽\n"
        f"Итог: {income - expense:.2f} ₽",
        reply_markup=get_main_menu(),
    )


@router.message(F.text == "📆 Неделя")
async def week_button(message: Message):
    ensure_user(message.from_user.id)

    date_from = datetime.now() - timedelta(days=7)
    ops = [
        op for op in user_data[message.from_user.id]["operations"]
        if op["date"] >= date_from
    ]

    if not ops:
        await message.answer("За неделю операций нет.", reply_markup=get_main_menu())
        return

    income = sum(op["amount"] for op in ops if op["type"] == "income")
    expense = sum(op["amount"] for op in ops if op["type"] == "expense")

    await message.answer(
        f"📆 Неделя\n"
        f"Доходы: {income:.2f} ₽\n"
        f"Расходы: {expense:.2f} ₽\n"
        f"Итог: {income - expense:.2f} ₽",
        reply_markup=get_main_menu(),
    )


@router.message(F.text == "🗓 Месяц")
async def month_button(message: Message):
    ensure_user(message.from_user.id)

    date_from = datetime.now() - timedelta(days=30)
    ops = [
        op for op in user_data[message.from_user.id]["operations"]
        if op["date"] >= date_from
    ]

    if not ops:
        await message.answer("За месяц операций нет.", reply_markup=get_main_menu())
        return

    income = sum(op["amount"] for op in ops if op["type"] == "income")
    expense = sum(op["amount"] for op in ops if op["type"] == "expense")

    await message.answer(
        f"🗓 Месяц\n"
        f"Доходы: {income:.2f} ₽\n"
        f"Расходы: {expense:.2f} ₽\n"
        f"Итог: {income - expense:.2f} ₽",
        reply_markup=get_main_menu(),
    )


@router.message(F.text == "📜 История")
async def history_button(message: Message):
    ensure_user(message.from_user.id)

    operations = user_data[message.from_user.id]["operations"]
    if not operations:
        await message.answer("История операций пуста.", reply_markup=get_main_menu())
        return

    text = "📜 Последние операции:\n\n"
    for op in operations[-10:]:
        emoji = "💰" if op["type"] == "income" else "💸"
        comment = f" ({op['comment']})" if op["comment"] else ""
        text += (
            f"{emoji} {op['amount']:.2f} ₽ | {op['category']} | "
            f"{op['date'].strftime('%d.%m %H:%M')}{comment}\n"
        )

    await message.answer(text, reply_markup=get_main_menu())


@router.message()
async def fallback_handler(message: Message):
    await message.answer(
        "Используйте кнопки меню ниже.",
        reply_markup=get_main_menu(),
    )


async def main():
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
