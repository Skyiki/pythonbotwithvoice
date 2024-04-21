from botik_for_speech import *
import telebot
import gpt
import logging
from database import *

import requests
import telebot
from telebot import types
from datetime import datetime
from transformers import AutoTokenizer
from nou import *
from botik_for_speech import *
from check_for_speech import *
from creds import get_bot_token, get_creds  # модуль для получения bot_token

user_answer = ""
user = {}
session = {}
max_tokens_in_task = 2048
system_content = {}
task = {}
assistant_content = 'Ответь на вопрос:'
role = 'Ты дружелюбный помощник. Пиши на русском языке'
limit_users = 10

iam_token, folder_id = get_creds()  # получаем iam_token и folder_id из файлов

try:
    bot = telebot.TeleBot(get_bot_token())  # создаём объект бота
except:
    token = input(str('Напиши токен бота'))
    bot = telebot.TeleBot(token=token)

# def count_tokens(text):
#     tokenizer = AutoTokenizer.from_pretrained("rhysjones/phi-2-orange")  # название модели
#     return len(tokenizer.encode(text))

# def max_session(chat_id, session):
#     if session > max_sessions:
#         bot.send_message(chat_id, text='У тебя закончились сессии. Больше ты не сможешь воспользоваться ботом(')

# Функция получает идентификатор пользователя, чата и самого бота, чтобы иметь возможность отправлять сообщения
def is_tokens_limit(chat_id, tokens):
    # В зависимости от полученного числа выводим сообщение
    if tokens >= MAX_MODEL_TOKENS:
        bot.send_message(
              chat_id,
              f'Вы израсходовали все токены в этой сессии. Вы можете начать новую, введя help_with')

    elif tokens + 20 >= MAX_MODEL_TOKENS:# Если осталось меньше 20 токенов
        bot.send_message(
            chat_id,
            f'Вы приближаетесь к лимиту в {MAX_MODEL_TOKENS} токенов в этой сессии. '
            f'Ваш запрос содержит суммарно {tokens} токенов.')

    elif tokens / 2 >= MAX_MODEL_TOKENS:# Если осталось меньше половины
        bot.send_message(
            chat_id,
            f'Вы использовали больше половины токенов в этой сессии. '
            f'Ваш запрос содержит суммарно {tokens} токенов.'
          )
        
#--------------------------------------------обработчики команд---------------------------------------------------------
@bot.message_handler(commands=['start'])
def start_function(message):
    user_id = message.from_user.id
    #создание таблицы и бд с помощью функций
    create_db()
    create_table('users')

    limit = is_limit_users(user_id)

    if limit == limit_users:
        bot.send_message(message.chat.id, text='Бот в данный момент не доступен')
        return

    #имя пользователя сохраняется в переменных
    user_name = message.from_user.first_name

    keyboard = types.InlineKeyboardMarkup()
    but1 = types.InlineKeyboardButton(text='Начать!', callback_data='button_1')
    keyboard.add(but1)
    bot.send_message(user_id, 'Я бот-помощник! \n Если хочешь, чтобы я ответил '
                              'на твой\n'
                              ' - текстовой вопрос напиши команду /tts \n'
                              ' - на твое аудио сообщение напиши команду /stt')

    user_id = message.from_user.id
    insert_data(user_id=user_id)
    global user
    user[user_id] = {}


# into voice message
@bot.message_handler(commands=['tts'])
def tts_handler(message):
    user_id = message.from_user.id
    bot.send_message(user_id, 'Отправь следующим сообщением текстовой вопрос, чтобы я ответил тебе!')
    bot.register_next_step_handler(message, finals)


@bot.message_handler(commands=['help'])
def help_function(message):
    user_id = message.chat.id
    bot.send_message(user_id, text='С помощью команд: \n'
                                   '/start - бот начнёт диалог заново'
                                   '/solve_task - можно задать роль боту \n'
                                   '/continue - бот продолжит формулировать ответ')

#-------------------------------------------------генерация сообщения с помощью YaGPT-----------------------------------
@bot.message_handler()
def finals(message):
    user_id = message.from_user.id
    text = message.text

    global user_answer
    user_answer = message.text

    bot.send_message(user_id, text="Если ты хочешь ещё что-то добавить к истории, то напиши сейчас."
                                   "Или ты можешь нажать /begin для начала генерации")


    bot.register_next_step_handler(message, answer_function)


#Команда, присылающая ответ от нейросети
@bot.message_handler(commands=['begin'])
def answer_function(call, user_answer=None):
    user_id = call.message_id

    assert isinstance(user_answer, object)
    tokens: int = gpt.count_gpt_tokens(user_answer)

    if is_tokens_limit(user_id, tokens):
        return

    row: sqlite3.Row = session[user_id]

    # создание новой строчки в таблице с user
    add_record_to_table(
        user_id,
        'user',
        user_answer,
        datetime.now(),
        tokens,
        row['session_id']
    )

    bot.send_message(user_id, 'Генерирую ответ...')
    try:

        results = gpt.ask_gpt(messages=user_answer)

        tokens: int = gpt.count_gpt_tokens(results)

        if is_tokens_limit(user_id, tokens):
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
        bot.send_message(call.message.chat.id, text=results)

        bot.register_next_step_handler(call, start_function)

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
            call,
            f"Извини, я не смог сгенерировать для тебя ответ сейчас",
        )


bot.polling()
