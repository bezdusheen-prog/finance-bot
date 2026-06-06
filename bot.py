import asyncio
import logging
import os
import random
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

# Расширенный список категорий с процентами бюджета
DEFAULT_BUDGET_DISTRIBUTION = {
    'Коммуналка': 15,        'Аренда': 25,
        'Кредиты': 10,
    'Здоровье': 5,
    'Одежда': 3,    'Образование': 3,
    'Подарки': 2,
    'Другое': 2}

# Временное хранилище данных (в памяти)
user_data = {}

# FSM состояния
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
            waiting_action = State()  # создать/пополнить/снять
            waiting_fund_name = State()
            waiting_amount = State()

# Хелперная функция: Расчёт бюджета по категориям
def calculate_budget(salary):
    budget = {}
    for category, percent in DEFAULT_BUDGET_DISTRIBUTION.items():
        budget[category] = round(salary * percent / 100, 2)
    return budget

# Хелпер: Напутствия по тратам
def get_spending_tip(remaining, category_budget):
    if category_budget == 0:
        return ''
    percent_left = (remaining / category_budget) * 100
    
    tips = [
        ("Великолепно! Осталось {:.0f}% бюджета 🎉", 75, 100),
        ("Отлично! Осталось {:.0f}% бюджета 😊", 50, 75),
        ("Неплохо, но лучше сэкономить. Осталось {:.0f}% 👀", 25, 50),
        ("Внимание! Бюджет почти исчерпан: {:.0f}% ⚠️", 0, 25),
        ("Бюджет превышен! 😱", -1000, 0)
    ]
    
    for tip_text, min_p, max_p in tips:
        if min_p <= percent_left < max_p:
            return tip_text.format(percent_left)
    return ''

# Обработчик /start
@router.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    if user_id not in user_data:
        user_data[user_id] = {
            'balance': 0,
            'salary': 0,
            'budget': {},
            'operations': [],
            'categories': list(DEFAULT_BUDGET_DISTRIBUTION.keys()),
            'accounts': ['Наличные', 'Карта'],
            'funds': []
        }
    
    await message.answer(
        f"👋 Добро пожаловать, {message.from_user.first_name}!\n\n"
        "💰 Финансовый помощник с бюджетированием!\n\n"
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
        "/addincome, /addexpense - Учёт операций\n"
        "/balance - Текущий баланс и остатки бюджета\n"
        "/tips - Получить напутствия по тратам\n"
                    "/editdistribution - Редактировать распределение бюджета\n"
                    "/addcategory - Добавить новую категорию\n"
        "/today, /week, /month - Отчёты\n"
        "/categories, /accounts - Управление"
                    "/funds - Просмотр фондов\n"
                    "/createfund - Создать фонд\n"
                    "/addfund - Пополнить фонд\n"
                    "/withdrawfund - Снять с фонда\n"
    )

# Команда /salary - установка зарплаты и расчёт бюджета
@router.message(Command("salary"))
async def cmd_salary(message: Message, state: FSMContext):
    await state.set_state(SetSalary.waiting_salary)
    await message.answer("💵 Введите вашу зарплату (в рублях):")

@router.message(SetSalary.waiting_salary)
async def process_salary(message: Message, state: FSMContext):
    try:
        salary = float(message.text.replace(',', '.'))
        if salary <= 0:
            await message.answer("❌ Зарплата должна быть больше нуля!")
            return
        
        user_id = message.from_user.id
        budget = calculate_budget(salary)
        
        if user_id not in user_data:
            user_data[user_id] = {'balance': 0, 'operations': [], 'categories': list(DEFAULT_BUDGET_DISTRIBUTION.keys())}
        
        user_data[user_id]['salary'] = salary
        user_data[user_id]['budget'] = budget
        
        text = f"✅ Зарплата установлена: {salary:.2f} ₽\n\n📊 Бюджет на месяц:\n"
        for cat, amount in budget.items():
            text += f"• {cat}: {amount:.2f} ₽\n"
        
        await message.answer(text)
        await state.clear()
    except ValueError:
        await message.answer("❌ Неверный формат! Введите число.")

