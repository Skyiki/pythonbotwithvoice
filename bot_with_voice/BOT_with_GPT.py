from botik_for_speech import *
import telebot
import gpt
import logging
from database import(
    create_db,
    create_table,
    insert_data,
    add_record_to_table,
    execute_selection_query,
    is_limit_users
)

import requests
import telebot
from telebot import types
from datetime import datetime
from transformers import AutoTokenizer
from nou import *
from botik_for_speech import *
from check_for_speech import *

user_answer = ""
user = {}
session = {}
max_tokens_in_task = 2048
system_content = {}
task = {}
assistant_content = 'Ответь на вопрос:'
role = 'Ты дружелюбный помощник. Пиши на русском языке'
max_session = 3

try:
    bot = telebot.TeleBot(token=config.token)
except:
    token = input(str('Напиши токен бота'))
    bot = telebot.TeleBot(token=token)

def count_tokens(text):
    tokenizer = AutoTokenizer.from_pretrained("rhysjones/phi-2-orange")  # название модели
    return len(tokenizer.encode(text))

#--------------------------------------------обработчики команд---------------------------------------------------------
@bot.message_handler(commands=['start'])
def start_function(message):
    user_id = message.from_user.id
    #создание таблицы и бд с помощью функций
    create_db()
    create_table('users')

    limit = is_limit_users()

    if limit == True:
        bot.send_message(message.chat.id, text='Бот в данный момент не доступен')
        return

    #имя пользователя сохраняется в переменных
    user_name = message.from_user.first_name

    keyboard = types.InlineKeyboardMarkup()
    but1 = types.InlineKeyboardButton(text='Начать!', callback_data='button_1')
    keyboard.add(but1)
    bot.send_message(user_id, 'Я бот-помощник! \n Если хочешь, чтобы я ответил '
                              'на твой текстовой вопрос напиши команду /tts \n'
                              'Если хочешь, чтобы я ответил на твое аудио сообщение напиши команду /stt')

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

    session[user_id] += 1
    max_session(user_id, user_id, session, bot)

    bot.register_next_step_handler(message, answer_function)


#Команда, присылающая ответ от нейросети
@bot.message_handler(commands=['begin'])
def answer_function(call, user_answer=None):
    user_id = call.message_id

    tokens: int = gpt.count_tokens(user_answer)

    if gpt.is_tokens_limit(user_id, user_id, tokens, bot):
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

        results = gpt.ask_gpt(text=user_answer, role=role, mode='continue')

        tokens: int = count_tokens(results)

        if gpt.is_tokens_limit(user_id, user_id, tokens, bot):
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
