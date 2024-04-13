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
MAX_MODEL_TOKENS = 50
# Креативность GPT (от 0 до 1)
MODEL_TEMPERATURE = 0.6

token_data = {}
expires_at = []
DB_DIR = 'db'
DB_NAME = 'db.sqlite'
DB_TABLE_USERS_NAME = 'users'

SYSTEM_PROMPT = (
    "Ты пишешь историю вместе с человеком. "
    "Историю вы пишете по очереди. Начинает человек, а ты продолжаешь. "
    "Если это уместно, ты можешь добавлять в историю диалог между персонажами. "
    "Диалоги пиши с новой строки и отделяй тире. "
    "Не пиши никакого пояснительного текста в начале, а просто логично продолжай историю."
)

TOKEN = config.iam_token  # Токен для доступа к YandexGPT изменяется каждые 12 часов
FOLDER_ID = config.folder_id  # Folder_id для доступа к YandexGPT

# Подсчитывает количество токенов в сессии
# messages - все промты из указанной сессии
def count_tokens(messages: sqlite3.Row):
    headers = {
        'Authorization': f'Bearer {TOKEN}',
        'Content-Type': 'application/json'
    }
    data = {
       "modelUri": f"gpt://{FOLDER_ID}/yandexgpt/latest",
       "maxTokens": MAX_MODEL_TOKENS,
       "messages": []
    }

        # Проходимся по всем сообщениям и добавляем их в список
    for row in messages:
        data["messages"].append(
            {
                "role": row["role"],
                "text": row["content"]
            }
        )


    return len(
        requests.post(
            "https://llm.api.cloud.yandex.net/foundationModels/v1/tokenizeCompletion",
            json=data,
            headers=headers
        ).json()["tokens"]
    )


# Функция получает идентификатор пользователя, чата и самого бота, чтобы иметь возможность отправлять сообщения
def is_tokens_limit(user_id, chat_id, tokens, bot):
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
def ask_gpt(text, role, mode='continue'):
    """Запрос к Yandex GPT"""

    if expires_at < time.time():
        global FOLDER_ID
        FOLDER_ID = create_new_token()

    # Добавление инструкций в зависимости от режима работы
    if mode == 'continue':
        text += '\n' + CONTINUE_STORY
    elif mode == 'end':
        text += '\n' + END_STORY

    # URL для запроса к YandexGPT
    url = f"https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

    # Заголовки запроса, включая токен авторизации
    headers = {
        'Authorization': f'Bearer {TOKEN}',
        'Content-Type': 'application/json'
    }

    data = {
        "modelUri": f"gpt://{FOLDER_ID}/{GPT_MODEL}/latest",
        "completionOptions": {
            "stream": False,
            "temperature": MODEL_TEMPERATURE,
            "maxTokens": MAX_MODEL_TOKENS
        },
        "messages": [
            {"role": "system", "text": role}, #роль нейросети в диалоге
            {"role": "user", "text": text}, #задание от пользователя
            # Можно продолжить диалог
            {"role": "assistant", "text": ""}
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code != 200:
            logging.debug(f"Response {response.json()} Status code:{response.status_code} Message {response.text}")
            result = f"Status code {response.status_code}. Подробности см. в журнале."
            return result
        print("\n\nТУТ", response.json(), "ТУТ\n\n")
        result = response.json()['result']['alternatives'][0]['message']['text']
        logging.info(f"Request: {response.request.url}\n"
                     f"Response: {response.status_code}\n"
                     f"Response Body: {response.text}\n"
                     f"Processed Result: {result}")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        result = "Произошла непредвиденная ошибка. Подробности см. в журнале."

    return result