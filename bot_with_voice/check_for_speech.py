import telebot
import config
from botik_for_speech import *
from creds import get_bot_token, get_creds

try:
    bot = telebot.TeleBot(get_bot_token())
except:
    token = input(str('Напиши токен бота'))
    bot = telebot.TeleBot(token=token)

@bot.message_handler(commands=['check'])
def stt_handler(message):
    user_id = message.from_user.id
    bot.send_message(user_id, 'Отправь голосовое сообщение для проверки speech! Бот должен прислать расшифровку'
                              ' сообщения в текст, а также преобразованного в '
                              'голосовое сообщение отправленное вами сообщение.')
    bot.register_next_step_handler(message, stt)


# из гс в текст для проверки
def stt_for_check(message):
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

        # отправка преобразованного в текст сообщения
        bot.send_message(user_id, text)
        # генерация из текста в аудио
        content = tts(user_id=user_id, text=text)

        # отправка преобразованного в аудио сообщения
        bot.send_audio(user_id, content)
    else:
        bot.send_message(user_id, text)