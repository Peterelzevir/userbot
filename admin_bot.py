# admin_bot.py
from telethon import TelegramClient, events, Button
from telethon.tl.functions.users import GetFullUserRequest
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from config import *
import asyncio
from datetime import datetime, timedelta
import os
import math
import json

def load_data():
    try:
        with open('data.json', 'r') as f:
            data = json.load(f)
            if 'premium_users' not in data:
                data['premium_users'] = {}
            if 'users' not in data:
                data['users'] = {}
            if 'userbots' not in data:
                data['userbots'] = {}
            return data
    except FileNotFoundError:
        return {'userbots': {}, 'premium_users': {}, 'users': {}}

def save_data(data):
    with open('data.json', 'w') as f:
        json.dump(data, f, indent=4)

def is_premium(user_id):
    data = load_data()
    if str(user_id) in data.get('premium_users', {}):
        expiry = datetime.fromisoformat(data['premium_users'][str(user_id)]['expires_at'])
        if expiry > datetime.now():
            return True
        else:
            del data['premium_users'][str(user_id)]
            save_data(data)
    return False

def save_user(user_id, username=None):
    data = load_data()
    if str(user_id) not in data['users']:
        data['users'][str(user_id)] = {
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
                    [Button.inline("🤖 Manajemen Userbot", data="help_userbot")],
                    [Button.inline("⚙️ Pengaturan", data="help_settings")],
                    [Button.inline("❌ Tutup", data="help_close")]
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
                    [Button.inline("◀️ Kembali", data="help_main")],
                    [Button.inline("❌ Tutup", data="help_close")]
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
                    [Button.inline("◀️ Kembali", data="help_main")],
                    [Button.inline("❌ Tutup", data="help_close")]
                ]
            }
        }

    async def start(self):
        await self.bot.start(bot_token=BOT_TOKEN)

        @self.bot.on(events.NewMessage(pattern=r'(?i)[!/\.]start$'))
        async def start_handler(event):
            user_id = event.sender_id
            save_user(user_id, event.sender.username)
            
            if user_id in ADMIN_IDS:
                buttons = [
                    [Button.inline("🤖 Buat Userbot", data="create_userbot")],
                    [Button.inline("👥 Add Premium", data="add_premium")],
                    [Button.inline("📢 Broadcast", data="broadcast")],
                    [Button.inline("❓ Bantuan", data="help_main")]
                ]
                await event.reply("👋 **Halo admin!**\n\nSilahkan pilih menu:", buttons=buttons)
                return

            buttons = [
                [Button.inline("🤖 Buat Userbot", data="create_userbot")],
                [Button.inline("❓ Bantuan", data="help_main")]
            ]
            
            if is_premium(user_id):
                text = "👋 **Halo pengguna premium!**\n\nSilahkan pilih menu:"
            else:
                text = "👋 **Halo!**\n\nSilahkan pilih menu:"
            
            await event.reply(text, buttons=buttons)

        @self.bot.on(events.CallbackQuery(data="not_premium"))
        async def not_premium_handler(event):
            text = """
⚠️ **Akses Ditolak**

Anda tidak memiliki akses premium.
Silahkan hubungi @hiyaok untuk membeli userbot!
            """
            buttons = [[Button.inline("◀️ Kembali", data="back_to_start")]]
            await event.edit(text, buttons=buttons)

        @self.bot.on(events.CallbackQuery(data="back_to_start"))
        async def back_to_start_handler(event):
            await event.delete()
            # Simulate /start command
            message = event.original_update.msg_id
            await start_handler(await event.get_message())

        @self.bot.on(events.NewMessage(pattern=r'(?i)[!/\.]broadcast$'))
        async def broadcast_command(event):
            if event.sender_id not in ADMIN_IDS:
                return
            
            async with self.bot.conversation(event.chat_id) as conv:
                try:
                    await conv.send_message("📝 **Masukkan pesan broadcast:**")
                    msg = await conv.get_response(timeout=300)
                    
                    data = load_data()
                    success = 0
                    failed = 0
                    
                    await conv.send_message("📤 **Mengirim broadcast...**")
                    
                    for user_id in data['users']:
                        try:
                            await self.bot.send_message(int(user_id), msg.text)
                            success += 1
                        except:
                            failed += 1
                            continue
                        await asyncio.sleep(0.5)  # Delay to prevent flood

                    await conv.send_message(f"""
✅ **Broadcast selesai!**

📊 **Statistik:**
• Berhasil: `{success}`
• Gagal: `{failed}`
• Total: `{success + failed}`
                    """)
                except asyncio.TimeoutError:
                    await conv.send_message("❌ **Waktu habis! Silahkan kirim `/broadcast` untuk mencoba lagi.**")

        @self.bot.on(events.NewMessage(pattern=r'(?i)[!/\.]addpremium$'))
        async def add_premium_command(event):
            if event.sender_id not in ADMIN_IDS:
                return
            
            async with self.bot.conversation(event.chat_id) as conv:
                try:
                    await conv.send_message("📝 **Masukkan ID user yang akan ditambahkan sebagai premium:**")
                    user_id_msg = await conv.get_response(timeout=300)
                    user_id = user_id_msg.text.strip()
                    
                    await conv.send_message("⏳ **Masukkan durasi premium (dalam hari):**")
                    duration_msg = await conv.get_response(timeout=300)
                    duration = int(duration_msg.text)
                    
                    data = load_data()
                    expiry_date = (datetime.now() + timedelta(days=duration)).isoformat()
                    
                    data['premium_users'][user_id] = {
                        'added_at': datetime.now().isoformat(),
                        'expires_at': expiry_date
                    }
                    save_data(data)
                    
                    # Notify user
                    try:
                        text = f"""
🎉 **Selamat! Anda telah mendapatkan akses premium!**

📅 **Detail:**
• Tanggal Mulai: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`
• Kadaluarsa: `{datetime.fromisoformat(expiry_date).strftime('%Y-%m-%d %H:%M:%S')}`
                        """
                        await self.bot.send_message(int(user_id), text)
                    except:
                        pass
                    
                    await conv.send_message(f"✅ **Berhasil menambahkan user `{user_id}` sebagai premium!**")
                    
                except asyncio.TimeoutError:
                    await conv.send_message("❌ **Waktu habis! Silahkan kirim `/addpremium` untuk mencoba lagi.**")
                except ValueError:
                    await conv.send_message("❌ **Error: Durasi harus berupa angka!**")
                except Exception as e:
                    await conv.send_message(f"❌ **Error:** `{str(e)}`")

        @self.bot.on(events.CallbackQuery(data="create_userbot"))
        async def create_userbot_handler(event):
            user_id = event.sender_id
            
            # Check premium status for non-admin users
            if user_id not in ADMIN_IDS:
                if not is_premium(user_id):
                    await not_premium_handler(event)
                    return
                
                # Check if premium user already has a userbot
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
                        buttons = [[Button.inline("◀️ Kembali", data="back_to_start")]]
                        await event.edit(text, buttons=buttons)
                        return

            # Start userbot creation process
            async with self.bot.conversation(event.chat_id) as conv:
                try:
                    await event.delete()
                    # Get API ID
                    await conv.send_message("📝 **Masukkan API ID:**")
                    api_id_msg = await conv.get_response(timeout=300)
                    api_id = api_id_msg.text

                    # Get API Hash
                    await conv.send_message("📝 **Masukkan API Hash:**")
                    api_hash_msg = await conv.get_response(timeout=300)
                    api_hash = api_hash_msg.text

                    # Get phone number
                    await conv.send_message("📱 **Masukkan nomor telepon:**")
                    phone_msg = await conv.get_response(timeout=300)
                    phone = phone_msg.text

                    duration = 30 if user_id not in ADMIN_IDS else None
                    if duration is None:
                        await conv.send_message("⏳ **Masukkan durasi aktif userbot (dalam hari):**")
                        duration_msg = await conv.get_response(timeout=300)
                        duration = int(duration_msg.text)

                    await self.create_new_userbot(conv, phone, api_id, api_hash, duration, user_id)
                    
                except asyncio.TimeoutError:
                    await conv.send_message("❌ **Waktu habis! Silahkan kirim `/start` untuk mencoba lagi.**")

        async def create_new_userbot(self, conv, phone, api_id, api_hash, duration, owner_id):
            try:
                # Create client and connect
                client = TelegramClient(StringSession(), api_id, api_hash, device_model=APP_VERSION)
                await client.connect()
                
                await conv.send_message("⏳ **Memproses permintaan login...**")
                code = await client.send_code_request(phone)
                
                await conv.send_message("📲 **Masukkan kode OTP (format: 1 2 3 4 5):**")
                otp_msg = await conv.get_response(timeout=300)
                otp = ''.join(otp_msg.text.split())

                try:
                    await client.sign_in(phone=phone, code=otp, phone_code_hash=code.phone_code_hash)
                except SessionPasswordNeededError:
                    await conv.send_message("🔐 **Akun ini menggunakan verifikasi 2 langkah. Silahkan masukkan password:**")
                    password = await conv.get_response(timeout=300)
                    await client.sign_in(password=password.text)

                me = await client.get_me()
                
                # Save userbot data
                data = load_data()
                expiry_date = (datetime.now() + timedelta(days=duration)).isoformat()
                
                data['userbots'][str(me.id)] = {
                    'first_name': me.first_name,
                    'last_name': me.last_name,
                    'phone': phone,
                    'created_at': datetime.now().isoformat(),
                    'expires_at': expiry_date,
                    'active': True,
                    'session': client.session.save(),
                    'owner_id': owner_id
                }
                save_data(data)

                # Format response message
                response = f"""
🤖 **Userbot berhasil dibuat!**

👤 **Detail Userbot:**
• First Name: `{me.first_name}`
• Last Name: `{me.last_name or 'N/A'}`
• User ID: `{me.id}`
• Phone: `{phone}`
• Created: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`
• Expires: `{datetime.fromisoformat(expiry_date).strftime('%Y-%m-%d %H:%M:%S')}`
                """
                await conv.send_message(response, parse_mode='md')
                
            except asyncio.TimeoutError:
                await conv.send_message("❌ **Waktu habis! Silahkan kirim `/start` untuk mencoba lagi.**")
            except Exception as e:
                await conv.send_message(f"❌ **Error:** `{str(e)}`")

        @self.bot.on(events.NewMessage(pattern=r'(?i)[!/\.]help$'))
        async def help_handler(event):
            help_page = self.help_pages['main']
            await event.reply(help_page['text'], buttons=help_page['buttons'])

        @self.bot.on(events.CallbackQuery(pattern=r'^help_(\w+)'))
        async def help_callback(event):
            page = event.data.decode().split('_')[1]
            if page == 'close':
                await event.delete()
                return

            help_page = self.help_pages.get(page, self.help_pages['main'])
            await event.edit(help_page['text'], buttons=help_page['buttons'])

        @self.bot.on(events.NewMessage(pattern=r'(?i)[!/\.]cek$'))
        async def check_userbot_handler(event):
            if event.sender_id not in ADMIN_IDS:
                await event.reply("⚠️ **Maaf, perintah ini hanya untuk admin!**")
                return
                
            await self.show_userbot_list(event, page=0)

        async def show_userbot_list(self, event, page=0):
            data = load_data()
            if not data['userbots']:
                await event.reply("❌ **Tidak ada userbot yang ditemukan!**")
                return

            userbots = list(data['userbots'].items())
            total_pages = math.ceil(len(userbots) / self.page_size)
            start_idx = page * self.page_size
            end_idx = start_idx + self.page_size
            current_page_userbots = userbots[start_idx:end_idx]

            buttons = []
            for user_id, info in current_page_userbots:
                status = "🟢" if info['active'] else "🔴"
                button_text = f"{status} {info['first_name']} ({user_id})"
                buttons.append([Button.inline(button_text, data=f"toggle_{user_id}")])

            nav_buttons = []
            if page > 0:
                nav_buttons.append(Button.inline("⬅️ Kembali", data=f"page_{page-1}"))
            if page < total_pages - 1:
                nav_buttons.append(Button.inline("Lanjut ➡️", data=f"page_{page+1}"))
            if nav_buttons:
                buttons.append(nav_buttons)

            buttons.append([Button.inline("❓ Bantuan", data="help_main")])

            active_count = sum(1 for _, info in data['userbots'].items() if info['active'])
            inactive_count = len(data['userbots']) - active_count
            
            text = f"""
📊 **Statistik Userbot:**
• Total: `{len(data['userbots'])}`
• Aktif: `{active_count}`
• Nonaktif: `{inactive_count}`

🔄 **Silahkan pilih userbot untuk mengubah status:**
            """
            
            if event.message:
                await event.reply(text, buttons=buttons)
            else:
                await event.edit(text, buttons=buttons)

        @self.bot.on(events.CallbackQuery(pattern=r'^toggle_(\d+)'))
        async def toggle_userbot_callback(event):
            if event.sender_id not in ADMIN_IDS:
                return
                
            user_id = event.data.decode().split('_')[1]
            data = load_data()
            
            if user_id in data['userbots']:
                data['userbots'][user_id]['active'] = not data['userbots'][user_id]['active']
                save_data(data)
                
                page = 0
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
                # For premium users, check their userbot
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
                        Button.inline("✅ Ya, Hapus", data=f"confirm_delete_{bot_id}"),
                        Button.inline("❌ Tidak", data="back_to_start")
                    ]
                ]
                await event.reply(text, buttons=buttons)

        async def show_delete_list(self, event, page=0):
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
                buttons.append([Button.inline(button_text, data=f"delete_{user_id}")])

            nav_buttons = []
            if page > 0:
                nav_buttons.append(Button.inline("⬅️ Kembali", data=f"delete_page_{page-1}"))
            if page < total_pages - 1:
                nav_buttons.append(Button.inline("Lanjut ➡️", data=f"delete_page_{page+1}"))
            if nav_buttons:
                buttons.append(nav_buttons)

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
                        Button.inline("✅ Ya, Hapus", data=f"confirm_delete_{bot_id}"),
                        Button.inline("❌ Tidak", data="back_to_start")
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
                except:
                    pass
                
                # Remove from data
                del data['userbots'][bot_id]
                save_data(data)
                
                text = "✅ **Userbot berhasil dihapus!**"
                buttons = [[Button.inline("◀️ Kembali ke Menu", data="back_to_start")]]
                await event.edit(text, buttons=buttons)
            else:
                await event.edit("❌ **Userbot tidak ditemukan!**")

        return self.bot
