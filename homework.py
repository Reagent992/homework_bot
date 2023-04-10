import logging
import os
import time
from http import HTTPStatus
from logging.handlers import RotatingFileHandler

import requests
import telegram
from dotenv import load_dotenv

load_dotenv()

PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}
HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    '%(asctime)s [%(levelname)s] [%(lineno)d строка]  %(message)s '
)
log_files_handler = RotatingFileHandler(
    'custom_logger.log', maxBytes=2000000, backupCount=5, encoding='utf-8')
log_files_handler.setFormatter(formatter)
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.DEBUG)
stream_handler.setFormatter(formatter)
logger.addHandler(log_files_handler)
logger.addHandler(stream_handler)


class HttpCodeIsNot200(Exception):
    """Неверный HTTP  код."""

    pass


def check_tokens() -> bool:
    """Проверяем доступность необходимых переменных окружения."""
    logger.debug('Запущена проверка необходимых переменных окружения')
    return all([PRACTICUM_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_TOKEN])


def send_message(bot: telegram.Bot, message: str) -> None:
    """Отправляет сообщение в Telegram чат."""
    try:
        logger.debug('Запущена отправка сообщения в Telegram')
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        logger.info(f'Сообщение {message} отправлено на №{TELEGRAM_CHAT_ID}')
    except telegram.error.TelegramError as e:
        logger.error(f'Неудачная отправка сообщения: {message} ошибка {e}')


def get_api_answer(timestamp: int) -> dict:
    """Запрос к ЯП API."""
    payload = {'from_date': timestamp}
    try:
        logger.debug('Отправка запроса к API')
        response = requests.get(url=ENDPOINT, params=payload, headers=HEADERS)
        if response.status_code != HTTPStatus.OK:
            raise HttpCodeIsNot200('Неподходящий http ответ')
        logger.debug('Получен ответ от API, переход к десериализации')
        return response.json()

    except requests.JSONDecodeError:
        msg = 'Ошибка при десериализации JSON'
        raise requests.JSONDecodeError(msg)


def check_response(response: dict):
    """Проверяет ответ API. Возвращает домашку если она есть."""
    logger.debug('Проверка ответа API')
    if not isinstance(response, dict):
        msg = 'Ответ API не является словарем'
        raise TypeError(msg)
    homeworks = response.get('homeworks')
    if not response.get('current_date'):
        raise KeyError('В ответе API нехватает ключа current_date')
    logger.debug('Извлечение домашки из ответа API')
    if homeworks is not None and isinstance(homeworks, list):
        if homeworks:
            logger.debug('Успешная проверка ответа API, домашка есть =)')
            return homeworks[0]
        else:
            logger.debug('Успешная проверка ответа API, домашки нет =(')
            return None
    else:
        msg = ('Неверный ответ API, в словаре нет ключа homeworks или '
               'homeworks не является list()')
        raise TypeError(msg)


def parse_status(homework):
    """Извлекает статус Домашки, возвращает строку-статус."""
    logger.debug('Начало работы parse_status()')
    homework_name = homework.get('homework_name')
    homework_status = homework.get('status')
    if homework_name and homework_status:
        logger.debug('В словаре-домашки правильные ключи.')

        if homework_status in HOMEWORK_VERDICTS:
            logger.debug('В словаре-домашки подходящий статус')
            verdict = HOMEWORK_VERDICTS[homework_status]
        else:
            raise ValueError('Неожиданный статус домашки')

        message = (f'Изменился статус проверки работы '
                   f'"{homework_name}". {verdict}')
        logger.info(message)
        return message
    else:
        raise KeyError('Неверные ключи в словаре домашки')


def main():
    """Основная логика работы бота."""
    if not check_tokens():
        msg = 'Отсутствуют переменные окружения'
        logger.critical(msg)
        raise NameError(msg)

    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    timestamp = int(time.time())
    last_check_time = None
    last_homework_status = None
    last_telegram_message = None

    while True:
        try:
            logger.debug("Начало цикла работы бота.")
            response = get_api_answer(last_check_time or timestamp)
            homework = check_response(response)
            if homework:
                # Дата последней проверки(станет датой следующей проверки)
                last_check_time = response['current_date']
                message = parse_status(homework)
                if message != last_homework_status:
                    logger.debug('Новая домашка, отправляем сообщение')
                    # Сохраняем последний статус домашки
                    last_homework_status = homework['status']
                    send_message(bot, message)
                else:
                    logger.info('Старая домашка, идем спать.')
            logger.info('Нету домашки, идем спать.')

        except Exception as error:
            logger.error(error)
            message = f'Сбой в работе программы: {error}'
            if message != last_telegram_message:
                send_message(bot, message)
                # Сохраняем последнее отправленное сообщение
                last_telegram_message = message

        finally:
            time.sleep(RETRY_PERIOD)
            logger.debug("Конец цикла работы бота. Прошло 10 минут.")


if __name__ == '__main__':
    main()