# Команда /tips - напутствия

# Команда /editdistribution - редактирование распределения бюджета
@router.message(Command("editdistribution"))
async def cmd_editdistribution(message: Message, state: FSMContext):
        user_id = message.from_user.id
        if user_id not in user_data or 'budget' not in user_data[user_id]:
                    await message.answer("⚠️ Сначала установите зарплату с помощью /salary")
                    return

    categories_list = "\n".join([f"{i+1}. {cat}: {percent}%" for i, (cat, percent) in enumerate(DEFAULT_BUDGET_DISTRIBUTION.items())])
    await message.answer(f"📊 Текущее распределение:\n{categories_list}\n\nВыберите номер категории для редактирования:")
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
        await message.answer(f"✏️ Категория: {selected_category}\nТекущий %: {current_percent}%\n\nВведите новый процент:")
        await state.set_state(EditDistribution.waiting_new_percent)
    except ValueError:
        await message.answer("❌ Введите число")


@router.message(EditDistribution.waiting_new_percent)
async def process_new_percent(message: Message, state: FSMContext):
        try:
                    new_percent = int(message.text.replace(',', '.').replace(' ', ''))
                    if new_percent < 0 or new_percent > 100:
                                    await message.answer("❌ Процент должен быть от 0 до 100")
                                    return

        data = await state.get_data()
        selected_category = data.get('selected_category')
        DEFAULT_BUDGET_DISTRIBUTION[selected_category] = new_percent

        total = sum(DEFAULT_BUDGET_DISTRIBUTION.values())
        await message.answer(f"✅ Категория {selected_category} обновлена до {new_percent}%\nСумма всех %: {total}%")
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите число")


# Команда /addcategory - добавление новой категории
@router.message(Command("addcategory"))
async def cmd_addcategory(message: Message, state: FSMContext):
        await message.answer("🆕 Введите название новой категории:")
    await state.set_state(AddCategory.waiting_category_name)


@router.message(AddCategory.waiting_category_name)
async def process_category_name(message: Message, state: FSMContext):
        category_name = message.text.strip()
    if category_name in DEFAULT_BUDGET_DISTRIBUTION:
                await message.answer("⚠️ Категория с таким названием уже существует")
                return

    await state.update_data(category_name=category_name)
    await message.answer(f"✏️ Категория: {category_name}\nВведите процент бюджета для этой категории:")
    await state.set_state(AddCategory.waiting_category_percent)


@router.message(AddCategory.waiting_category_percent)
async def process_category_percent(message: Message, state: FSMContext):
        try:
                    percent = int(message.text.replace(',', '.').replace(' ', ''))
                    if percent < 0 or percent > 100:
                                    await message.answer("❌ Процент должен быть от 0 до 100")
                                    return

        data = await state.get_data()
        category_name = data.get('category_name')
        DEFAULT_BUDGET_DISTRIBUTION[category_name] = percent

        total = sum(DEFAULT_BUDGET_DISTRIBUTION.values())
        await message.answer(f"✅ Категория '{category_name}' добавлена с {percent}%\nСумма всех %: {total}%")
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите число")
@router.message(Command("tips"))
async def cmd_tips(message: Message):
    user_id = message.from_user.id
    if user_id not in user_data or not user_data[user_id].get('budget'):
        await message.answer("⚠️ Сначала установите зарплату с помощью /salary")
        return
    
    budget = user_data[user_id]['budget']
    spent_by_category = {}
    
    for op in user_data[user_id].get('operations', []):
        if op['type'] == 'expense':
            cat = op['category']
            spent_by_category[cat] = spent_by_category.get(cat, 0) + op['amount']
    
    text = "💡 Напутствия по тратам:\n\n"
    for cat, budget_amount in budget.items():
        spent = spent_by_category.get(cat, 0)
        remaining = budget_amount - spent
        tip = get_spending_tip(remaining, budget_amount)
        text += f"• {cat}: {remaining:.2f} ₽ / {budget_amount:.2f} ₽\n"
        if tip:
            text += f"  {tip}\n"
    
    await message.answer(text)

