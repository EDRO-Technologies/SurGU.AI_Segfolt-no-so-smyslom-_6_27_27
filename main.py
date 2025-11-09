import telebot
from telebot import types as t
from config import token
import ollama
import os
import glob
import json
from pypdf import PdfReader
import docx
import datetime
import re
import speech_recognition as sr
from pydub import AudioSegment
import io

bot = telebot.TeleBot(token)
MODEL_NAME = "llama3"

# Конфигурация
ADMIN_PASSWORD = "admin123"  # Замените на свой пароль
AUTH_FILE = "authorized_users.json"

# Ключевые слова для определения релевантности вопросов
RELEVANCE_KEYWORDS = []

# Инициализация распознавателя речи
recognizer = sr.Recognizer()


# Загрузка авторизованных пользователей
def load_authorized_users():
    if os.path.exists(AUTH_FILE):
        with open(AUTH_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


# Сохранение авторизованных пользователей
def save_authorized_users(users):
    with open(AUTH_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


# Загружаем авторизованных пользователей
authorized_users = load_authorized_users()


def convert_voice_to_text(voice_file_path):
    """Конвертирует голосовое сообщение в текст"""
    try:
        # Конвертируем OGG в WAV
        audio = AudioSegment.from_ogg(voice_file_path)
        wav_file_path = voice_file_path.replace('.ogg', '.wav')
        audio.export(wav_file_path, format='wav')

        # Распознаем речь
        with sr.AudioFile(wav_file_path) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language='ru-RU')

        # Удаляем временные файлы
        os.remove(wav_file_path)
        os.remove(voice_file_path)

        return text
    except sr.UnknownValueError:
        return None  # Не удалось распознать речь
    except Exception as e:
        print(f"Ошибка конвертации голоса: {e}")
        # Удаляем временные файлы в случае ошибки
        if os.path.exists(voice_file_path):
            os.remove(voice_file_path)
        wav_file_path = voice_file_path.replace('.ogg', '.wav')
        if os.path.exists(wav_file_path):
            os.remove(wav_file_path)
        return None


# Функции для чтения файлов
def read_txt_file(file_path):
    """Чтение текстовых файлов"""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return file.read()
    except Exception as e:
        print(f"Ошибка чтения TXT файла {file_path}: {e}")
        return ""


def read_pdf_file(file_path):
    """Чтение PDF файлов"""
    try:
        text = ""
        reader = PdfReader(file_path)
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        print(f"Ошибка чтения PDF файла {file_path}: {e}")
        return ""


def read_docx_file(file_path):
    """Чтение DOCX файлов"""
    try:
        doc = docx.Document(file_path)
        text = ""
        for paragraph in doc.paragraphs:
            text += paragraph.text + "\n"
        return text
    except Exception as e:
        print(f"Ошибка чтения DOCX файла {file_path}: {e}")
        return ""


def read_rtf_file(file_path):
    """Чтение RTF файлов"""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
            return file.read()
    except Exception as e:
        print(f"Ошибка чтения RTF файла {file_path}: {e}")
        return ""


def extract_keywords_from_text(text):
    """Извлекает ключевые слова из текста"""
    # Удаляем спецсимволы и приводим к нижнему регистру
    clean_text = re.sub(r'[^\w\s]', ' ', text.lower())
    # Разбиваем на слова и убираем стоп-слова
    words = clean_text.split()
    # Фильтруем короткие слова и оставляем только значимые
    keywords = [word for word in words if len(word) > 3]
    # Убираем дубликаты
    return list(set(keywords))


def load_all_data_with_sources():
    """Загрузка всех данных из папки data с указанием источников"""
    global RELEVANCE_KEYWORDS
    data_content = ""
    data_folder = "data"
    file_contents = {}
    all_keywords = []

    if not os.path.exists(data_folder):
        os.makedirs(data_folder)
        print(f"Создана папка {data_folder}")
        return "", file_contents

    # Чтение всех файлов в папке data
    for file_path in glob.glob(os.path.join(data_folder, "*")):
        filename = os.path.basename(file_path)
        file_content = ""

        if file_path.endswith('.txt'):
            file_content = read_txt_file(file_path)
        elif file_path.endswith('.pdf'):
            file_content = read_pdf_file(file_path)
        elif file_path.endswith('.docx'):
            file_content = read_docx_file(file_path)
        elif file_path.endswith('.rtf'):
            file_content = read_rtf_file(file_path)

        if file_content:
            data_content += f"\n--- Содержимое файла {filename} ---\n{file_content}\n"
            file_contents[filename] = file_content
            # Извлекаем ключевые слова из содержимого файла
            keywords = extract_keywords_from_text(file_content)
            all_keywords.extend(keywords)

    # Обновляем глобальный список ключевых слов
    RELEVANCE_KEYWORDS = list(set(all_keywords))
    return data_content, file_contents


def is_question_relevant(question, file_contents):
    """Проверяет, относится ли вопрос к предоставленным данным"""
    question_lower = question.lower()

    # Проверяем наличие ключевых слов в вопросе
    for keyword in RELEVANCE_KEYWORDS:
        if keyword in question_lower and len(keyword) > 3:
            return True

    # Проверяем прямое упоминание файлов
    for filename in file_contents.keys():
        filename_without_ext = os.path.splitext(filename)[0].lower()
        if filename_without_ext in question_lower:
            return True

    # Проверяем общие вопросы о данных
    general_data_questions = [
        'что в файл', 'что в документ', 'информация в баз', 'данные в файл',
        'содержан', 'напиши о', 'расскажи о', 'информация о', 'данные о',
        'что известно', 'какая информация', 'какие данные'
    ]

    for data_question in general_data_questions:
        if data_question in question_lower:
            return True

    return False


def get_system_prompt(data_content, file_contents):
    """Создает системный промпт на основе загруженных данных"""
    files_list = "\n".join([f"- {filename}" for filename in file_contents.keys()])

    return {
        "role": "system",
        "content": f"""
Ты - AI-ассистент, который отвечает ТОЛЬКО на основе предоставленных данных.
Если информации для ответа нет в данных - сообщи об этом.

ВАЖНЫЕ ПРАВИЛА:
1. Отвечай ТОЛЬКО на основе предоставленных данных
2. Если в данных нет информации для ответа - скажи "В предоставленных данных нет информации по этому вопросу"
3. Не придумывай информацию
4. Не используй свои знания вне этих данных
5. В КАЖДОМ ответе ОБЯЗАТЕЛЬНО указывай источник информации - название файла, откуда взята информация
6. Если информация взята из нескольких файлов - укажи все источники
7. Формат указания источников: [Источник: название_файла.расширение]
8. Будь точным и ссылайся на конкретные данные
9. Отвечай только на русском
10. Если вопрос не относится к предоставленным данным - вежливо откажись отвечать
11. Не отвечай на вопросы о себе, своих возможностях или других темах, не связанных с данными

Доступные файлы:
{files_list}

Данные для работы:
{data_content}

Теперь ты готов отвечать на вопросы строго по этим данным. ВСЕГДА указывай источники!
"""
    }


def start_markup_start():
    markup = t.InlineKeyboardMarkup(row_width=2)
    button1 = t.InlineKeyboardButton(text="🤖 Задать вопрос AI", callback_data="send_question")
    button2 = t.InlineKeyboardButton(text="📚 Скачать файлы", callback_data="user_download_files")
    button3 = t.InlineKeyboardButton(text="🔧 Админ панель", callback_data="admin_auth")
    markup.add(button1, button2, button3)
    return markup


def admin_panel_markup():
    """Клавиатура админ-панели"""
    markup = t.InlineKeyboardMarkup(row_width=2)
    button1 = t.InlineKeyboardButton(text="📁 Все файлы", callback_data="admin_list_files")
    button2 = t.InlineKeyboardButton(text="📤 Загрузить файлы", callback_data="admin_upload_files")
    button3 = t.InlineKeyboardButton(text="🗑️ Удалить файлы", callback_data="admin_delete_files")
    button4 = t.InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")
    button5 = t.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")
    markup.add(button1, button2, button3, button4, button5)
    return markup


def files_list_markup(mode="delete"):
    """Клавиатура со списком файлов"""
    markup = t.InlineKeyboardMarkup()
    data_folder = "data"

    if not os.path.exists(data_folder):
        markup.add(t.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
        return markup

    files = glob.glob(os.path.join(data_folder, "*"))
    for file_path in files:
        filename = os.path.basename(file_path)
        if mode == "delete":
            button = t.InlineKeyboardButton(text=f"🗑️ {filename}", callback_data=f"delete_{filename}")
        else:  # download
            button = t.InlineKeyboardButton(text=f"📥 {filename}", callback_data=f"download_{filename}")
        markup.add(button)

    markup.add(t.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    return markup


def user_files_markup():
    """Клавиатура со списком файлов для обычных пользователей"""
    markup = t.InlineKeyboardMarkup()
    data_folder = "data"

    if not os.path.exists(data_folder):
        markup.add(t.InlineKeyboardButton(text="🔙 Назад", callback_data="user_back"))
        return markup

    files = glob.glob(os.path.join(data_folder, "*"))
    for file_path in files:
        filename = os.path.basename(file_path)
        button = t.InlineKeyboardButton(text=f"📥 {filename}", callback_data=f"user_download_{filename}")
        markup.add(button)

    markup.add(t.InlineKeyboardButton(text="🔙 Назад", callback_data="user_back"))
    return markup


@bot.message_handler(commands=["start"])
def start_message(message):
    welcome_text = """
🎉 <b>Добро пожаловать в AI-ассистент!</b>

🤖 <b>AI-помощник</b> - задавайте вопросы на основе данных из базы знаний
🎤 <b>Голосовые сообщения</b> - задавайте вопросы голосом
📚 <b>Файлы</b> - скачивайте доступные документы
🔧 <b>Админ-панель</b> - управление базой знаний (требуется авторизация)

Выберите действие:
    """
    bot.send_message(message.chat.id, welcome_text,
                     parse_mode="HTML",
                     reply_markup=start_markup_start())


# Словари для хранения состояний
file_upload_sessions = {}
admin_auth_sessions = {}
file_contents_cache = {}  # Кэш содержимого файлов для каждого чата


@bot.callback_query_handler(func=lambda call: True)
def check_click(call):
    try:
        if call.data == "send_question":
            chat_id = call.message.chat.id

            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(chat_id, "🔄 Загружаю данные из папки data...")

            loaded_data, file_contents = load_all_data_with_sources()
            file_count = len(glob.glob(os.path.join("data", "*")))

            if not loaded_data:
                bot.send_message(chat_id, "❌ В папке data нет файлов или произошла ошибка загрузки")
                return

            system_prompt = get_system_prompt(loaded_data, file_contents)
            user_contexts[chat_id] = [system_prompt]
            active_ai_chats[chat_id] = True
            file_contents_cache[chat_id] = file_contents  # Сохраняем содержимое файлов для этого чата

            welcome_msg = f"""🤖 <b>AI-режим активирован</b>

📊 База знаний: {file_count} файлов из папки data
💾 Загружено {len(loaded_data)} символов данных
📝 Отвечаю только на основе предоставленных данных
🔍 В ответах указываю источники информации
🎤 Поддерживаются голосовые сообщения
🛡️  Вопросы проверяются на релевантность данным
⏹️ Используйте /stop чтобы выключить

Задавайте ваш вопрос текстом или голосом:"""

            bot.send_message(chat_id, welcome_msg, parse_mode="HTML")

        elif call.data == "user_download_files":
            chat_id = call.message.chat.id
            files_markup = user_files_markup()

            data_folder = "data"
            if not os.path.exists(data_folder):
                files_list = "📁 Папка data пуста"
            else:
                files = glob.glob(os.path.join(data_folder, "*"))
                if not files:
                    files_list = "📁 Папка data пуста"
                else:
                    files_list = f"📚 <b>Доступные файлы ({len(files)}):</b>\n\n"
                    for i, file_path in enumerate(files, 1):
                        filename = os.path.basename(file_path)
                        size = os.path.getsize(file_path)
                        files_list += f"{i}. {filename} ({size} байт)\n"

            bot.edit_message_text(files_list,
                                  call.message.chat.id,
                                  call.message.message_id,
                                  parse_mode="HTML",
                                  reply_markup=files_markup)

        elif call.data.startswith("user_download_"):
            filename = call.data.replace("user_download_", "")
            file_path = os.path.join("data", filename)

            try:
                if os.path.exists(file_path):
                    with open(file_path, 'rb') as file:
                        bot.send_document(call.message.chat.id, file,
                                          caption=f"📥 Вот ваш файл: {filename}")
                    bot.answer_callback_query(call.id, f"✅ Файл {filename} отправлен")
                else:
                    bot.answer_callback_query(call.id, "❌ Файл не найден")
            except Exception as e:
                bot.answer_callback_query(call.id, f"❌ Ошибка отправки: {str(e)}")

        elif call.data == "user_back":
            bot.edit_message_text("Привет\nВыбери действие",
                                  call.message.chat.id,
                                  call.message.message_id,
                                  reply_markup=start_markup_start())

        elif call.data == "admin_auth":
            chat_id = call.message.chat.id

            # Проверяем авторизацию
            if str(chat_id) in authorized_users:
                # Пользователь уже авторизован
                bot.edit_message_text("🔧 <b>Админ панель</b>\n\nВыберите действие:",
                                      call.message.chat.id,
                                      call.message.message_id,
                                      parse_mode="HTML",
                                      reply_markup=admin_panel_markup())
            else:
                # Требуется авторизация
                admin_auth_sessions[chat_id] = True
                bot.edit_message_text("🔐 <b>Авторизация</b>\n\n"
                                      "Для доступа к админ-панели введите пароль:\n\n"
                                      "Для отмены нажмите /cancel",
                                      call.message.chat.id,
                                      call.message.message_id,
                                      parse_mode="HTML")

        elif call.data == "admin_list_files":
            # Проверяем авторизацию
            if str(call.message.chat.id) not in authorized_users:
                bot.answer_callback_query(call.id, "❌ Доступ запрещен")
                return

            data_folder = "data"
            if not os.path.exists(data_folder):
                files_list = "📁 Папка data пуста"
            else:
                files = glob.glob(os.path.join(data_folder, "*"))
                if not files:
                    files_list = "📁 Папка data пуста"
                else:
                    files_list = f"📁 <b>Файлы в папке data ({len(files)}):</b>\n\n"
                    total_size = 0
                    for i, file_path in enumerate(files, 1):
                        filename = os.path.basename(file_path)
                        size = os.path.getsize(file_path)
                        total_size += size
                        files_list += f"{i}. {filename} ({size} байт)\n"

                    files_list += f"\n💾 Общий размер: {total_size} байт"

            bot.edit_message_text(files_list,
                                  call.message.chat.id,
                                  call.message.message_id,
                                  parse_mode="HTML",
                                  reply_markup=admin_panel_markup())

        elif call.data == "admin_upload_files":
            # Проверяем авторизацию
            if str(call.message.chat.id) not in authorized_users:
                bot.answer_callback_query(call.id, "❌ Доступ запрещен")
                return

            # Начинаем сессию загрузки файлов
            chat_id = call.message.chat.id
            file_upload_sessions[chat_id] = True

            bot.edit_message_text("📤 <b>Загрузка файлов</b>\n\n"
                                  "Отправьте файлы в формате TXT, PDF, DOCX или RTF.\n"
                                  "Файлы будут автоматически сохранены в папку data.\n\n"
                                  "Для отмены нажмите /cancel",
                                  call.message.chat.id,
                                  call.message.message_id,
                                  parse_mode="HTML")

        elif call.data == "admin_delete_files":
            # Проверяем авторизацию
            if str(call.message.chat.id) not in authorized_users:
                bot.answer_callback_query(call.id, "❌ Доступ запрещен")
                return

            files_markup = files_list_markup("delete")
            bot.edit_message_text("🗑️ <b>Удаление файлов</b>\n\n"
                                  "Выберите файл для удаления:",
                                  call.message.chat.id,
                                  call.message.message_id,
                                  parse_mode="HTML",
                                  reply_markup=files_markup)

        elif call.data.startswith("delete_"):
            # Проверяем авторизацию
            if str(call.message.chat.id) not in authorized_users:
                bot.answer_callback_query(call.id, "❌ Доступ запрещен")
                return

            filename = call.data.replace("delete_", "")
            file_path = os.path.join("data", filename)

            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    bot.answer_callback_query(call.id, f"✅ Файл {filename} удален")

                    # Обновляем список файлов
                    files_markup = files_list_markup("delete")
                    bot.edit_message_reply_markup(call.message.chat.id,
                                                  call.message.message_id,
                                                  reply_markup=files_markup)
                else:
                    bot.answer_callback_query(call.id, "❌ Файл не найден")
            except Exception as e:
                bot.answer_callback_query(call.id, f"❌ Ошибка удаления: {str(e)}")

        elif call.data == "admin_users":
            # Проверяем авторизацию
            if str(call.message.chat.id) not in authorized_users:
                bot.answer_callback_query(call.id, "❌ Доступ запрещен")
                return

            users_list = f"👥 <b>Авторизованные пользователи ({len(authorized_users)}):</b>\n\n"
            for user_id, user_data in authorized_users.items():
                users_list += f"🆔 ID: {user_id}\n"
                users_list += f"👤 Имя: {user_data.get('first_name', 'Unknown')}\n"
                users_list += f"📛 Username: @{user_data.get('username', 'Unknown')}\n"
                users_list += f"📅 Авторизация: {datetime.datetime.fromtimestamp(user_data.get('auth_date', 0)).strftime('%Y-%m-%d %H:%M')}\n\n"

            bot.edit_message_text(users_list,
                                  call.message.chat.id,
                                  call.message.message_id,
                                  parse_mode="HTML",
                                  reply_markup=admin_panel_markup())

        elif call.data == "admin_back":
            bot.edit_message_text("Привет\nВыбери действие",
                                  call.message.chat.id,
                                  call.message.message_id,
                                  reply_markup=start_markup_start())

    except Exception as e:
        print(f"Ошибка в обработке callback: {e}")


# Обработчик авторизации
@bot.message_handler(func=lambda message: message.chat.id in admin_auth_sessions)
def handle_admin_auth(message):
    chat_id = message.chat.id
    password_attempt = message.text.strip()

    if password_attempt == ADMIN_PASSWORD:
        # Авторизация успешна
        authorized_users[str(chat_id)] = {
            "username": message.from_user.username or "Unknown",
            "first_name": message.from_user.first_name or "Unknown",
            "auth_date": message.date
        }
        save_authorized_users(authorized_users)

        del admin_auth_sessions[chat_id]
        bot.send_message(chat_id, "✅ Авторизация успешна! Доступ к админ-панели разрешен.")
        bot.send_message(chat_id, "🔧 <b>Админ панель</b>\n\nВыберите действие:",
                         parse_mode="HTML", reply_markup=admin_panel_markup())
    else:
        # Неверный пароль
        bot.send_message(chat_id, "❌ Неверный пароль. Попробуйте снова или нажмите /cancel для отмены.")


# Обработчик загрузки файлов
@bot.message_handler(content_types=['document'])
def handle_document(message):
    chat_id = message.chat.id

    # Проверяем, активна ли сессия загрузки для админа
    if chat_id in file_upload_sessions and file_upload_sessions[chat_id]:
        # Проверяем авторизацию
        if str(chat_id) not in authorized_users:
            bot.reply_to(message, "❌ Доступ запрещен")
            return

        # Проверяем формат файла
        allowed_extensions = ['.txt', '.pdf', '.docx', '.rtf']
        file_name = message.document.file_name
        file_extension = os.path.splitext(file_name)[1].lower()

        if file_extension not in allowed_extensions:
            bot.reply_to(message, f"❌ Неподдерживаемый формат файла: {file_extension}\n"
                                  f"Разрешенные форматы: {', '.join(allowed_extensions)}")
            return

        try:
            # Скачиваем файл
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)

            # Сохраняем в папку data
            save_path = os.path.join("data", file_name)
            with open(save_path, 'wb') as new_file:
                new_file.write(downloaded_file)

            bot.reply_to(message, f"✅ Файл {file_name} успешно загружен в папку data")

        except Exception as e:
            bot.reply_to(message, f"❌ Ошибка загрузки файла: {str(e)}")

    else:
        # Обычный пользователь пытается загрузить файл - игнорируем
        pass


# Обработчик голосовых сообщений
@bot.message_handler(content_types=['voice'])
def handle_voice_message(message):
    chat_id = message.chat.id

    # Проверяем, активен ли AI-режим
    if chat_id not in active_ai_chats:
        bot.reply_to(message, "❌ AI-режим не активирован. Нажмите /ai чтобы начать.")
        return

    bot.send_chat_action(chat_id, 'typing')

    try:
        # Скачиваем голосовое сообщение
        file_info = bot.get_file(message.voice.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        # Сохраняем временный файл
        voice_file_path = f"temp_voice_{chat_id}.ogg"
        with open(voice_file_path, 'wb') as f:
            f.write(downloaded_file)

        # Конвертируем в текст
        recognized_text = convert_voice_to_text(voice_file_path)

        if recognized_text:
            # Отправляем распознанный текст пользователю
            bot.reply_to(message, f"🎤 <b>Распознано:</b> {recognized_text}", parse_mode="HTML")

            # Обрабатываем распознанный текст как обычное сообщение
            process_ai_question(chat_id, recognized_text, message)
        else:
            bot.reply_to(message, "❌ Не удалось распознать речь. Попробуйте еще раз или напишите текст.")

    except Exception as e:
        print(f"Ошибка обработки голосового сообщения: {e}")
        bot.reply_to(message, "❌ Ошибка обработки голосового сообщения. Попробуйте еще раз.")


# Команда отмены
@bot.message_handler(commands=['cancel'])
def cancel_operation(message):
    chat_id = message.chat.id

    if chat_id in admin_auth_sessions:
        del admin_auth_sessions[chat_id]
        bot.reply_to(message, "❌ Авторизация отменена")
        bot.send_message(chat_id, "Привет\nВыбери действие", reply_markup=start_markup_start())

    elif chat_id in file_upload_sessions:
        file_upload_sessions[chat_id] = False
        bot.reply_to(message, "❌ Загрузка файлов отменена")
        bot.send_message(chat_id, "🔧 <b>Админ панель</b>\n\nВыберите действие:",
                         parse_mode="HTML", reply_markup=admin_panel_markup())


# Команда для выхода из админ-панели
@bot.message_handler(commands=['logout'])
def logout_user(message):
    chat_id = str(message.chat.id)
    if chat_id in authorized_users:
        del authorized_users[chat_id]
        save_authorized_users(authorized_users)
        bot.reply_to(message, "✅ Вы вышли из админ-панели")
    else:
        bot.reply_to(message, "❌ Вы не авторизованы")


@bot.message_handler(commands=["commands", "help"])
def commands(commands_chat):
    help_text = """
📋 <b>Доступные команды:</b>

/start - Главное меню
/ai - Активировать AI-помощник
/stop - Остановить AI-помощник
/reload_data - Перезагрузить данные
/commands - Список команд

🎤 <b>Голосовые сообщения</b> - отправьте голосовое сообщение когда AI-режим активен

🔧 <b>Админ команды:</b>
/cancel - Отмена операции
/logout - Выход из админ-панели

💡 <b>Просто отправьте сообщение</b> чтобы задать вопрос AI-помощнику
    """
    bot.send_message(commands_chat.chat.id, help_text, parse_mode="HTML")


@bot.message_handler(commands=["Best_country", "best_country"])
def photo_message(message_photo):
    text = "USSR"
    try:
        with open("USSR.jpg", "rb") as photo:
            bot.send_photo(message_photo.chat.id, photo, caption=text)
    except FileNotFoundError:
        bot.send_message(message_photo.chat.id, "Photo not found!")


@bot.message_handler(commands=["Chat_ID", "chat_id"])
def id_your_chat(message):
    chat_id = message.chat.id
    bot.reply_to(message, "ID of this chat: " + str(chat_id))


# AI система
active_ai_chats = {}
user_contexts = {}


@bot.message_handler(commands=["ai", "Ai", "AI"])
def activate_ai_chat(message):
    chat_id = message.chat.id

    bot.send_message(chat_id, "🔄 Загружаю данные из папки data...")
    loaded_data, file_contents = load_all_data_with_sources()
    file_count = len(glob.glob(os.path.join("data", "*")))

    if not loaded_data:
        bot.send_message(chat_id, "❌ В папке data нет файлов или произошла ошибка загрузки")
        return

    system_prompt = get_system_prompt(loaded_data, file_contents)
    user_contexts[chat_id] = [system_prompt]
    active_ai_chats[chat_id] = True
    file_contents_cache[chat_id] = file_contents

    welcome_msg = f"""🤖 <b>AI-режим активирован</b>

📊 База знаний: {file_count} файлов из папки data
💾 Загружено {len(loaded_data)} символов данных
📝 Отвечаю только на основе предоставленных данных
🔍 В ответах указываю источники информации [Источник: файл.расширение]
🎤 Поддерживаются голосовые сообщения
🛡️  Вопросы проверяются на релевантность данным
⏹️ Используйте /stop чтобы выключить

Задавайте ваш вопрос текстом или голосом:"""

    bot.send_message(chat_id, welcome_msg, parse_mode="HTML")


@bot.message_handler(commands=["reload_data"])
def reload_data(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "🔄 Перезагружаю данные из папки data...")
    loaded_data, file_contents = load_all_data_with_sources()
    file_count = len(glob.glob(os.path.join("data", "*")))

    if chat_id in active_ai_chats:
        system_prompt = get_system_prompt(loaded_data, file_contents)
        user_contexts[chat_id] = [system_prompt]
        file_contents_cache[chat_id] = file_contents

    bot.reply_to(message, f"✅ Данные перезагружены! Загружено {file_count} файлов, {len(loaded_data)} символов")


@bot.message_handler(commands=["stop"])
def deactivate_ai_chat(message):
    chat_id = message.chat.id
    if chat_id in active_ai_chats:
        del active_ai_chats[chat_id]
    if chat_id in user_contexts:
        del user_contexts[chat_id]
    if chat_id in file_contents_cache:
        del file_contents_cache[chat_id]
    bot.reply_to(message, "🛑 AI-режим отключен. Контекст очищен.")


def process_ai_question(chat_id, question_text, original_message=None):
    """Обрабатывает вопрос для AI (общая функция для текста и голоса)"""
    # Проверяем релевантность вопроса
    if chat_id in file_contents_cache:
        if not is_question_relevant(question_text, file_contents_cache[chat_id]):
            warning_msg = """
⚠️ <b>Вопрос не относится к предоставленным данным</b>

Я могу отвечать только на вопросы, связанные с информацией из загруженных файлов в папке data.

Пожалуйста, задайте вопрос о содержании документов, например:
• Что написано в файле X?
• Какая информация есть о Y?
• Расскажи о Z из документов
"""
            if original_message:
                bot.reply_to(original_message, warning_msg, parse_mode="HTML")
            else:
                bot.send_message(chat_id, warning_msg, parse_mode="HTML")
            return

    user_contexts[chat_id].append({"role": "user", "content": question_text})
    bot.send_chat_action(chat_id, 'typing')

    try:
        response = ollama.chat(
            model=MODEL_NAME,
            messages=user_contexts[chat_id],
        )

        ai_response = response['message']['content']
        user_contexts[chat_id].append({"role": "assistant", "content": ai_response})

        # Добавляем информацию об источниках, если их нет в ответе
        if chat_id in file_contents_cache and file_contents_cache[chat_id]:
            files_mentioned = any(filename in ai_response for filename in file_contents_cache[chat_id].keys())
            if not files_mentioned and "источник" not in ai_response.lower():
                ai_response += "\n\n📚 <i>Информация взята из предоставленных документов</i>"

        if original_message:
            bot.reply_to(original_message, f"🤖 {ai_response}")
        else:
            bot.send_message(chat_id, f"🤖 {ai_response}")

    except Exception as e:
        print(f"AI Error: {e}")
        error_msg = "⚠️ Ошибка генерации. Попробуйте позже."
        if original_message:
            bot.reply_to(original_message, error_msg)
        else:
            bot.send_message(chat_id, error_msg)


@bot.message_handler(func=lambda msg: True)
def handle_text(message):
    chat_id = message.chat.id

    if chat_id not in active_ai_chats:
        return

    if chat_id not in user_contexts:
        bot.send_message(chat_id, "❌ Контекст не найден. Активируйте AI-режим заново.")
        return

    # Обрабатываем текстовый вопрос
    process_ai_question(chat_id, message.text, message)


if __name__ == "__main__":
    # Устанавливаем зависимости для обработки голоса
    print("🔧 Проверка зависимостей для обработки голосовых сообщений...")
    try:
        import speech_recognition as sr
        from pydub import AudioSegment

        print("✅ Все зависимости установлены")
    except ImportError as e:
        print(f"❌ Не установлены зависимости для обработки голоса: {e}")
        print("Установите их командой: pip install SpeechRecognition pydub")

    # Создаем папку data если не существует
    if not os.path.exists("data"):
        os.makedirs("data")
        print("Создана папка data")

    print("🤖 Бот запущен...")
    print(f"👥 Авторизованных пользователей: {len(authorized_users)}")
    print("💾 Данные будут загружаться при активации AI-режима")
    print("🎤 Обработка голосовых сообщений активна")
    bot.polling(non_stop=True)