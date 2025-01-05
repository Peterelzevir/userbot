# coding by @hiyaok on telegram

from admin_bot import AdminBot
from userbot import Userbot
from config import *
import asyncio

async def main():
    # Create sessions directory if it doesn't exist
    if not os.path.exists('sessions'):
        os.makedirs('sessions')

    # Start admin bot
    admin_bot = AdminBot()
    bot = await admin_bot.start()
    
    # Start all active userbots
    data = load_data()
    for user_id, info in data['userbots'].items():
        if info['active']:
            userbot = Userbot(info['session'], API_ID, API_HASH)
            await userbot.start()
    
    # Run until disconnected
    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
