import vk_api
import telethon
import yt_dlp
import yaml
import re
import time
import asyncio
from telethon import TelegramClient, events
from telethon.errors import PeerFloodError, UserPrivacyRestrictedError
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty, InputPeerChannel, InputPeerUser
from telethon.errors.rpcerrorlist import (
    PeerFloodError,
    UserPrivacyRestrictedError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
    FloodWaitError,
    UserBotError,
)

with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

# Инициализация VK API
vk_session = vk_api.VkApi(token=config["vk_token"])
vk = vk_session.get_api()

# Инициализация Telegram Client
client = TelegramClient("anon", config["api_id"], config["api_hash"])
client.connect()


# Функции для работы с VK
def get_vk_posts(count=config["req_count"], offset=0):
    """Получение постов ВКонтакте."""
    posts = vk.wall.get(domain=config["vk_domain"], count=count, offset=offset)
    return posts["items"]


def get_vk_post_by_id(post_id):
    """Получение поста ВКонтакте по ID."""
    post = vk.wall.getById(posts=post_id)
    return post[0]


def get_vk_comments(post_id):
    """Получение комментариев к посту ВКонтакте."""
    comments = vk.wall.getComments(
        owner_id=config["vk_group_id"], post_id=post_id, count=10
    )
    return comments["items"]


# Функции для работы с Telegram
def send_message(channel, message):
    """Отправка сообщения в Telegram канал."""
    client.send_message(entity=channel, message=message)


def send_photo(channel, photo_url):
    """Отправка фото в Telegram канал."""
    client.send_file(entity=channel, file=photo_url)


def send_video(channel, video_url, caption=None):
    """Отправка видео в Telegram канал."""
    client.send_file(entity=channel, file=video_url, caption=caption)


# Функции для обработки контента
def check_blacklist(text, blacklist):
    """Проверяет текст на наличие слов из блэклиста с учётом различных форм."""
    for word in blacklist:
        pattern = r"\b" + re.escape(word) + r"\b"
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def check_whitelist(text, whitelist):
    """Проверяет текст на наличие слов из вайтлиста с учётом различных форм."""
    for word in whitelist:
        pattern = r"\b" + re.escape(word) + r"\b"
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def check_author_comment(comment, blacklist):
    """Проверяет комментарий автора на наличие ссылок из блэклиста."""
    for word in blacklist:
        if word in comment:
            return True
    return False


def format_links(text, publish_as_hyperlinks):
    """Форматирует ссылки в тексте."""
    if publish_as_hyperlinks:
        # Форматирует ссылки как гиперссылки
        return text
    else:
        # Форматирует ссылки как обычный текст
        return text.replace("https://", "https://").replace("t.me/", "t.me/")


def download_video(video_url):
    """Скачивает видео с помощью yt_dlp."""
    with yt_dlp.YoutubeDL({"outtmpl": "%(id)s.%(ext)s"}) as ydl:
        try:
            ydl.download([video_url])
            return ydl.prepare_filename(video_url)
        except Exception as e:
            print(f"Ошибка при скачивании видео: {e}")
            return None


def process_post(post):
    """Обработка поста: фильтрация, скачивание видео, добавление подписи"""
    text = post["text"]

    # Проверка блэклиста и вайтлиста
    if check_blacklist(text, config["blacklist"]):
        return None
    if not check_whitelist(text, config["whitelist"]):
        return None

    # Проверка на репост
    if (
        config["skip_reposts"]
        and "copy_history" in post
        and len(post["copy_history"]) > 0
    ):
        return None

    # Проверка на рекламный пост
    if (
        config["skip_ads_posts"]
        and "marked_as_ads" in post
        and post["marked_as_ads"] == 1
    ):
        return None

    # Проверка на защищённый авторским правом пост
    if (
        config["skip_copyrighted_posts"]
        and "can_publish" in post
        and not post["can_publish"]
    ):
        return None

    # Обработка видео
    if config["download_video"] and "attachments" in post:
        for attachment in post["attachments"]:
            if attachment["type"] == "video":
                video_url = attachment["video"]["player"]
                video_path = download_video(video_url)
                if video_path:
                    text += f"\n\nВидео: {video_url}"
                    return {"text": text, "video_path": video_path}

    # Добавление подписи
    if config["default_signature"]:
        if config["signature_format"] == "markdown":
            text += f"\n\n{config['default_signature']}"
        else:
            text += f"\n{config['default_signature']}"

    # Форматирование ссылок
    text = format_links(text, config["publish_links_as_hyperlinks"])

    return {"text": text}


def process_comment(comment):
    """Обработка комментария: фильтрация, форматирование."""
    text = comment["text"]

    # Проверка блэклиста
    if check_blacklist(text, config["blacklist"]):
        return None

    # Проверка вайтлиста
    if not check_whitelist(text, config["whitelist"]):
        return None

    # Проверка на наличие ссылок в комментариях
    if config["skip_comments_with_links"] and check_author_comment(
        text, config["author_comment_blacklist"]
    ):
        return None

    # Форматирование ссылок
    text = format_links(text, config["publish_links_as_hyperlinks"])

    return {"text": text}


async def main():
    """Основная функция парсера."""
    channel = config["tg_channel"]

    if not await client.is_user_authorized():
        client.send_code_request(config["tg_phone_number"])
        client.sign_in(config["tg_phone_number"], input("Enter the code: "))

    while True:
        posts = get_vk_posts()
        for post in posts:
            try:
                processed_post = process_post(post)

                if processed_post:
                    if "video_path" in processed_post:
                        send_video(
                            channel,
                            processed_post["video_path"],
                            caption=processed_post["text"],
                        )
                    else:
                        send_message(channel, processed_post["text"])

                # Обработка комментариев к посту
                comments = get_vk_comments(post["id"])
                for comment in comments:
                    processed_comment = process_comment(comment)
                    if processed_comment:
                        send_message(
                            channel, f"**Комментарий:** {processed_comment['text']}"
                        )

            except Exception as e:
                print(f"Ошибка при обработке поста: {e}")

        # Завершение цикла при single_start
        if config["single_start"]:
            break

        time.sleep(config["time_to_sleep"])


if __name__ == "__main__":
    asyncio.run(main())