# Остальные команды (сокращённые версии из предыдущего файла)
@router.message(Command("addincome"))
async def cmd_addincome(message: Message, state: FSMContext):
    await state.set_state(AddOperation.waiting_amount)
    await state.update_data(operation_type='income')
    await message.answer("💵 Введите сумму дохода:")

@router.message(Command("addexpense"))
async def cmd_addexpense(message: Message, state: FSMContext):
    await state.set_state(AddOperation.waiting_amount)
    await state.update_data(operation_type='expense')
    await message.answer("💸 Введите сумму расхода:")

@router.message(AddOperation.waiting_amount)
async def process_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше нуля!")
            return
        await state.update_data(amount=amount)
        await state.set_state(AddOperation.waiting_category)
        user_id = message.from_user.id
        if user_id in user_data:
            cats = user_data[user_id]['categories']
            await message.answer(f"✅ Сумма: {amount} ₽\n\nВыберите категорию:\n" + "\n".join([f"• {c}" for c in cats]))
        else:
            await message.answer("Введите категорию:")
    except ValueError:
        await message.answer("❌ Неверный формат!")

@router.message(AddOperation.waiting_category)
async def process_category(message: Message, state: FSMContext):
    await state.update_data(category=message.text.strip())
    await state.set_state(AddOperation.waiting_comment)
    await message.answer("📝 Комментарий (или '-'):")

@router.message(AddOperation.waiting_comment)
async def process_comment(message: Message, state: FSMContext):
    comment = message.text.strip() if message.text.strip() != '-' else ''
    data = await state.get_data()
    user_id = message.from_user.id
    
    if user_id not in user_data:
        user_data[user_id] = {'balance': 0, 'operations': [], 'budget': {}, 'categories': list(DEFAULT_BUDGET_DISTRIBUTION.keys())}
    
    operation = {'type': data['operation_type'], 'amount': data['amount'], 'category': data['category'], 'comment': comment, 'date': datetime.now()}
    user_data[user_id]['operations'].append(operation)
    
    if data['operation_type'] == 'income':
        user_data[user_id]['balance'] += data['amount']
        emoji = "💰"
        op_type = "Доход"
    else:
        user_data[user_id]['balance'] -= data['amount']
        emoji = "💸"
        op_type = "Расход"
    
    await message.answer(f"{emoji} {op_type} добавлен!\nСумма: {data['amount']} ₽\nБаланс: {user_data[user_id]['balance']:.2f} ₽")
    await state.clear()

@router.message(Command("balance"))
async def cmd_balance(message: Message):
    user_id = message.from_user.id
    if user_id in user_data:
        bal = user_data[user_id]['balance']
        text = f"💰 Баланс: {bal:.2f} ₽\n\n"
        if user_data[user_id].get('budget'):
            text += "📊 Остатки бюджета:\n"
            for cat, budg in user_data[user_id]['budget'].items():
                spent = sum(op['amount'] for op in user_data[user_id].get('operations', []) if op['type']=='expense' and op['category']==cat)
                text += f"• {cat}: {budg-spent:.2f}/{budg:.2f} ₽\n"
        await message.answer(text)
    else:
        await message.answer("💰 Баланс: 0 ₽")

@router.message(Command("today"))
async def cmd_today(message: Message):
    user_id = message.from_user.id
    if user_id not in user_data or not user_data[user_id]['operations']:
        await message.answer("📊 Операций нет")
        return
    today = datetime.now().date()
    ops = [o for o in user_data[user_id]['operations'] if o['date'].date()==today]
    if not ops:
        await message.answer("📊 Операций за сегодня нет")
        return
    inc = sum(o['amount'] for o in ops if o['type']=='income')
    exp = sum(o['amount'] for o in ops if o['type']=='expense')
    await message.answer(f"📊 Сегодня:\n💰 +{inc:.2f} ₽\n💸 -{exp:.2f} ₽\n📈 {inc-exp:.2f} ₽")

