import asyncio
import logging
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

# Временное хранилище данных (в памяти)
user_data = {}

# FSM состояния для добавления операций
class AddOperation(StatesGroup):
    waiting_amount = State()
    waiting_category = State()
    waiting_comment = State()

# Обработчик команды /start
@router.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    if user_id not in user_data:
        user_data[user_id] = {
            'balance': 0,
            'operations': [],
            'categories': ['Продукты', 'Транспорт', 'Развлечения', 'Здоровье', 'Другое'],
            'accounts': ['Наличные', 'Карта'],
            'funds': []
        }
    
    await message.answer(
        f"👋 Добро пожаловать, {message.from_user.first_name}!\n\n"
        "Это бот для учёта личных финансов.\n\n"
        "Доступные команды:\n"
        "/addincome - Добавить доход\n"
        "/addexpense - Добавить расход\n"
        "/balance - Показать баланс\n"
        "/today - Операции за сегодня\n"
        "/week - Операции за неделю\n"
        "/month - Операции за месяц\n"
        "/history - История операций\n"
        "/categories - Управление категориями\n"
        "/accounts - Управление счетами\n"
        "/funds - Управление фондами\n"
        "/settings - Настройки\n"
        "/help - Справка"
    )

# Обработчик команды /help
@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📚 Справка по боту\n\n"
        "Основные команды:\n\n"
        "💰 Финансы:\n"
        "/addincome - Добавить доход\n"
        "/addexpense - Добавить расход\n"
        "/balance - Текущий баланс\n\n"
        "📊 Отчёты:\n"
        "/today - Операции за сегодня\n"
        "/week - Операции за неделю\n"
        "/month - Операции за месяц\n"
        "/history - Вся история\n\n"
        "⚙️ Управление:\n"
        "/categories - Категории расходов\n"
        "/accounts - Счета и кошельки\n"
        "/funds - Накопительные фонды\n"
        "/settings - Настройки бота"
    )

# Команда /addincome
@router.message(Command("addincome"))
async def cmd_addincome(message: Message, state: FSMContext):
    await state.set_state(AddOperation.waiting_amount)
    await state.update_data(operation_type='income')
    await message.answer("💵 Введите сумму дохода:")

# Команда /addexpense
@router.message(Command("addexpense"))
async def cmd_addexpense(message: Message, state: FSMContext):
    await state.set_state(AddOperation.waiting_amount)
    await state.update_data(operation_type='expense')
    await message.answer("💸 Введите сумму расхода:")

# Обработка суммы
@router.message(AddOperation.waiting_amount)
async def process_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше нуля. Попробуйте ещё раз:")
            return
        
        await state.update_data(amount=amount)
        await state.set_state(AddOperation.waiting_category)
        
        user_id = message.from_user.id
        if user_id in user_data:
            categories = user_data[user_id]['categories']
            await message.answer(
                f"✅ Сумма: {amount} ₽\n\n"
                f"Выберите категорию или введите новую:\n" +
                "\n".join([f"• {cat}" for cat in categories])
            )
        else:
            await message.answer("Введите категорию:")
    except ValueError:
        await message.answer("❌ Неверный формат суммы. Введите число (например: 500 или 1500.50):")

# Обработка категории
@router.message(AddOperation.waiting_category)
async def process_category(message: Message, state: FSMContext):
    category = message.text.strip()
    await state.update_data(category=category)
    await state.set_state(AddOperation.waiting_comment)
    await message.answer("📝 Введите комментарий (или отправьте '-' чтобы пропустить):")

# Обработка комментария и сохранение операции
@router.message(AddOperation.waiting_comment)
async def process_comment(message: Message, state: FSMContext):
    comment = message.text.strip() if message.text.strip() != '-' else ''
    
    data = await state.get_data()
    user_id = message.from_user.id
    
    operation = {
        'type': data['operation_type'],
        'amount': data['amount'],
        'category': data['category'],
        'comment': comment,
        'date': datetime.now()
    }
    
    if user_id not in user_data:
        user_data[user_id] = {'balance': 0, 'operations': [], 'categories': [], 'accounts': [], 'funds': []}
    
    user_data[user_id]['operations'].append(operation)
    
    if data['operation_type'] == 'income':
        user_data[user_id]['balance'] += data['amount']
        emoji = "💰"
        op_type = "Доход"
    else:
        user_data[user_id]['balance'] -= data['amount']
        emoji = "💸"
        op_type = "Расход"
    
    # Добавляем категорию если её нет
    if data['category'] not in user_data[user_id]['categories']:
        user_data[user_id]['categories'].append(data['category'])
    
    await message.answer(
        f"{emoji} {op_type} добавлен!\n\n"
        f"Сумма: {data['amount']} ₽\n"
        f"Категория: {data['category']}\n"
        f"Комментарий: {comment if comment else 'нет'}\n\n"
        f"Текущий баланс: {user_data[user_id]['balance']:.2f} ₽"
    )
    
    await state.clear()

# Команда /balance
@router.message(Command("balance"))
async def cmd_balance(message: Message):
    user_id = message.from_user.id
    if user_id in user_data:
        balance = user_data[user_id]['balance']
        await message.answer(f"💰 Ваш текущий баланс: {balance:.2f} ₽")
    else:
        await message.answer("💰 Ваш баланс: 0 ₽\nНачните добавлять операции с помощью /addincome или /addexpense")

