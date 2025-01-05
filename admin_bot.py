from telethon import TelegramClient, events, Button, types
from telethon.tl.functions.users import GetFullUserRequest
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
from config import API_ID, API_HASH, BOT_TOKEN, ADMIN_IDS, APP_VERSION
import asyncio
from datetime import datetime, timedelta
import os
import math
import json
import logging
import re

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def load_data():
    """Load data from JSON file with error handling"""
    try:
        with open('data.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            default_data = {
                'userbots': {},
                'premium_users': {},
                'users': {}
            }
            for key, value in default_data.items():
                if key not in data:
                    data[key] = value
            return data
    except FileNotFoundError:
        return {'userbots': {}, 'premium_users': {}, 'users': {}}
    except json.JSONDecodeError:
        logger.error("Invalid JSON in data.json")
        return {'userbots': {}, 'premium_users': {}, 'users': {}}

def save_data(data):
    """Save data to JSON file with error handling"""
    try:
        with open('data.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error saving data: {str(e)}")
        return False

def is_premium(user_id):
    """Check if user has premium status"""
    data = load_data()
    str_id = str(user_id)
    if str_id in data.get('premium_users', {}):
        try:
            expiry = datetime.fromisoformat(data['premium_users'][str_id]['expires_at'])
            if expiry > datetime.now():
                return True
            else:
                del data['premium_users'][str_id]
                save_data(data)
        except (ValueError, KeyError):
            pass
    return False

def save_user(user_id, username=None):
    """Save new user to database"""
    data = load_data()
    str_id = str(user_id)
    if str_id not in data['users']:
        data['users'][str_id] = {
            'id': user_id,
            'username': username,
            'first_seen': datetime.now().isoformat()
        }
        save_data(data)

class AdminBot:
    def __init__(self):
        self.bot = TelegramClient('admin_bot', API_ID, API_HASH)
        self.page_size = 10
        self.help_pages = {
            'main': {
                'text': """
📚 **Panduan Penggunaan Bot**

Silahkan pilih kategori bantuan di bawah ini:
                """,
                'buttons': [
                    [Button.inline("🤖 Manajemen Userbot", "help_userbot")],
                    [Button.inline("⚙️ Pengaturan", "help_settings")],
                    [Button.inline("❌ Tutup", "help_close")]
                ]
            },
            'userbot': {
                'text': """
🤖 **Panduan Manajemen Userbot**

**Perintah Tersedia:**
• `/start` - Memulai bot dan membuat userbot baru
• `/cek` - Mengecek status userbot (Admin)
• `/hapus` - Menghapus userbot
• `/help` - Menampilkan bantuan ini
• `/addpremium` - Menambahkan user premium (Admin)
• `/broadcast` - Mengirim pesan broadcast (Admin)

**Catatan:**
• Semua perintah mendukung awalan `/`, `!`, dan `.`
• User premium hanya dapat membuat 1 userbot
• Durasi userbot premium otomatis 30 hari
                """,
                'buttons': [
                    [Button.inline("◀️ Kembali", "help_main")],
                    [Button.inline("❌ Tutup", "help_close")]
                ]
            },
            'settings': {
                'text': """
⚙️ **Panduan Pengaturan**

**Fitur:**
• Toggle status userbot dengan sekali klik
• Konfirmasi sebelum penghapusan
• Pembersihan otomatis sesi yang tidak terpakai
• Pengecekan sesi ganda
• Manajemen user premium
• Sistem broadcast pesan

**Tips:**
• Selalu cek status sebelum membuat userbot baru
• Backup data secara berkala
• Monitor masa aktif userbot premium
                """,
                'buttons': [
                    [Button.inline("◀️ Kembali", "help_main")],
                    [Button.inline("❌ Tutup", "help_close")]
                ]
            }
        }

    async def start(self):
        """Start the bot and register all handlers"""
        
        @self.bot.on(events.NewMessage(pattern=r'(?i)[!/\.]start$'))
        async def start_handler(event):
            user_id = event.sender_id
            save_user(user_id, event.sender.username)
            
            if user_id in ADMIN_IDS:
                buttons = [
                    [Button.inline("🤖 Buat Userbot", "create_userbot")],
                    [Button.inline("👥 Add Premium", "add_premium")],
                    [Button.inline("📢 Broadcast", "broadcast")],
                    [Button.inline("❓ Bantuan", "help_main")]
                ]
                await event.reply("👋 **Halo admin!**\n\nSilahkan pilih menu:", buttons=buttons)
                return

            if is_premium(user_id):
                text = "👋 **Halo pengguna premium!**\n\nSilahkan pilih menu:"
            else:
                text = "👋 **Halo!**\n\nSilahkan pilih menu:"

            buttons = [
                [Button.inline("🤖 Buat Userbot", "create_userbot")],
                [Button.inline("❓ Bantuan", "help_main")]
            ]
            await event.reply(text, buttons=buttons)

        @self.bot.on(events.CallbackQuery(data="not_premium"))
        async def not_premium_handler(event):
            text = """
⚠️ **Akses Ditolak**

Anda tidak memiliki akses premium.
Silahkan hubungi admin untuk membeli userbot!
            """
            buttons = [[Button.inline("◀️ Kembali", "back_to_start")]]
            await event.edit(text, buttons=buttons)

        @self.bot.on(events.CallbackQuery(pattern=r'^broadcast$'))
        async def broadcast_button_handler(event):
            if event.sender_id not in ADMIN_IDS:
                await event.answer("⚠️ Hanya untuk admin!", alert=True)
                return

            await event.delete()
            msg = events.NewMessage.Event(
                message=types.Message(
                    id=0, peer_id=types.PeerUser(event.sender_id),
                    message="/broadcast"
                )
            )
            msg.pattern_match = re.match(r'(?i)[!/\.]broadcast$', "/broadcast")
            await broadcast_handler(msg)

        @self.bot.on(events.CallbackQuery(pattern=r'^add_premium$'))
        async def premium_button_handler(event):
            if event.sender_id not in ADMIN_IDS:
                await event.answer("⚠️ Hanya untuk admin!", alert=True)
                return

            await event.delete()
            msg = events.NewMessage.Event(
                message=types.Message(
                    id=0, peer_id=types.PeerUser(event.sender_id),
                    message="/addpremium"
                )
            )
            msg.pattern_match = re.match(r'(?i)[!/\.]addpremium$', "/addpremium")
            await add_premium_handler(msg)

        @self.bot.on(events.NewMessage(pattern=r'(?i)[!/\.]broadcast$'))
        async def broadcast_handler(event):
            if event.sender_id not in ADMIN_IDS:
                await event.reply("⚠️ **Maaf, perintah ini hanya untuk admin!**")
                return
            
            async with self.bot.conversation(event.chat_id) as conv:
                try:
                    await conv.send_message("📝 **Masukkan pesan broadcast:**")
                    msg = await conv.get_response(timeout=300)
                    
                    data = load_data()
                    success = 0
                    failed = 0
                    
                    progress_msg = await conv.send_message("📤 **Mengirim broadcast...**")
                    
                    total_users = len(data['users'])
                    for i, (user_id, _) in enumerate(data['users'].items(), 1):
                        try:
                            await self.bot.send_message(int(user_id), msg.text)
                            success += 1
                        except Exception as e:
                            logger.error(f"Broadcast error for {user_id}: {str(e)}")
                            failed += 1
                            continue
                        
                        if i % 5 == 0:  # Update progress every 5 users
                            await progress_msg.edit(f"📤 **Mengirim broadcast... ({i}/{total_users})**")
                        await asyncio.sleep(0.5)  # Delay to prevent flood

                    await progress_msg.edit(f"""
✅ **Broadcast selesai!**

📊 **Statistik:**
• Berhasil: `{success}`
• Gagal: `{failed}`
• Total: `{success + failed}`
                    """)
                except asyncio.TimeoutError:
                    await conv.send_message("❌ **Waktu habis! Silahkan kirim `/broadcast` untuk mencoba lagi.**")

        @self.bot.on(events.NewMessage(pattern=r'(?i)[!/\.]addpremium$'))
        async def add_premium_handler(event):
            if event.sender_id not in ADMIN_IDS:
                await event.reply("⚠️ **Maaf, perintah ini hanya untuk admin!**")
                return
            
            async with self.bot.conversation(event.chat_id) as conv:
                try:
                    await conv.send_message("📝 **Masukkan ID user yang akan ditambahkan sebagai premium:**")
                    user_id_msg = await conv.get_response(timeout=300)
                    user_id = user_id_msg.text.strip()
                    
                    try:
                        user_id = int(user_id)
                    except ValueError:
                        await conv.send_message("❌ **Error: User ID harus berupa angka!**")
                        return
                    
                    await conv.send_message("⏳ **Masukkan durasi premium (dalam hari):**")
                    duration_msg = await conv.get_response(timeout=300)
                    try:
                        duration = int(duration_msg.text.strip())
                    except ValueError:
                        await conv.send_message("❌ **Error: Durasi harus berupa angka!**")
                        return
                    
                    data = load_data()
                    expiry_date = (datetime.now() + timedelta(days=duration)).isoformat()
                    
                    data['premium_users'][str(user_id)] = {
                        'added_at': datetime.now().isoformat(),
                        'expires_at': expiry_date,
                        'added_by': event.sender_id
                    }
                    
                    if save_data(data):
                        # Notify user
                        try:
                            text = f"""
🎉 **Selamat! Anda telah mendapatkan akses premium!**

📅 **Detail:**
• Tanggal Mulai: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`
• Kadaluarsa: `{datetime.fromisoformat(expiry_date).strftime('%Y-%m-%d %H:%M:%S')}`
• Durasi: `{duration} hari`
                            """
                            await self.bot.send_message(user_id, text)
                            await conv.send_message(f"✅ **Berhasil menambahkan user `{user_id}` sebagai premium!**")
                        except Exception as e:
                            await conv.send_message(f"⚠️ **Berhasil menambahkan premium, tapi gagal mengirim notifikasi ke user:** `{str(e)}`")
                    else:
                        await conv.send_message("❌ **Gagal menyimpan data premium user!**")
                    
                except asyncio.TimeoutError:
                    await conv.send_message("❌ **Waktu habis! Silahkan kirim `/addpremium` untuk mencoba lagi.**")

        @self.bot.on(events.CallbackQuery(pattern=r'^create_userbot$'))
        async def create_userbot_handler(event):
            user_id = event.sender_id
            
            if user_id not in ADMIN_IDS:
                if not is_premium(user_id):
                    await not_premium_handler(event)
                    return
                
                data = load_data()
                for info in data['userbots'].values():
                    if str(info.get('owner_id')) == str(user_id):
                        text = f"""
⚠️ **Anda sudah memiliki userbot!**

🤖 **Detail Userbot:**
• Nama: `{info['first_name']}`
• Status: {"🟢 Aktif" if info['active'] else "🔴 Nonaktif"}
• Dibuat: `{datetime.fromisoformat(info['created_at']).strftime('%Y-%m-%d %H:%M:%S')}`
• Kadaluarsa: `{datetime.fromisoformat(info['expires_at']).strftime('%Y-%m-%d %H:%M:%S')}`
                        """
                        buttons = [[Button.inline("◀️ Kembali", "back_to_start")]]
                        await event.edit(text, buttons=buttons)
                        return

            async with self.bot.conversation(event.chat_id) as conv:
                try:
                    await event.delete()
                    await conv.send_message("📝 **Masukkan API ID:**")
                    api_id_msg = await conv.get_response(timeout=300)
                    api_id = api_id_msg.text.strip()

                    await conv.send_message("📝 **Masukkan API Hash:**")
                    api_hash_msg = await conv.get_response(timeout=300)
                    api_hash = api_hash_msg.text.strip()

                    await conv.send_message("📱 **Masukkan nomor telepon:**")
                    phone_msg = await conv.get_response(timeout=300)
                    phone = phone_msg.text.strip()

                    duration = 30 if user_id not in ADMIN_IDS else None
                    if duration is None:
                        await conv.send_message("⏳ **Masukkan durasi aktif userbot (dalam hari):**")
                        duration_msg = await conv.get_response(timeout=300)
                        try:
                            duration = int(duration_msg.text.strip())
                        except ValueError:
                            await conv.send_message("❌ **Error: Durasi harus berupa angka!**")
                            return

                    await self.create_new_userbot(conv, phone, api_id, api_hash, duration, user_id)
                    
                except asyncio.TimeoutError:
                    await conv.send_message("❌ **Waktu habis! Silahkan kirim `/start` untuk mencoba lagi.**")
                except Exception as e:
                    await conv.send_message(f"❌ **Error:** `{str(e)}`")

        @self.bot.on(events.NewMessage(pattern=r'(?i)[!/\.]cek$'))
        async def check_userbot_handler(event):
            if event.sender_id not in ADMIN_IDS:
                await event.reply("⚠️ **Maaf, perintah ini hanya untuk admin!**")
                return
                
            await self.show_userbot_list(event, page=0)

        @self.bot.on(events.CallbackQuery(pattern=r'^page_(\d+)'))
        async def page_callback(event):
            if event.sender_id not in ADMIN_IDS:
                return
                
            page = int(event.data.decode().split('_')[1])
            await self.show_userbot_list(event, page)

        @self.bot.on(events.NewMessage(pattern=r'(?i)[!/\.]hapus$'))
        async def delete_userbot_handler(event):
            user_id = event.sender_id
            data = load_data()
            
            if user_id in ADMIN_IDS:
                if not data['userbots']:
                    await event.reply("❌ **Tidak ada userbot yang ditemukan!**")
                    return
                    
                await self.show_delete_list(event, page=0)
            else:
                user_bot = None
                for bot_id, info in data['userbots'].items():
                    if str(info.get('owner_id')) == str(user_id):
                        user_bot = (bot_id, info)
                        break
                
                if not user_bot:
                    await event.reply("❌ **Anda tidak memiliki userbot yang aktif!**")
                    return
                
                bot_id, info = user_bot
                text = f"""
⚠️ **Konfirmasi Penghapusan Userbot**

👤 **Detail Userbot:**
• Nama: `{info['first_name']}`
• Status: {"🟢 Aktif" if info['active'] else "🔴 Nonaktif"}
• Dibuat: `{datetime.fromisoformat(info['created_at']).strftime('%Y-%m-%d %H:%M:%S')}`
• Kadaluarsa: `{datetime.fromisoformat(info['expires_at']).strftime('%Y-%m-%d %H:%M:%S')}`

❓ **Apakah Anda yakin ingin menghapus userbot ini?**
                """
                buttons = [
                    [
                        Button.inline("✅ Ya, Hapus", f"confirm_delete_{bot_id}"),
                        Button.inline("❌ Tidak", "back_to_start")
                    ]
                ]
                await event.reply(text, buttons=buttons)

        async def show_delete_list(self, event, page=0):
            """Show list of userbots for deletion"""
            data = load_data()
            
            text = """
❌ **Hapus Userbot**

Silahkan pilih userbot yang ingin dihapus:
            """
            
            userbots = list(data['userbots'].items())
            total_pages = math.ceil(len(userbots) / self.page_size)
            start_idx = page * self.page_size
            end_idx = start_idx + self.page_size
            current_page_userbots = userbots[start_idx:end_idx]

            buttons = []
            for user_id, info in current_page_userbots:
                status = "🟢" if info['active'] else "🔴"
                button_text = f"{status} {info['first_name']} ({user_id})"
                buttons.append([Button.inline(button_text, f"delete_{user_id}")])

            nav_buttons = []
            if page > 0:
                nav_buttons.append(Button.inline("⬅️ Kembali", f"delete_page_{page-1}"))
            if page < total_pages - 1:
                nav_buttons.append(Button.inline("Lanjut ➡️", f"delete_page_{page+1}"))
            if nav_buttons:
                buttons.append(nav_buttons)

            buttons.append([Button.inline("❌ Tutup", "help_close")])

            if event.message:
                await event.reply(text, buttons=buttons)
            else:
                await event.edit(text, buttons=buttons)

        @self.bot.on(events.CallbackQuery(pattern=r'^delete_(\d+)'))
        async def delete_confirmation_callback(event):
            user_id = event.sender_id
            if user_id not in ADMIN_IDS and not is_premium(user_id):
                return
                
            bot_id = event.data.decode().split('_')[1]
            data = load_data()
            
            if bot_id in data['userbots']:
                info = data['userbots'][bot_id]
                
                # Check if premium user is trying to delete someone else's userbot
                if user_id not in ADMIN_IDS:
                    if str(info.get('owner_id')) != str(user_id):
                        await event.answer("⚠️ Anda tidak dapat menghapus userbot milik orang lain!", alert=True)
                        return

                text = f"""
⚠️ **Konfirmasi Penghapusan Userbot**

👤 **Detail Userbot:**
• Nama: `{info['first_name']}`
• Status: {"🟢 Aktif" if info['active'] else "🔴 Nonaktif"}
• Phone: `{info['phone']}`

❓ **Apakah Anda yakin ingin menghapus userbot ini?**
                """
                buttons = [
                    [
                        Button.inline("✅ Ya, Hapus", f"confirm_delete_{bot_id}"),
                        Button.inline("❌ Tidak", "back_to_start")
                    ]
                ]
                await event.edit(text, buttons=buttons)

        @self.bot.on(events.CallbackQuery(pattern=r'^confirm_delete_(\d+)'))
        async def confirm_delete_callback(event):
            user_id = event.sender_id
            bot_id = event.data.decode().split('_')[2]
            data = load_data()
            
            if bot_id in data['userbots']:
                info = data['userbots'][bot_id]
                
                # Check permissions
                if user_id not in ADMIN_IDS:
                    if str(info.get('owner_id')) != str(user_id):
                        await event.answer("⚠️ Anda tidak dapat menghapus userbot milik orang lain!", alert=True)
                        return
                
                try:
                    # Clean up session
                    session = StringSession(info['session'])
                    if os.path.exists(f"{session}.session"):
                        os.remove(f"{session}.session")
                except Exception as e:
                    logger.error(f"Error cleaning up session: {str(e)}")
                
                # Remove from data
                del data['userbots'][bot_id]
                if save_data(data):
                    text = "✅ **Userbot berhasil dihapus!**"
                    buttons = [[Button.inline("◀️ Kembali ke Menu", "back_to_start")]]
                    await event.edit(text, buttons=buttons)
                else:
                    await event.edit("❌ **Gagal menghapus userbot!**")
            else:
                await event.edit("❌ **Userbot tidak ditemukan!**")

        @self.bot.on(events.CallbackQuery(data="back_to_start"))
        async def back_to_start_handler(event):
            """Handle back to start button"""
            await event.delete()
            # Simulate /start command
            message = event.original_update.msg_id
            await start_handler(await event.get_message())

        # Start the bot
        await self.bot.start(bot_token=BOT_TOKEN)
        return self.bot
