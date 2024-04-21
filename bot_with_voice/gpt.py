import requests
import logging
import config
import sqlite3
import telebot
import database_for_speech
import time


logging.basicConfig(level=logging.DEBUG,
                    format="%(asctime)s %(message)s")

CONTINUE_STORY = 'Продолжи сюжет в 1-3 предложения и оставь интригу. Не пиши никакой пояснительный текст от себя'
END_STORY = 'Напиши завершение истории c неожиданной развязкой. Не пиши никакой пояснительный текст от себя'


GPT_MODEL = 'yandexgpt'
# Ограничение на выход модели в токенах
MAX_MODEL_TOKENS = 150
# Креативность GPT (от 0 до 1)
MODEL_TEMPERATURE = 0.6

expires_at = []
DB_DIR = 'db'
DB_NAME = 'db.sqlite'
DB_TABLE_USERS_NAME = 'users'
token_data = {"access_token":"t1.9euelZqSz83Pko3GyseMz5mXi4mcku3rnpWalpKUx5eTmJaSmpHMmpvJmsnl9PcFRWtO-e8MS32v3fT3RXNoTvnvDEt9r83n9euelZrNnYyMzJWOncyPmY7Ol5zPxu_8xeuelZrN"
"nYyMzJWOncyPmY7Ol5zPxr3rnpWay8qQlI3LzseUzYySnZrOi5O13oac0ZyQko-Ki5rRi5nSnJCSj4qLmtKSmouem56LntKMng.SDGab_1A2R8QLioCAPFs6jfp2uV0rNzbK6Rvmc5yNWV9rZkq8LT_s63Zx"
"OQGt90MEnu7RtBBcqclafODCeKfDw","expires_in":43200, "token_type":"Bearer"}

SYSTEM_PROMPT = (
    "Ты пишешь историю вместе с человеком. "
    "Историю вы пишете по очереди. Начинает человек, а ты продолжаешь. "
    "Если это уместно, ты можешь добавлять в историю диалог между персонажами. "
    "Диалоги пиши с новой строки и отделяй тире. "
    "Не пиши никакого пояснительного текста в начале, а просто логично продолжай историю."
)

TOKEN = config.iam_token  # Токен для доступа к YandexGPT изменяется каждые 12 часов
FOLDER_ID = config.folder_id  # Folder_id для доступа к YandexGPT
IAM_TOKEN = config.iam_token

# подсчитываем количество токенов в сообщениях
def count_gpt_tokens(messages):
    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/tokenizeCompletion"
    headers = {
        'Authorization': f'Bearer {IAM_TOKEN}',
        'Content-Type': 'application/json'
    }
    data = {
        'modelUri': f"gpt://{FOLDER_ID}/yandexgpt-lite",
        "messages": messages
    }
    try:
        return len(requests.post(url=url, json=data, headers=headers).json()['tokens'])
    except Exception as e:
        logging.error(e)  # если ошибка - записываем её в логи
        return 0



# Функция получает идентификатор пользователя, чата и самого бота, чтобы иметь возможность отправлять сообщения
def is_tokens_limit(chat_id, tokens, bot):
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

def create_new_token():
    """Создание нового токена"""
    metadata_url = "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token"
    headers = {"Metadata-Flavor": "Google"}
    try:
        response = requests.get(metadata_url, headers=headers)
        if response.status_code == 200:
            global token_data
            token_data = response.json()

            global expires_at
            expires_at = time.time() + token_data['expires_in']

            logging.info('Token created')
        else:
            logging.error(f'Failed to retrieve token. Status code: {response.status_code}')
    except Exception as e:
        logging.error(f'An error occurred while retrieving token: {e}')

    token = token_data['access_token']
    return token


# Функция создает промт для начала истории, используя выбор пользователя (жанр, герой и т.п.)
# Принимает два параметра: user_data (словарь данных от пользователей)
# и user_id (id конкретного пользователя)
def create_prompt(user_data, user_id):
    # Начальный текст для нашей истории - вводная часть
    prompt = SYSTEM_PROMPT

    # Добавляем в начало истории инфу о жанре и главном герое, которых выбрал пользователь
    prompt += (f"\nНапиши начало истории в стиле {user_data[user_id]['genre']} "
              f"с главным героем {user_data[user_id]['character']}. "
              f"Вот начальный сеттинг: \n{user_data[user_id]['setting']}. \n"
              "Начало должно быть коротким, 1-3 предложения.\n")

    # Если пользователь указал что-то еще в "дополнительной информации", добавляем это тоже
    if user_data[user_id]['additional_info']:
        prompt += (f"Также пользователь попросил учесть "
                   f"следующую дополнительную информацию: {user_data[user_id]['additional_info']} ")

    # Добавляем к prompt напоминание не давать пользователю лишних подсказок
    prompt += 'Не пиши никакие подсказки пользователю, что делать дальше. Он сам знает'

    # Возвращаем сформированный текст истории
    return prompt

# Выполняем запрос к YandexGPT
# запрос к GPT
def ask_gpt(messages):
    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    headers = {
        'Authorization': f'Bearer {IAM_TOKEN}',
        'Content-Type': 'application/json'
    }
    data = {
        'modelUri': f"gpt://{FOLDER_ID}/yandexgpt-lite",
        "completionOptions": {
            "stream": False,
            "temperature": 0.7,
            "maxTokens": MAX_MODEL_TOKENS
        },
        "messages": SYSTEM_PROMPT + messages  # добавляем к системному сообщению предыдущие сообщения
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        # проверяем статус код
        if response.status_code != 200:
            return False, f"Ошибка GPT. Статус-код: {response.status_code}", None
        # если всё успешно - считаем количество токенов, потраченных на ответ, возвращаем статус, ответ, и количество токенов в ответе
        answer = response.json()['result']['alternatives'][0]['message']['text']
        tokens_in_answer = count_gpt_tokens([{'role': 'assistant', 'text': answer}])
        return True, answer, tokens_in_answer
    except Exception as e:
        logging.error(e)  # если ошибка - записываем её в логи
        return False, "Ошибка при обращении к GPT",  None