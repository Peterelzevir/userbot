# main.py
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
    active_bots = []
    for user_id, info in data['userbots'].items():
        if info['active']:
            try:
                userbot = Userbot(info['session'], API_ID, API_HASH)
                await userbot.start()
                active_bots.append(userbot)
                print(f"Started userbot for {user_id}")
            except Exception as e:
                print(f"Failed to start userbot {user_id}: {e}")
    
    try:
        print("Bot is running...")
        await bot.run_until_disconnected()
    finally:
        # Cleanup
        for userbot in active_bots:
            try:
                await userbot.client.disconnect()
            except:
                pass

if __name__ == '__main__':
    asyncio.run(main())
