import requests
from speech import text_to_speech, speech_to_text
import config
from database_for_speech import *
import math
from gpt import *
import logging
from database import *
import requests
import telebot
from telebot import types
from datetime import datetime
from transformers import AutoTokenizer
from nou import *
from BOT_with_GPT import *

try:
    bot = telebot.TeleBot(token=config.token)
except:
    token = input(str('Напиши токен бота'))
    bot = telebot.TeleBot(token=token)

user = {}
session = {}
max_tokens_in_task = 2048
system_content = {}
task = {}
assistant_content = 'Ответь на вопрос:'
role = 'Ты дружелюбный помощник. Пиши на русском языке'
max_session = 3
MAX_USER_TTS_SYMBOLS = 700
MAX_TTS_SYMBOLS = 110
MAX_USER_STT_BLOCKS = 12

def is_tts_symbol_limit(message, text):
    user_id = message.from_user.id
    text_symbols = len(text)

    # Функция из БД для подсчёта всех потраченных пользователем символов
    all_symbols = count_all_symbol(user_id) + text_symbols

    # Сравниваем all_symbols с количеством доступных пользователю символов
    if all_symbols >= MAX_USER_TTS_SYMBOLS:
        msg = f"Превышен общий лимит SpeechKit TTS {MAX_USER_TTS_SYMBOLS}. Использовано: {all_symbols} символов. Доступно: {MAX_USER_TTS_SYMBOLS - all_symbols}"
        bot.send_message(user_id, msg)
        return None

    # Сравниваем количество символов в тексте с максимальным количеством символов в тексте
    if text_symbols >= MAX_TTS_SYMBOLS:
        msg = f"Превышен лимит SpeechKit TTS на запрос {MAX_TTS_SYMBOLS}, в сообщении {text_symbols} символов"
        bot.send_message(user_id, msg)
        return None
    return len(text)


def is_stt_block_limit(user_id, duration):
    # user_id = message.from_user.id

    # Переводим секунды в аудиоблоки
    audio_blocks = math.ceil(duration / 15) # округляем в большую сторону
    # Функция из БД для подсчёта всех потраченных пользователем аудиоблоков
    all_blocks = count_all_blocks(user_id) + audio_blocks

    # Проверяем, что аудио длится меньше 30 секунд
    if duration >= 30:
        msg = "SpeechKit STT работает с голосовыми сообщениями меньше 30 секунд"
        bot.send_message(user_id, msg)
        return None

    # Сравниваем all_blocks с количеством доступных пользователю аудиоблоков
    if all_blocks >= MAX_USER_STT_BLOCKS:
        msg = f"Превышен общий лимит SpeechKit STT {MAX_USER_STT_BLOCKS}. Использовано {all_blocks} блоков. Доступно: {MAX_USER_STT_BLOCKS - all_blocks}"
        bot.send_message(user_id, msg)
        return None

    return audio_blocks

#---------------------------------------обработчик команды--------------------------------------------------------------

# Обрабатываем команду /stt into text
@bot.message_handler(commands=['stt'])
def stt_handler(message):
    user_id = message.from_user.id
    bot.send_message(user_id, 'Отправь голосовое сообщение с указанием твоего вопроса!')
    bot.register_next_step_handler(message, stt)


#---------------------------------------------перевод сообщений с помощью speech----------------------------------------

# Переводим голосовое сообщение в текст после команды stt
def stt(message):
    user_id = message.from_user.id

    # Проверка, что сообщение действительно голосовое
    if not message.voice:
        bot.send_message(user_id, 'Отправь голосовое сообщение')
        return

    # Считаем аудиоблоки и проверяем сумму потраченных аудиоблоков
    stt_blocks = is_stt_block_limit(message, message.voice.duration)
    if not stt_blocks:
        return

    file_id = message.voice.file_id  # получаем id голосового сообщения
    file_info = bot.get_file(file_id)  # получаем информацию о голосовом сообщении
    file = bot.download_file(file_info.file_path)  # скачиваем голосовое сообщение

    # Получаем статус и содержимое ответа от SpeechKit
    status, text = speech_to_text(file)  # преобразовываем голосовое сообщение в текст

    # Если статус True - отправляем текст сообщения и сохраняем в БД, иначе - сообщение об ошибке
    if status:
        # Записываем сообщение и кол-во аудиоблоков в БД
        insert_row_stt(user_id, text, stt_blocks)
        global user_answer
        user_answer[user_id] = text
        bot.register_next_step_handler(message, answer_function_speech)
    else:
        bot.send_message(user_id, text)



#отправка из текста в аудио
def tts(user_id, text):
    # user_id = message.from_user.id
    text = text

    # Считаем символы в тексте и проверяем сумму потраченных символов
    text_symbol = is_tts_symbol_limit(user_id, text)
    if text_symbol is None:
        return

    # Записываем сообщение и кол-во символов в БД
    insert_row_tts(user_id, text, text_symbol)

    # Получаем статус и содержимое ответа от SpeechKit
    status, content = text_to_speech(text)

    # Если статус True - отправляем голосовое сообщение, иначе - сообщение об ошибке
    if status:
        return content
    else:
        bot.send_message(user_id, content)

#--------------------------------------ответ от нейросети---------------------------------------------------------------

#Команда, присылающая ответ от нейросети
@bot.message_handler(commands=['begin'])
def answer_function_speech(message, user_answer=None):
    user_id = message.from_user.id

    tokens: int = count_tokens(user_answer[user_id])

    if is_tokens_limit(user_id, user_id, tokens, bot):
        return

    row: sqlite3.Row = session[user_id]

    # создание новой строчки в таблице с user
    add_record_to_table(
        user_id,
        'user',
        user_answer[user_id],
        datetime.now(),
        tokens,
        row['session_id']
    )

    bot.send_message(user_id, 'Генерирую ответ...')
    try:

        results = ask_gpt(text=user_answer[user_id], role=role, mode='continue')

        tokens: int = count_tokens(results)

        if is_tokens_limit(user_id, user_id, tokens, bot):
            return

        #создание новой строчки в таблице с assistant
        add_record_to_table(
            user_id,
            'assistant',
            results,
            datetime.now(),
            tokens,
            row['session_id']
        )

        #генерация из текста в аудио
        content = tts(user_id=user_id, text=results)

        bot.send_audio(user_id, content)
        bot.register_next_step_handler(message, start_function)
        # if call.data != 'button2':
        #     gpt.ask_gpt(text=user_answer, role=role, mode='end')
        #     #удаление ненужного
        #     user_answer = ''
        #
        #     #возвращение к началу
        #     bot.register_next_step_handler(call, subject)
        # else:
        #user_answer += f'{results}'
        return
    except:

        bot.reply_to(
            message,
            f"Извини, я не смог сгенерировать для тебя ответ сейчас",
        )