@router.message(Command("week"))
async def cmd_week(message: Message):
    user_id = message.from_user.id
    if user_id not in user_data: 
        await message.answer("Нет данных")
        return
    week_ago = datetime.now() - timedelta(days=7)
    ops = [o for o in user_data[user_id].get('operations',[]) if o['date']>=week_ago]
    inc = sum(o['amount'] for o in ops if o['type']=='income')
    exp = sum(o['amount'] for o in ops if o['type']=='expense')
    await message.answer(f"📊 Неделя:\n💰 +{inc:.2f} ₽\n💸 -{exp:.2f} ₽")

@router.message(Command("month"))
async def cmd_month(message: Message):
    user_id = message.from_user.id
    if user_id not in user_data:
        await message.answer("Нет данных")
        return
    month_ago = datetime.now() - timedelta(days=30)
    ops = [o for o in user_data[user_id].get('operations',[]) if o['date']>=month_ago]
    inc = sum(o['amount'] for o in ops if o['type']=='income')
    exp = sum(o['amount'] for o in ops if o['type']=='expense')
    await message.answer(f"📊 Месяц:\n💰 +{inc:.2f} ₽\n💸 -{exp:.2f} ₽")

@router.message(Command("history"))
async def cmd_history(message: Message):
    user_id = message.from_user.id
    if user_id not in user_data or not user_data[user_id].get('operations'):
        await message.answer("📜 История пуста")
        return
    ops = user_data[user_id]['operations'][-15:]
    text = "📜 Последние 15:\n\n"
    for o in reversed(ops):
        e = "💰" if o['type']=='income' else "💸"
        text += f"{e} {o['amount']:.2f} ₽ - {o['category']}\n"
    await message.answer(text)

@router.message(Command("categories"))
async def cmd_categories(message: Message):
    user_id = message.from_user.id
    if user_id in user_data:
        cats = user_data[user_id]['categories']
        await message.answer("📂 Категории:\n"+"\n".join([f"{i+1}. {c}" for i,c in enumerate(cats)]))
    else:
        await message.answer("Нет данных")

@router.message(Command("accounts"))
async def cmd_accounts(message: Message):
    await message.answer("💳 Счета:\n1. Наличные\n2. Карта")

@router.message(Command("funds"))
async def cmd_funds(message: Message):
    user_id = message.from_user.id
    if user_id not in user_data:
                user_data[user_id] = {'balance': 0, 'operations': [], 'categories': list(DEFAULT_BUDGET_DISTRIBUTION.keys()), 'funds': {}}

    funds = user_data[user_id].get('funds', {})
    if not funds:
                await message.answer("🏛️ Фонды\n\nУ вас пока нет фондов.\nИспользуйте /createfund для создания")
                return

    funds_list = "\n".join([f"💰 {name}: {amount} ₽" for name, amount in funds.items()])
    total = sum(funds.values())
    await message.answer(f"🏛️ Фонды\n\n{funds_list}\n\n📊 Итого: {total} ₽\n\nКоманды:\n/createfund - создать фонд\n/addfund - пополнить фонд\n/withdrawfund - снять с фонда")


# Команда /createfund - создать фонд
@router.message(Command("createfund"))
async def cmd_createfund(message: Message, state: FSMContext):
        await message.answer("🏛️ Создание фонда\nВведите название фонда (например, 'Отпуск', 'Ремонт', 'Образование'):")
    await state.set_state(ManageFund.waiting_fund_name)
    await state.update_data(action='create')


