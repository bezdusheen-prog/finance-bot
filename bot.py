import asyncio
import logging
import os
import re
import datetime
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from db import (
    init_db, get_or_create_user, add_operation,
    get_user_default_account, find_category_by_name,
    get_today_summary, get_all_users, get_period_summary,
    get_user_operations, delete_operation, get_user_categories,
    get_user_accounts, get_user_envelopes, get_user_funds,
    create_envelope
)

load_dotenv()
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
TZ = os.getenv("TZ", "Europe/Moscow")

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(storage=MemoryStorage())
router = Router()
scheduler = AsyncIOScheduler(timezone=TZ)

class BudgetState(StatesGroup):
    idle = State()
    waiting_salary = State()
    preview_distribution = State()
    editing_distribution = State()
    confirm_distribution = State()
    viewing_current_budget = State()

budget_data = {}

def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Доход"), KeyboardButton(text="➖ Расход")],
            [KeyboardButton(text="📊 Отчет за сегодня")],
            [KeyboardButton(text="Категории"), KeyboardButton(text="Сравнить"), KeyboardButton(text="Конверты")],
        ],
        resize_keyboard=True
    )

@router.message(CommandStart())
async def cmd_start(message: Message):
    await get_or_create_user(message.from_user.id, message.from_user.username or "user")
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "💰 <b>Финансовый бот — справка</b>\n\n"
        "<b>Быстрый ввод одной строкой:</b>\n"
        "• <code>350 кофе</code> — расход\n"
        "• <code>2200 продукты обед</code> — расход с комментарием\n"
        "• <code>+120000 зарплата</code> или <code>зарплата 120000</code> — доход с распределением\n\n"
        "<b>Команды:</b>\n"
        "/add_income — добавить доход\n"
        "/add_expense — добавить расход\n"
        "/today /week /month — отчёты за период\n"
        "/balance — баланс по счетам\n"
        "/history — история операций\n"
        "/categories — категории\n"
        "/accounts — счета\n"
        "/budget — бюджет и конверты\n"
        "/funds — накопительные фонды\n"
        "/settings — настройки\n"
        "/del <id> — удалить операцию",
        reply_markup=main_keyboard()
    )

@router.message(Command("today"))
@router.message(F.text == "📊 Отчет за сегодня")
async def cmd_today(message: Message):
    summary = await get_today_summary(message.from_user.id)
    if not summary:
        await message.answer("🔹 За сегодня операций нет.")
        return
    
    income, expense, ops = summary
    balance = income - expense
    
    text = f"<b>📊 Отчёт за сегодня</b>\n\n"
    text += f"💰 Доходы: {income:,.0f} ₽\n"
    text += f"💸 Расходы: {expense:,.0f} ₽\n"
    text += f"📈 Баланс дня: {balance:+,.0f} ₽\n\n"
    
    if ops:
        text += "<b>Операции:</b>\n"
        for op in ops[:10]:
            sign = "+" if op.type == "income" else "-"
            text += f"{sign}{op.amount:,.0f} ₽ — {op.category.name}\n"
    
    await message.answer(text)

@router.message(Command("week"))
async def cmd_week(message: Message):
    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=7)
    summary = await get_period_summary(message.from_user.id, start_date, end_date)
    
    if not summary:
        await message.answer("🔹 За неделю операций нет.")
        return
    
    income, expense, ops = summary
    balance = income - expense
    
    text = f"<b>📊 Отчёт за неделю</b>\n\n"
    text += f"💰 Доходы: {income:,.0f} ₽\n"
    text += f"💸 Расходы: {expense:,.0f} ₽\n"
    text += f"📈 Баланс: {balance:+,.0f} ₽"
    
    await message.answer(text)

@router.message(Command("month"))
async def cmd_month(message: Message):
    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=30)
    summary = await get_period_summary(message.from_user.id, start_date, end_date)
    
    if not summary:
        await message.answer("🔹 За месяц операций нет.")
        return
    
    income, expense, ops = summary
    balance = income - expense
    
    text = f"<b>📊 Отчёт за месяц</b>\n\n"
    text += f"💰 Доходы: {income:,.0f} ₽\n"
    text += f"💸 Расходы: {expense:,.0f} ₽\n"
    text += f"📈 Баланс: {balance:+,.0f} ₽"
    
    await message.answer(text)