# Команда /today
@router.message(Command("today"))
async def cmd_today(message: Message):
    user_id = message.from_user.id
    if user_id not in user_data or not user_data[user_id]['operations']:
        await message.answer("📊 Операций за сегодня нет")
        return
    
    today = datetime.now().date()
    today_ops = [op for op in user_data[user_id]['operations'] if op['date'].date() == today]
    
    if not today_ops:
        await message.answer("📊 Операций за сегодня нет")
        return
    
    income = sum(op['amount'] for op in today_ops if op['type'] == 'income')
    expense = sum(op['amount'] for op in today_ops if op['type'] == 'expense')
    
    text = f"📊 Операции за сегодня:\n\n"
    text += f"💰 Доходы: {income:.2f} ₽\n"
    text += f"💸 Расходы: {expense:.2f} ₽\n"
    text += f"📈 Итого: {(income - expense):.2f} ₽\n\n"
    
    for op in today_ops[-10:]:
        emoji = "💰" if op['type'] == 'income' else "💸"
        text += f"{emoji} {op['amount']:.2f} ₽ - {op['category']}\n"
    
    await message.answer(text)

# Команда /week
@router.message(Command("week"))
async def cmd_week(message: Message):
    user_id = message.from_user.id
    if user_id not in user_data or not user_data[user_id]['operations']:
        await message.answer("📊 Операций за неделю нет")
        return
    
    week_ago = datetime.now() - timedelta(days=7)
    week_ops = [op for op in user_data[user_id]['operations'] if op['date'] >= week_ago]
    
    if not week_ops:
        await message.answer("📊 Операций за неделю нет")
        return
    
    income = sum(op['amount'] for op in week_ops if op['type'] == 'income')
    expense = sum(op['amount'] for op in week_ops if op['type'] == 'expense')
    
    await message.answer(
        f"📊 Операции за неделю:\n\n"
        f"💰 Доходы: {income:.2f} ₽\n"
        f"💸 Расходы: {expense:.2f} ₽\n"
        f"📈 Итого: {(income - expense):.2f} ₽\n\n"
        f"Всего операций: {len(week_ops)}"
    )

# Команда /month
@router.message(Command("month"))
async def cmd_month(message: Message):
    user_id = message.from_user.id
    if user_id not in user_data or not user_data[user_id]['operations']:
        await message.answer("📊 Операций за месяц нет")
        return
    
    month_ago = datetime.now() - timedelta(days=30)
    month_ops = [op for op in user_data[user_id]['operations'] if op['date'] >= month_ago]
    
    if not month_ops:
        await message.answer("📊 Операций за месяц нет")
        return
    
    income = sum(op['amount'] for op in month_ops if op['type'] == 'income')
    expense = sum(op['amount'] for op in month_ops if op['type'] == 'expense')
    
    await message.answer(
        f"📊 Операции за месяц:\n\n"
        f"💰 Доходы: {income:.2f} ₽\n"
        f"💸 Расходы: {expense:.2f} ₽\n"
        f"📈 Итого: {(income - expense):.2f} ₽\n\n"
        f"Всего операций: {len(month_ops)}"
    )

# Команда /history
@router.message(Command("history"))
async def cmd_history(message: Message):
    user_id = message.from_user.id
    if user_id not in user_data or not user_data[user_id]['operations']:
        await message.answer("📜 История операций пуста\n\nИспользуйте /addincome или /addexpense для добавления операций")
        return
    
    ops = user_data[user_id]['operations'][-20:]
    text = "📜 Последние 20 операций:\n\n"
    
    for op in reversed(ops):
        emoji = "💰" if op['type'] == 'income' else "💸"
        date_str = op['date'].strftime("%d.%m %H:%M")
        text += f"{emoji} {op['amount']:.2f} ₽ - {op['category']} ({date_str})\n"
    
    await message.answer(text)

# Команда /categories
@router.message(Command("categories"))
async def cmd_categories(message: Message):
    user_id = message.from_user.id
    if user_id not in user_data or not user_data[user_id]['categories']:
        await message.answer("📂 Список категорий пуст\n\nКатегории будут добавляться автоматически при создании операций")
        return
    
    categories = user_data[user_id]['categories']
    text = "📂 Ваши категории:\n\n"
    for i, cat in enumerate(categories, 1):
        text += f"{i}. {cat}\n"
    
    await message.answer(text)

# Команда /accounts
@router.message(Command("accounts"))
async def cmd_accounts(message: Message):
    user_id = message.from_user.id
    if user_id in user_data and user_data[user_id]['accounts']:
        accounts = user_data[user_id]['accounts']
        text = "💳 Ваши счета:\n\n"
        for i, acc in enumerate(accounts, 1):
            text += f"{i}. {acc}\n"
    else:
        text = "💳 Счета:\n\n1. Наличные\n2. Карта\n\nУправление счетами будет доступно в следующих версиях"
    
    await message.answer(text)

# Команда /funds
@router.message(Command("funds"))
async def cmd_funds(message: Message):
    await message.answer(
        "🏦 Накопительные фонды\n\n"
        "Функция находится в разработке.\n"
        "Скоро вы сможете создавать фонды для целевых накоплений!"
    )

# Команда /settings
@router.message(Command("settings"))
async def cmd_settings(message: Message):
    await message.answer(
        "⚙️ Настройки\n\n"
        "Доступные настройки:\n"
        "• Язык: Русский\n"
        "• Валюта: ₽ (RUB)\n"
        "• Часовой пояс: MSK\n\n"
        "Расширенные настройки будут доступны в следующих версиях"
    )

# Обработчик всех остальных сообщений
@router.message()
async def echo_handler(message: Message):
    await message.answer(
        "Я вас не понял. Используйте /help для справки."
    )

# Главная функция
async def main():
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
