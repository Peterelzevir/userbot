# config.py
from telethon.sync import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError, 
    AuthKeyUnregisteredError, 
    AuthKeyError,
    UserDeactivatedBanError
)
from telethon.sessions import StringSession
import json
import os
from datetime import datetime, timedelta
import asyncio

# Basic Configuration
API_ID = "23207350"
API_HASH = "03464b6c80a5051eead6835928e48189"
BOT_TOKEN = "7822772930:AAG88QFjM--u8sICAMZXQfRBCLczbTcf_fU"
ADMIN_IDS = [5988451717]
APP_VERSION = "ᴜꜱᴇʀʙᴏᴛ ʙʏ ʜɪʏᴀᴏᴋ"

# Database Configuration
DB_FILE = "userbot_data.json"

# Monitoring Configuration
CHECK_INTERVAL = 60  # 1 minute in seconds
MAX_RETRIES = 2
RETRY_DELAY = 10  # 10 seconds between retries

# Bot instance for notifications
admin_bot = None

def load_data():
    """Load data from database file"""
    try:
        if os.path.exists(DB_FILE):
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {'userbots': {}, 'banned_groups': {}}
    except Exception as e:
        print(f"Error loading database: {str(e)}")
        return {'userbots': {}, 'banned_groups': {}}

def save_data(data):
    """Save data to database file"""
    try:
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving database: {str(e)}")

async def notify_admin(message):
    """Send notification to all admin users"""
    if admin_bot:
        for admin_id in ADMIN_IDS:
            try:
                await admin_bot.send_message(admin_id, message, parse_mode='md')
            except Exception as e:
                print(f"Failed to notify admin {admin_id}: {str(e)}")

async def check_session_validity(user_id, info):
    """Check if a userbot session is still valid"""
    retries = 0
    while retries < MAX_RETRIES:
        try:
            client = TelegramClient(StringSession(info['session']), API_ID, API_HASH)
            await client.connect()
            
            if not await client.is_user_authorized():
                raise AuthKeyUnregisteredError("Session unauthorized")
                
            # Test basic functionality
            me = await client.get_me()
            if not me:
                raise Exception("Failed to get user info")
                
            await client.disconnect()
            return True
            
        except (AuthKeyUnregisteredError, AuthKeyError, UserDeactivatedBanError):
            # Session is definitely invalid
            return False
            
        except Exception as e:
            print(f"Error checking session {user_id} (attempt {retries + 1}/{MAX_RETRIES}): {str(e)}")
            retries += 1
            if retries < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY)
            
    return False

async def monitor_sessions():
    """Monitor all userbot sessions and handle invalid ones"""
    while True:
        try:
            data = load_data()
            sessions_to_remove = []

            for user_id, info in data['userbots'].items():
                if not await check_session_validity(user_id, info):
                    # If session is invalid, try one more time after a short delay
                    await asyncio.sleep(5)
                    if not await check_session_validity(user_id, info):
                        notification = f"""
⚠️ **Session Terputus!**

👤 **Detail Userbot:**
• Nama: `{info['first_name']}`
• ID: `{user_id}`
• Phone: `{info['phone']}`
• Status: `{'Aktif' if info['active'] else 'Nonaktif'}`
• Dibuat: `{datetime.fromisoformat(info['created_at']).strftime('%Y-%m-%d %H:%M:%S')}`
• Expired: `{datetime.fromisoformat(info['expires_at']).strftime('%Y-%m-%d %H:%M:%S')}`

🔄 **Tindakan:** Session telah dihapus dari database secara otomatis.
                        """
                        sessions_to_remove.append((user_id, notification))

            # Remove invalid sessions and notify admins
            for user_id, notification in sessions_to_remove:
                try:
                    # Clean up session file if exists
                    session = StringSession(data['userbots'][user_id]['session'])
                    session_file = f"{session}.session"
                    if os.path.exists(session_file):
                        os.remove(session_file)
                except Exception as e:
                    print(f"Error cleaning up session file for user {user_id}: {str(e)}")

                # Remove from database
                del data['userbots'][user_id]
                
                # Notify admin
                await notify_admin(notification)

            if sessions_to_remove:
                save_data(data)

        except Exception as e:
            print(f"Error in session monitoring: {str(e)}")

        # Wait before next check
        await asyncio.sleep(CHECK_INTERVAL)

def check_expiry():
    """Check and handle expired userbot sessions"""
    try:
        data = load_data()
        current_time = datetime.now()
        changes_made = False
        
        for user_id, info in list(data['userbots'].items()):
            if info['active']:
                expiry = datetime.fromisoformat(info['expires_at'])
                if current_time > expiry:
                    info['active'] = False
                    changes_made = True
                    
                    # Send notification to userbot
                    try:
                        client = TelegramClient(StringSession(info['session']), API_ID, API_HASH)
                        with client:
                            client.send_message('me', """
⚠️ **Userbot Expired!**
Your userbot has expired. Please contact @hiyaok to extend your subscription.
Thank you for using our service! 🙏
""", parse_mode='md')
                    except Exception as e:
                        print(f"Failed to send expiry notification to user {user_id}: {str(e)}")
        
        if changes_made:
            save_data(data)
            
    except Exception as e:
        print(f"Error in expiry check: {str(e)}")

def start_session_monitor(bot):
    """Initialize and start the session monitoring"""
    global admin_bot
    admin_bot = bot
    asyncio.create_task(monitor_sessions())