# Команда /addfund - пополнить фонд
@router.message(Command("addfund"))
async def cmd_addfund(message: Message, state: FSMContext):
        user_id = message.from_user.id
    if user_id not in user_data or not user_data[user_id].get('funds'):
                await message.answer("⚠️ Сначала создайте фонд с помощью /createfund")
                return

    funds = user_data[user_id]['funds']
    funds_list = "\n".join([f"{i+1}. {name}" for i, name in enumerate(funds.keys())])
    await message.answer(f"💸 Пополнение фонда\nВыберите фонд:\n{funds_list}")
    await state.set_state(ManageFund.waiting_fund_name)
    await state.update_data(action='add')


# Команда /withdrawfund - снять с фонда
@router.message(Command("withdrawfund"))
async def cmd_withdrawfund(message: Message, state: FSMContext):
        user_id = message.from_user.id
    if user_id not in user_data or not user_data[user_id].get('funds'):
                await message.answer("⚠️ Сначала создайте фонд с помощью /createfund")
                return

    funds = user_data[user_id]['funds']
    funds_list = "\n".join([f"{i+1}. {name}: {amount} ₽" for i, (name, amount) in enumerate(funds.items())])
    await message.answer(f"💵 Снятие с фонда\nВыберите фонд:\n{funds_list}")
    await state.set_state(ManageFund.waiting_fund_name)
    await state.update_data(action='withdraw')


# FSM обработчики для управления фондами
@router.message(ManageFund.waiting_fund_name)
async def process_fund_name(message: Message, state: FSMContext):
        user_id = message.from_user.id
    data = await state.get_data()
    action = data.get('action')

    if action == 'create':
                fund_name = message.text.strip()
                if fund_name in user_data[user_id].get('funds', {}):
                                await message.answer("⚠️ Фонд с таким названием уже существует")
                                return
                            if 'funds' not in user_data[user_id]:
                                            user_data[user_id]['funds'] = {}
                                        user_data[user_id]['funds'][fund_name] = 0
        await message.answer(f"✅ Фонд '{fund_name}' создан!")
        await state.clear()
    else:
        fund_name = message.text.strip()
        funds = user_data[user_id].get('funds', {})
        if fund_name not in funds:
                        await message.answer("❌ Фонд не найден. Введите существующее название")
                        return
                    await state.update_data(fund_name=fund_name)
        await message.answer("💰 Введите сумму:")
        await state.set_state(ManageFund.waiting_amount)


@router.message(ManageFund.waiting_amount)
async def process_fund_amount(message: Message, state: FSMContext):
        try:
                    amount = float(message.text.replace(',', '.').replace(' ', ''))
                    if amount <= 0:
                                    await message.answer("❌ Сумма должна быть больше 0")
                                    return

        user_id = message.from_user.id
        data = await state.get_data()
        action = data.get('action')
        fund_name = data.get('fund_name')

        if action == 'add':
                        user_data[user_id]['funds'][fund_name] += amount
                        await message.answer(f"✅ Фонд '{fund_name}' пополнен на {amount} ₽\nТекущий баланс: {user_data[user_id]['funds'][fund_name]} ₽")
                    elif action == 'withdraw':
                                    if user_data[user_id]['funds'][fund_name] < amount:
                                                        await message.answer(f"❌ Недостаточно средств в фонде. Доступно: {user_data[user_id]['funds'][fund_name]} ₽")
                                                        return
                                                    user_data[user_id]['funds'][fund_name] -= amount
            await message.answer(f"✅ Снято {amount} ₽ с фонда '{fund_name}'\nОсталось: {user_data[user_id]['funds'][fund_name]} ₽")

        await state.clear()
    except ValueError:
        await message.answer("❌ Введите число")
@router.message(Command("settings"))
async def cmd_settings(message: Message):
    await message.answer("⚙️ Настройки:\n• Язык: Русский\n• Валюта: ₽")

@router.message()
async def echo_handler(message: Message):
    await message.answer("Я вас не понял. /help")

async def main():
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