@router.message(Command("balance"))
async def cmd_balance(message: Message):
    accounts = await get_user_accounts(message.from_user.id)
    
    if not accounts:
        await message.answer("🔹 Счетов ещё нет.")
        return
    
    text = "<b>💼 Баланс по счетам</b>\n\n"
    total = 0
    for acc in accounts:
        text += f"{acc.name}: {acc.balance:,.0f} {acc.currency}\n"
        total += acc.balance
    
    text += f"\n<b>Итого:</b> {total:,.0f} ₽"
    await message.answer(text)

@router.message(Command("history"))
async def cmd_history(message: Message):
    ops = await get_user_operations(message.from_user.id, limit=20)
    
    if not ops:
        await message.answer("🔹 История операций пуста.")
        return
    
    text = "<b>📋 История операций</b>\n\n"
    for op in ops:
        sign = "+" if op.type == "income" else "-"
        date_str = op.created_at.strftime("%d.%m %H:%M")
        text += f"ID {op.id}: {sign}{op.amount:,.0f} ₽ — {op.category.name} ({date_str})\n"
    
    text += "\n<i>Для удаления: /del ID</i>"
    await message.answer(text)

@router.message(Command("categories"))
@router.message(F.text == "Категории")
async def cmd_categories(message: Message):
    categories = await get_user_categories(message.from_user.id)
    
    if not categories:
        await message.answer("🔹 Категорий нет.")
        return
    
    expense_cats = [c for c in categories if c.type == "expense"]
    income_cats = [c for c in categories if c.type == "income"]
    
    text = "<b>📂 Категории расходов:</b>\n"
    for cat in expense_cats:
        text += f"{cat.emoji} {cat.name}\n"
    
    text += "\n<b>💰 Категории доходов:</b>\n"
    for cat in income_cats:
        text += f"{cat.emoji} {cat.name}\n"
    
    text += "\nДобавить: /new_category"
    await message.answer(text)

@router.message(Command("accounts"))
async def cmd_accounts(message: Message):
    accounts = await get_user_accounts(message.from_user.id)
    
    if not accounts:
        await message.answer("🔹 Счетов нет.")
        return
    
    text = "<b>🏦 Счета</b>\n\n"
    for acc in accounts:
        text += f"{acc.name}: {acc.balance:,.0f} {acc.currency}\n"
    
    await message.answer(text)

@router.message(Command("budget"))
@router.message(F.text == "Конверты")
async def cmd_budget(message: Message, state: FSMContext):
    envelopes = await get_user_envelopes(message.from_user.id)
    
    if envelopes:
        text = "<b>📋 Бюджетные конверты</b>\n\n"
        for env in envelopes[:10]:
            percent = (env.spent_amount / env.planned_amount * 100) if env.planned_amount > 0 else 0
            text += f"{env.category.name}:\n"
            text += f"  План: {env.planned_amount:,.0f} ₽\n"
            text += f"  Потрачено: {env.spent_amount:,.0f} ₽ ({percent:.0f}%)\n"
            text += f"  Осталось: {env.planned_amount - env.spent_amount:,.0f} ₽\n\n"
        await message.answer(text)
    else:
        await message.answer(
            "<b>💰 Распределение зарплаты</b>\n\n"
            "Введите сумму зарплаты, чтобы распределить по конвертам.\n\n"
            "Пример: <code>120000</code>"
        )
        await state.set_state(BudgetState.waiting_salary)

@router.message(BudgetState.waiting_salary)
async def process_salary(message: Message, state: FSMContext):
    try:
        salary = float(message.text.replace(",", "").replace(" ", ""))
        if salary <= 0:
            await message.answer("❌ Сумма должна быть положительной. Попробуйте ещё раз.")
            return
    except ValueError:
        await message.answer("❌ Не распознал сумму. Формат: 1=400000, 120000")
        return
    
    distribution = {
        "🏠 Квартира": 0.35,
        "🛒 Продукты": 0.15,
        "🚗 Транспорт": 0.10,
        "🎬 Развлечения": 0.10,
        "💳 Кредитки": 0.05,
        "🏛️ Резерв": 0.05,
        "⚠️ Непредвиденные траты": 0.10,
        "👕 Одежда": 0.05,
        "💊 Здоровье": 0.05,
    }
    
    text = f"<b>💰 Распределение {salary:,.0f} ₽</b>\n\n"
    total_allocated = 0
    allocations = {}
    
    for cat_name, percent in distribution.items():
        amount = salary * percent
        allocations[cat_name] = amount
        total_allocated += amount
        text += f"{cat_name}: {amount:,.0f} ₽ ({percent*100:.0f}%)\n"
    
    await state.update_data(salary=salary, allocations=allocations)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_budget")],
        [InlineKeyboardButton(text="✏️ Изменить", callback_data="edit_budget")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_budget")],
    ])
    
    await message.answer(text, reply_markup=keyboard)
    await state.set_state(BudgetState.preview_distribution)

