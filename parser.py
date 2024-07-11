import vk_api
import yt_dlp
import yaml
import re
import time
import asyncio
from telethon import TelegramClient
from telethon.errors import PeerFloodError
from telethon.tl.functions.messages import SendMessageRequest

# Загружаем конфигурацию из YAML-файла
with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# Инициализируем VK API
vk_session = vk_api.VkApi(token=config["vk_token"])
vk = vk_session.get_api()

# Инициализируем Telegram Client
client = TelegramClient("session_name", config["api_id"], config["api_hash"])


# Функция для получения постов ВКонтакте
def get_vk_posts(count=config["req_count"], offset=0):
    """Получает посты ВКонтакте из указанной группы."""
    try:
        posts = vk.wall.get(owner_id=config["vk_owner_id"], count=count, offset=offset)
        return posts["items"]
    except vk_api.exceptions.ApiError as e:
        print(f"Ошибка VK API: {e}")
        return []


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
    except Exception as e:
        print(f"Ошибка при отправке сообщения в Telegram: {e}")


# Основная функция
async def main():
    """Основная функция для парсера."""
    await client.start(phone=config["tg_phone_number"])

    # Проверяем, авторизован ли клиент
    if not await client.is_user_authorized():
        print("Не удалось авторизоваться в Telegram.")
        return

    while True:
        posts = get_vk_posts()
        for post in posts:
            try:
                await send_message(
                    config["tg_channel"], f"**Новый пост из VK:**\n\n{post['text']}"
                )
            except Exception as e:
                print(f"Ошибка при отправке поста в Telegram: {e}")

        # Завершаем цикл, если single_start установлен в True
        if config["single_start"]:
            break

        time.sleep(config["time_to_sleep"])


if __name__ == "__main__":
    asyncio.run(main())

