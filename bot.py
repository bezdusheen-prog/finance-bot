import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.fsm.storage.memory import MemoryStorage
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

# Обработчик команды /start
@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        f"👋 Добро пожаловать, {message.from_user.first_name}!\n\n"
        "Это бот для учёта личных финансов.\n\n"
        "Доступные команды:\n"
        "/start - Начать работу\n"
        "/help - Справка\n"
        "/balance - Показать баланс\n"
    )

# Обработчик команды /help
@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📚 Справка по боту\n\n"
        "Доступные команды:\n"
        "/start - Начать работу\n"
        "/help - Справка\n"
        "/balance - Показать баланс\n\n"
        "Бот находится в разработке. Скоро будет доступно больше функций!"
    )

# Обработчик команды /balance
@router.message(Command("balance"))
async def cmd_balance(message: Message):
    await message.answer(
        "💰 Ваш баланс: 0 ₽\n\n"
        "Функция учёта операций находится в разработке."
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