@router.message(Command("funds"))
async def cmd_funds(message: Message):
    funds = await get_user_funds(message.from_user.id)
    
    if not funds:
        await message.answer(
            "<b>🏛️ Накопительные фонды</b>\n\n"
            "Функция в разработке."
        )
        return
    
    text = "<b>🏛️ Накопительные фонды</b>\n\n"
    for fund in funds:
        progress = (fund.current_amount / fund.target_amount * 100) if fund.target_amount > 0 else 0
        text += f"{fund.name}:\n"
        text += f"  Цель: {fund.target_amount:,.0f} ₽\n"
        text += f"  Накоплено: {fund.current_amount:,.0f} ₽ ({progress:.0f}%)\n"
        if fund.monthly_contribution > 0:
            text += f"  Ежемесячно: {fund.monthly_contribution:,.0f} ₽\n"
        text += "\n"
    
    await message.answer(text)

@router.message(Command("settings"))
async def cmd_settings(message: Message):
    await message.answer(
        "<b>⚙️ Настройки</b>\n\n"
        "Доступные настройки:\n"
        "• Часовой пояс: Europe/Moscow\n"
        "• Валюта: ₽\n"
        "• Ежедневный отчёт: 21:00"
    )

@router.message(Command("del"))
async def cmd_delete(message: Message):
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /del ID")
        return
    
    try:
        op_id = int(args[1])
        success = await delete_operation(message.from_user.id, op_id)
        if success:
            await message.answer(f"✅ Операция {op_id} удалена")
        else:
            await message.answer(f"❌ Операция {op_id} не найдена")
    except ValueError:
        await message.answer("ID должен быть числом")

@router.message()
async def process_message(message: Message):
    text = message.text.strip()
    
    if text.startswith("+") or re.match(r"^\d+(?:\.\d+)?\s+", text) or re.match(r"^[\w\s]+\d+", text):
        match = re.match(r"^\+(\d+(?:\.\d+)?)\s+(.+)$", text)
        if match:
            amount = float(match.group(1))
            description = match.group(2)
            op_type = "income"
        else:
            match = re.match(r"^(\d+(?:\.\d+)?)\s+(.+)$", text)
            if match:
                amount = float(match.group(1))
                description = match.group(2)
                op_type = "expense"
            else:
                match = re.match(r"^([\w\s]+?)\s+(\d+)$", text, re.UNICODE)
                if match:
                    description = match.group(1)
                    amount = float(match.group(2))
                    op_type = "income"
                else:
                    await message.answer(
                        "❌ Неверный формат. Используйте:\n"
                        "<code>+50000 зарплата</code> — доход\n"
                        "<code>350 кофе</code> — расход"
                    )
                    return
        
        account = await get_user_default_account(message.from_user.id)
        category = await find_category_by_name(message.from_user.id, description, op_type)
        
        await add_operation(
            user_id=message.from_user.id,
            account_id=account.id,
            category_id=category.id,
            amount=amount,
            op_type=op_type,
            description=description
        )
        
        sign = "+" if op_type == "income" else "-"
        await message.answer(
            f"✅ {sign}{amount:,.0f} ₽\n"
            f"Категория: {category.name}"
        )
        return

async def send_daily_reports():
    users = await get_all_users()
    for user in users:
        try:
            summary = await get_today_summary(user.tg_id)
            if summary:
                income, expense, ops = summary
                balance = income - expense
                text = f"<b>📊 Итоги дня</b>\n\n"
                text += f"💰 Доходы: {income:,.0f} ₽\n"
                text += f"💸 Расходы: {expense:,.0f} ₽\n"
                text += f"📈 Баланс: {balance:+,.0f} ₽"
                await bot.send_message(user.tg_id, text)
        except Exception as e:
            logging.error(f"Failed to send report to {user.tg_id}: {e}")

async def main():
    await init_db()
    dp.include_router(router)
    scheduler.add_job(
        send_daily_reports,
        CronTrigger(hour=21, minute=0, timezone=TZ),
        id="send_daily_reports"
    )
    scheduler.start()
    logging.info("Bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
