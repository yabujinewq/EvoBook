import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from pdfminer.high_level import extract_text
import os
import json
import chardet

# настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


summarized_text = None
questions = []  # cписок вопросов и правильных ответов
user_answers = {}  # ответы пользователя

# функция для отправки запроса в Ollama API
def ask_ollama(prompt, max_tokens=4000):
    url = "https://sickeningly-meteoric-gallinule.cloudpub.ru/generate" # API по которому передаёт запрос
    headers = {
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-coder-v2",
        "prompt": prompt[:1000],  # Ограничиваем длину текста
        "stream": False,
        "max_tokens": max_tokens
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()["response"]
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при запросе к Ollama API: {e}")
        return f"Ошибка при запросе к нейросети. Детали: {str(e)}"

# отправка длинных сообщений
async def send_long_response(update: Update, response: str, max_length=4096):
    for i in range(0, len(response), max_length):
        await update.message.reply_text(response[i:i + max_length])

# извлечение текста из файла
def extract_text_from_file(file_path, file_type):
    try:
        if file_type == "txt":
            encoding = detect_encoding(file_path)
            with open(file_path, 'r', encoding=encoding) as file:
                return file.read()
        elif file_type == "pdf":
            return extract_text(file_path)
        else:
            raise ValueError("Неподдерживаемый формат файла.")
    except Exception as e:
        logger.error(f"Ошибка при извлечении текста из файла: {e}")
        raise

# определение кодировки файла
def detect_encoding(file_path):
    with open(file_path, 'rb') as file:
        raw_data = file.read()
        result = chardet.detect(raw_data)
        return result['encoding']

# обработка команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global summarized_text, questions, user_answers
    summarized_text = None  # Сбрасываем сохранённый текст
    questions = []  # Очищаем список вопросов
    user_answers = {}  # Очищаем ответы пользователя
    await update.message.reply_text(
        'Привет! Начинаем новый диалог. Отправь мне текстовый файл (txt или pdf) или текст, и я сделаю подробный пересказ.'
    )

# обработчик текстовых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global summarized_text, questions, user_answers
    user_text = update.message.text

    # ответы на вопросы
    if "question_id" in context.user_data:
        question_id = context.user_data["question_id"]
        user_answers[question_id] = user_text  # Сохраняем ответ пользователя

        # Проверяем ответ с помощью нейросети
        question = questions[question_id]["question"]
        correct_answer = questions[question_id]["answer"]
        prompt = (
            f"Пользователь ответил на вопрос: '{question}'. "
            f"Его ответ: '{user_text}'. "
            f"Правильный ответ: '{correct_answer}'. "
            f"Оцени ответ пользователя. Если ответ правильный, напиши '✅ Правильно!'. "
            f"Если ответ неправильный, напиши '❌ Неправильно. Правильный ответ: [правильный ответ]'."
        )
        bot_response = ask_ollama(prompt, max_tokens=1000)
        await update.message.reply_text(bot_response)

        # если ответ правильный, задаём следующий вопрос
        if "✅" in bot_response:
            next_question_id = question_id + 1
            if next_question_id < len(questions):
                await send_question(update, context, next_question_id)
            else:
                await update.message.reply_text("Все вопросы пройдены! 🎉")
                del context.user_data["question_id"]  
        else:
            # если ответ неправильный, остаёмся на текущем вопросе
            await send_question(update, context, question_id)
        return

    # формируем промпт для подробного пересказа
    prompt = (
        f"Сделай подробный пересказ этого текста, сохраняя стиль, тон и ключевые детали оригинала. "
        f"Перескажи сюжет, опиши ключевые события, персонажей и их мотивацию. "
        f"Убедись, что пересказ легко читается и сохраняет дух оригинала. "
        f"Текст: {user_text}"
    )

    # отправка запроса в Ollama API
    bot_response = ask_ollama(prompt, max_tokens=4000)
    summarized_text = bot_response  # Сохраняем пересказ

    # отправка ответа пользователю
    await send_long_response(update, bot_response)

    # отправляем клавиатуру с кнопками
    keyboard = [
        [InlineKeyboardButton("Проверить понимание", callback_data="check_understanding")],
        [InlineKeyboardButton("Новый текст", callback_data="new_text")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Что дальше?", reply_markup=reply_markup)

# обработчик файлов
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global summarized_text, questions, user_answers
    file_path = None
    try:
        file = await update.message.document.get_file()
        file_path = f"temp_{update.message.document.file_name}"
        await file.download_to_drive(file_path)

        # определение тип файла
        file_type = file_path.split('.')[-1].lower()
        if file_type not in ["txt", "pdf"]:
            await update.message.reply_text("Неподдерживаемый формат файла. Пожалуйста, отправьте файл в формате txt или pdf.")
            return

        # извлечение текста из файла
        text = extract_text_from_file(file_path, file_type)
        logger.info(f"Текст из файла: {text[:100]}...")  # Логируем первые 100 символов

        
        chapters = split_into_chapters(text)
        summarized_parts = []
        previous_context = ""  # Сохраняем контекст из предыдущих глав

        for chapter in chapters:
            prompt = (
                f"Сделай подробный пересказ этой главы, сохраняя стиль, тон и ключевые детали оригинала. "
                f"Перескажи сюжет, опиши ключевые события, персонажей и их мотивацию. "
                f"Контекст из предыдущих глав: {previous_context}\n\n"
                f"Текст главы: {chapter}"
            )
            bot_response = ask_ollama(prompt, max_tokens=4000)
            summarized_parts.append(bot_response)
            previous_context = bot_response  # Сохраняем контекст для следующей главы

        
        summarized_text = "\n\n".join(summarized_parts)

        # Отправляем ответ пользователю
        await send_long_response(update, summarized_text)

        # Отправляем клавиатуру с кнопками
        keyboard = [
            [InlineKeyboardButton("Проверить понимание", callback_data="check_understanding")],
            [InlineKeyboardButton("Новый текст", callback_data="new_text")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Что дальше?", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Ошибка при обработке файла: {e}")
        await update.message.reply_text("Произошла ошибка при обработке файла. Пожалуйста, попробуйте ещё раз.")

    finally:

        if file_path and os.path.exists(file_path):
            os.remove(file_path)


def split_into_chapters(text):
    chapters = []
    current_chapter = ""
    for line in text.splitlines():
        if line.strip().startswith("Глава"):
            if current_chapter:
                chapters.append(current_chapter)
            current_chapter = line + "\n"
        else:
            current_chapter += line + "\n"
    if current_chapter:
        chapters.append(current_chapter)
    return chapters

# Обработчик нажатий на кнопки
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global summarized_text, questions, user_answers
    query = update.callback_query
    await query.answer()

    if query.data == "check_understanding":
        if summarized_text:
            # Запрашиваем вопросы для проверки понимания
            prompt = f"Задай 5 вопросов для проверки понимания этого текста и укажи правильные ответы. Текст: {summarized_text}"
            bot_response = ask_ollama(prompt, max_tokens=2000)

            # Парсим вопросы и ответы
            questions = parse_questions_and_answers(bot_response)
            if questions:
                # Отправляем первый вопрос
                await send_question(update, context, 0)
            else:
                await query.edit_message_text("Не удалось сгенерировать вопросы.")
        else:
            await query.edit_message_text("Нет сохранённого текста для проверки.")
    elif query.data == "new_text":
        # Вызываем функцию start для сброса состояния
        await start(update, context)

# отправка вопроса пользователю
async def send_question(update: Update, context: ContextTypes.DEFAULT_TYPE, question_id: int):
    if question_id < len(questions):
        question = questions[question_id]["question"]
        context.user_data["question_id"] = question_id  # Сохраняем ID вопроса
        await update.callback_query.message.reply_text(f"Вопрос {question_id + 1}: {question}")
    else:
        await update.callback_query.message.reply_text("Вопросы закончились! 🎉")

# парсинг вопросов и ответов
def parse_questions_and_answers(text):
    questions = []
    lines = text.splitlines()
    for i in range(0, len(lines), 2):
        if i + 1 < len(lines):
            question = lines[i].strip()
            answer = lines[i + 1].strip()
            questions.append({"question": question, "answer": answer})
    return questions


def main():
    # API-токен тг бота
    token = "7611506314:AAEuZmc-RG5nLAuMjfmZS0qdtPmLXE86fxo"

    # создание приложения
    application = Application.builder().token(token).build()

    # регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    application.add_handler(CallbackQueryHandler(button_handler))

    # запуск бота
    application.run_polling()

if __name__ == '__main__':
    main()
