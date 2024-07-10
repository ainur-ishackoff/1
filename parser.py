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
from telethon.tl.functions.messages import SendMessageRequest
from telethon.tl.types import InputPeerUser, InputPeerChat, InputPeerChannel

# Загружаем конфигурацию из YAML-файла
with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# Инициализируем VK API
vk_session = vk_api.VkApi(token=config["vk_token"])
vk = vk_session.get_api()

# Инициализируем Telegram Client
client = TelegramClient("anon", config["api_id"], config["api_hash"])


# Функция для получения постов ВКонтакте
def get_vk_posts(count=config["req_count"], offset=0):
    """Получает посты ВКонтакте из указанной группы."""
    posts = vk.wall.get(domain=config["vk_domain"], count=count, offset=offset)
    return posts["items"]


# Функция для получения поста ВКонтакте по ID
def get_vk_post_by_id(post_id):
    """Получает пост ВКонтакте по его ID."""
    post = vk.wall.getById(posts=post_id)
    return post[0]


# Функция для получения комментариев к посту ВКонтакте
def get_vk_comments(post_id):
    """Получает комментарии к посту ВКонтакте."""
    comments = vk.wall.getComments(
        owner_id=config["vk_group_id"], post_id=post_id, count=10
    )
    return comments["items"]


# Функция для отправки сообщения в Telegram-канал
async def send_message(channel, message):
    """Отправляет сообщение в Telegram-канал с помощью бота."""
    try:
        if isinstance(channel, str):
            channel = await client.get_input_entity(channel)

        await client(SendMessageRequest(peer=channel, message=message))

    except PeerFloodError:
        print("Слишком много сообщений. Ожидание...")
        time.sleep(60)
        await send_message(channel, message)


# Функция для отправки фотографии в Telegram-канал
async def send_photo(channel, photo_url):
    """Отправляет фотографию в Telegram-канал с помощью бота."""
    try:
        if isinstance(channel, str):
            channel = await client.get_input_entity(channel)

        await client.send_file(entity=channel, file=photo_url)
    except PeerFloodError:
        print("Слишком много сообщений. Ожидание...")
        time.sleep(60)
        await send_photo(channel, photo_url)


# Функция для отправки видео в Telegram-канал
async def send_video(channel, video_path, caption=None):
    """Отправляет видео в Telegram-канал с помощью бота."""
    try:
        if isinstance(channel, str):
            channel = await client.get_input_entity(channel)

        await client.send_file(entity=channel, file=video_path, caption=caption)
    except PeerFloodError:
        print("Слишком много сообщений. Ожидание...")
        time.sleep(60)
        await send_video(channel, video_path, caption)


# Функция для проверки, содержит ли текст слова из черного списка
def check_blacklist(text, blacklist):
    """Проверяет, содержит ли текст слова из черного списка."""
    for word in blacklist:
        pattern = r"\b" + re.escape(word) + r"\b"
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


# Функция для проверки, содержит ли текст слова из белого списка
def check_whitelist(text, whitelist):
    """Проверяет, содержит ли текст слова из белого списка."""
    for word in whitelist:
        pattern = r"\b" + re.escape(word) + r"\b"
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


# Функция для проверки, содержит ли комментарий ссылки из черного списка
def check_author_comment(comment, blacklist):
    """Проверяет, содержит ли комментарий автора ссылки из черного списка."""
    for word in blacklist:
        if word in comment:
            return True
    return False


# Функция для форматирования ссылок в тексте
def format_links(text, publish_as_hyperlinks):
    """Форматирует ссылки в тексте как гиперссылки или обычный текст."""
    if publish_as_hyperlinks:
        # Форматирует ссылки как гиперссылки
        return text
    else:
        # Форматирует ссылки как обычный текст
        return text.replace("https://", "https://").replace("t.me/", "t.me/")


# Функция для загрузки видео с помощью yt_dlp
def download_video(video_url):
    """Загружает видео с помощью yt_dlp."""
    with yt_dlp.YoutubeDL({"outtmpl": "%(id)s.%(ext)s"}) as ydl:
        try:
            ydl.download([video_url])
            return ydl.prepare_filename(video_url)
        except Exception as e:
            print(f"Ошибка при загрузке видео: {e}")
            return None


# Функция для обработки поста ВКонтакте
def process_post(post):
    """Обрабатывает пост ВКонтакте: фильтрация, загрузка видео, добавление подписи."""
    text = post["text"]

    # Проверка черного и белого списков
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

    # Проверка на рекламу
    if (
        config["skip_ads_posts"]
        and "marked_as_ads" in post
        and post["marked_as_ads"] == 1
    ):
        return None

    # Проверка на авторские права
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


# Функция для обработки комментария ВКонтакте
def process_comment(comment):
    """Обрабатывает комментарий ВКонтакте: фильтрация, форматирование."""
    text = comment["text"]

    # Проверка черного списка
    if check_blacklist(text, config["blacklist"]):
        return None

    # Проверка белого списка
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


# Основная функция
async def main():
    """Основная функция для парсера."""
    bot_token = config["tg_bot_token"]
    channel = config["tg_channel"]

    await client.connect()

    # Проверяем, авторизован ли клиент
    if not await client.is_user_authorized():
        await client.send_code_request(config["tg_phone_number"])
        try:
            await client.sign_in(config["tg_phone_number"], input("Введите код: "))
        except Exception as e:
            print(f"Ошибка авторизации: {e}")
            return

    while True:
        posts = get_vk_posts()
        for post in posts:
            try:
                processed_post = process_post(post)

                if processed_post:
                    if "video_path" in processed_post:
                        await send_video(
                            channel,
                            processed_post["video_path"],
                            caption=processed_post["text"],
                        )
                    else:
                        await send_message(channel, processed_post["text"])

                # Обрабатываем комментарии к посту
                comments = get_vk_comments(post["id"])
                for comment in comments:
                    processed_comment = process_comment(comment)
                    if processed_comment:
                        await send_message(
                            channel, f"**Комментарий:** {processed_comment['text']}"
                        )

            except Exception as e:
                print(f"Ошибка при обработке поста: {e}")

        # Завершаем цикл, если single_start установлен в True
        if config["single_start"]:
            break

        time.sleep(config["time_to_sleep"])


if __name__ == "__main__":
    asyncio.run(main())
