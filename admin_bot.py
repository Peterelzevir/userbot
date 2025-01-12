from telethon import TelegramClient, events, Button, types
from telethon.tl.functions.users import GetFullUserRequest
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, FloodWaitError
from config import API_ID, API_HASH, BOT_TOKEN, ADMIN_IDS, APP_VERSION
import asyncio
from datetime import datetime, timedelta
import os
import time
import math
import json
import logging
import sys
import re
import subprocess
import signal
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

class UserBotManager:
    def __init__(self):
        self.running_bots = {}
        self.bot_status = {}  # Track status setiap bot
        self.last_restart = {}  # Track waktu restart terakhir

    async def start_userbot(self, session_string, api_id, api_hash):
        try:
            # Dapatkan path absolut ke userbot.py
            userbot_path = os.path.abspath("userbot.py")
            
            if not os.path.exists(userbot_path):
                logger.error("userbot.py tidak ditemukan")
                return False, "File userbot.py tidak ditemukan"

            cmd = [
                sys.executable,
                userbot_path,
                session_string,
                str(api_id),
                api_hash
            ]
            
            logger.info(f"Mencoba menjalankan userbot...")
            
            # Jalankan dengan environment yang benar
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ.copy(),
                cwd=os.path.dirname(userbot_path),
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            # Tunggu dan monitor startup
            start_time = time.time()
            while time.time() - start_time < 30:  # Tunggu max 30 detik
                if process.poll() is not None:
                    # Proses mati saat startup
                    _, stderr = process.communicate()
                    logger.error(f"Userbot gagal start: {stderr}")
                    return False, stderr

                # Cek output untuk konfirmasi startup
                output = process.stdout.readline()
                if "Userbot started successfully" in output:
                    logger.info("Userbot berhasil dijalankan")
                    return True, process

                await asyncio.sleep(1)

            # Jika timeout
            process.kill()
            return False, "Timeout menunggu userbot start"

        except Exception as e:
            logger.error(f"Error saat start userbot: {str(e)}")
            return False, str(e)

    async def monitor_userbot(self, user_id, process):
        """Monitor status userbot"""
        retry_count = 0
        max_retries = 3
        
        while True:
            if process.poll() is not None:
                # Proses mati
                _, stderr = process.communicate()
                logger.error(f"Userbot {user_id} mati: {stderr}")
                
                if retry_count < max_retries:
                    # Coba restart
                    logger.info(f"Mencoba restart userbot {user_id}")
                    data = load_data()
                    if user_id in data['userbots']:
                        info = data['userbots'][user_id]
                        success, new_process = await self.start_userbot(
                            info['session'],
                            info['api_id'],
                            info['api_hash']
                        )
                        
                        if success:
                            logger.info(f"Userbot {user_id} berhasil direstart")
                            process = new_process
                            self.running_bots[user_id] = process
                            retry_count += 1
                            continue
                
                # Jika gagal restart atau sudah max retries
                if user_id in self.running_bots:
                    del self.running_bots[user_id]
                    self.bot_status[user_id] = 'dead'
                
                # Update di database
                data = load_data()
                if user_id in data['userbots']:
                    data['userbots'][user_id]['active'] = False
                    save_data(data)
                
                break
            
            await asyncio.sleep(30)  # Cek tiap 30 detik

    def stop_userbot(self, process):
        """Stop userbot dengan cara yang aman"""
        try:
            process.terminate()  # SIGTERM dulu
            try:
                process.wait(timeout=10)  # Tunggu sampai 10 detik
            except subprocess.TimeoutExpired:
                process.kill()  # Force kill kalau tidak mau mati
                process.wait()
        except Exception as e:
            logger.error(f"Error saat stop userbot: {str(e)}")

def load_data():
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
        default_data = {'userbots': {}, 'premium_users': {}, 'users': {}}
        save_data(default_data)
        return default_data
    except json.JSONDecodeError:
        logger.error("Invalid JSON in data.json")
        return {'userbots': {}, 'premium_users': {}, 'users': {}}

def save_data(data):
    try:
        with open('data.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error saving data: {str(e)}")
        return False

def is_premium(user_id):
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
    data = load_data()
    str_id = str(user_id)
    if str_id not in data['users']:
        data['users'][str_id] = {
            'id': user_id,
            'username': username,
            'first_seen': datetime.now().isoformat()
        }
        save_data(data)

async def verify_session(session_str, api_id, api_hash):
    client = None
    try:
        client = TelegramClient(StringSession(session_str), api_id, api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            return False
        me = await client.get_me()
        if not me:
            return False
        return True
    except Exception as e:
        logger.error(f"Session verification error: {str(e)}")
        return False
    finally:
        if client:
            try:
                await client.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting client: {str(e)}")

class AdminBot:
    def __init__(self):
        self.bot = TelegramClient('admin_bot', API_ID, API_HASH)
        self.page_size = 10
        self.userbot_manager = UserBotManager()
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
            # ... help pages lainnya ...
        }

    async def create_new_userbot(self, conv, phone, api_id, api_hash, duration, owner_id):
        client = None
        try:
            try:
                api_id = int(api_id)
            except ValueError:
                await conv.send_message("❌ **Error: API ID harus berupa angka!**")
                return

            data = load_data()
            for bot_info in data['userbots'].values():
                if bot_info['phone'] == phone:
                    await conv.send_message("❌ **Error: Nomor telepon ini sudah memiliki userbot!**")
                    return

            client = TelegramClient(StringSession(), api_id, api_hash, device_model=APP_VERSION)
            await client.connect()
            
            await conv.send_message("⏳ **Memproses permintaan login...**")
            
            try:
                code = await client.send_code_request(phone)
            except FloodWaitError as e:
                wait_time = str(timedelta(seconds=e.seconds))
                await conv.send_message(f"❌ **Terlalu banyak percobaan! Silahkan tunggu {wait_time} sebelum mencoba lagi.**")
                return

            await conv.send_message("""
📲 **Masukkan kode OTP**

Format: 1 2 3 4 5 (pisahkan dengan spasi)
⏳ Waktu: 5 menit
""")

            try:
                otp_msg = await conv.get_response(timeout=300)
                otp = ''.join(otp_msg.text.split())
            except asyncio.TimeoutError:
                await conv.send_message("❌ **Waktu habis! Silahkan coba lagi.**")
                return

            try:
                await client.sign_in(phone=phone, code=otp, phone_code_hash=code.phone_code_hash)
            except PhoneCodeInvalidError:
                await conv.send_message("❌ **Kode OTP tidak valid! Silahkan coba lagi.**")
                return
            except SessionPasswordNeededError:
                await conv.send_message("🔐 **Akun ini menggunakan verifikasi 2 langkah. Silahkan masukkan password:**")
                try:
                    password = await conv.get_response(timeout=300)
                    await client.sign_in(password=password.text)
                except asyncio.TimeoutError:
                    await conv.send_message("❌ **Waktu habis! Silahkan coba lagi.**")
                    return

            me = await client.get_me()
            session_string = client.session.save()

            is_working = await verify_session(session_string, api_id, api_hash)
            if not is_working:
                await conv.send_message("❌ **Error: Gagal memverifikasi sesi userbot. Silahkan coba lagi.**")
                return

            data = load_data()
            expiry_date = (datetime.now() + timedelta(days=duration)).isoformat()
            data['userbots'][str(me.id)] = {
                'first_name': me.first_name,
                'last_name': me.last_name,
                'phone': phone,
                'created_at': datetime.now().isoformat(),
                'expires_at': expiry_date,
                'active': True,
                'session': session_string,
                'owner_id': owner_id,
                'api_id': api_id,
                'api_hash': api_hash
            }

            if save_data(data):
                success, result = await self.userbot_manager.start_userbot(
                    session_string,
                    api_id,
                    api_hash
                )

                if success:
                    self.userbot_manager.running_bots[str(me.id)] = result
                    self.userbot_manager.bot_status[str(me.id)] = 'running'
                    
                    # Mulai monitoring
                    asyncio.create_task(
                        self.userbot_manager.monitor_userbot(str(me.id), result)
                    )

                    success_text = f"""
🤖 **User bot berhasil dibuat dan dijalankan!**

👤 **Detail Userbot:**
• First Name: `{me.first_name}`
• Last Name: `{me.last_name or 'N/A'}`
• User ID: `{me.id}`
• Phone: `{phone}`
• Created: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`
• Expires: `{datetime.fromisoformat(expiry_date).strftime('%Y-%m-%d %H:%M:%S')}`

✅ **Status: Aktif dan Berjalan**

📱 **Perintah Tersedia:**
• .help - Lihat bantuan
• .hiyaok - Mulai forward message
• .listgrup - Lihat daftar grup
• .ban - Ban grup dari forward
• .stop - Stop semua forward

⚠️ **PENTING:**
1. Userbot sudah aktif dan siap digunakan
2. Simpan informasi di bawah dengan aman
3. Gunakan .help untuk melihat semua perintah
4. Jika ada masalah, gunakan /restart

📝 **String Session (RAHASIAKAN!):**
`{session_string}`

⚡️ **API Credentials:**
• API ID: `{api_id}`
• API Hash: `{api_hash}`

🔒 **SIMPAN INFORMASI DI ATAS DENGAN AMAN!**
"""
                    await conv.send_message(success_text)

                else:
                    error_msg = f"""
❌ **Error saat menjalankan userbot:**
`{result}`

**Solusi:**
1. Pastikan userbot.py ada di folder yang benar
2. Cek API ID dan Hash valid
3. Gunakan /restart untuk coba lagi
4. Hubungi admin jika masih error
"""
                    await conv.send_message(error_msg)
                    return

                buttons = []
                if owner_id in ADMIN_IDS:
                    buttons = [
                        [Button.inline("🤖 Buat Userbot", "create_userbot")],
                        [Button.inline("👥 Add Premium", "add_premium")],
                        [Button.inline("📢 Broadcast", "broadcast")],
                        [Button.inline("❓ Bantuan", "help_main")]
                    ]
                else:
                    buttons = [
                        [Button.inline("🤖 Cek Status", "check_status")],
                        [Button.inline("❓ Bantuan", "help_main")]
                    ]

                await conv.send_message("👋 **Kembali ke menu utama.**", buttons=buttons)
            else:
                await conv.send_message("❌ **Error saat menyimpan data userbot!**")
        except Exception as e:
            await conv.send_message(f"❌ **Error tidak terduga:** `{str(e)}`")
        finally:
            if client:
                try:
                    await client.disconnect()
                except Exception as e:
                    logger.error(f"Error disconnecting client: {str(e)}")

    async def restart_userbot(self, user_id):
        """Restart userbot untuk user tertentu"""
        try:
            data = load_data()
            if str(user_id) not in data['userbots']:
                return False, "Userbot tidak ditemukan"

            # Hentikan proses yang sedang berjalan
            if str(user_id) in self.userbot_manager.running_bots:
                old_process = self.userbot_manager.running_bots[str(user_id)]
                self.userbot_manager.stop_userbot(old_process)
                del self.userbot_manager.running_bots[str(user_id)]

            # Ambil info userbot
            info = data['userbots'][str(user_id)]
            
            # Cek waktu restart terakhir
            now = time.time()
            if str(user_id) in self.userbot_manager.last_restart:
                last_restart = self.userbot_manager.last_restart[str(user_id)]
                if now - last_restart < 60:  # Min 1 menit antara restart
                    return False, "Terlalu cepat! Tunggu 1 menit antara restart"
            
            # Update waktu restart terakhir
            self.userbot_manager.last_restart[str(user_id)] = now

            # Start ulang userbot
            success, result = await self.userbot_manager.start_userbot(
                info['session'],
                info['api_id'],
                info['api_hash']
            )

            if success:
                self.userbot_manager.running_bots[str(user_id)] = result
                self.userbot_manager.bot_status[str(user_id)] = 'running'
                
                # Mulai monitoring baru
                asyncio.create_task(
                    self.userbot_manager.monitor_userbot(str(user_id), result)
                )
                
                return True, "Userbot berhasil direstart"
            else:
                return False, f"Gagal restart userbot: {result}"

        except Exception as e:
            logger.error(f"Error restarting userbot: {str(e)}")
            return False, f"Error tidak terduga: {str(e)}"

    async def start(self):
        """Start the bot and register all handlers"""
        
        @self.bot.on(events.NewMessage(pattern=r'(?i)[!/\.]restart$'))
        async def restart_handler(event):
            """Handle restart command"""
            user_id = event.sender_id
            data = load_data()
            
            # Cek apakah user punya userbot
            user_bot = None
            for bot_id, info in data['userbots'].items():
                if str(info.get('owner_id')) == str(user_id):
                    user_bot = (bot_id, info)
                    break
            
            if not user_bot:
                await event.reply("❌ **Anda tidak memiliki userbot untuk direstart!**")
                return
                
            msg = await event.reply("⏳ **Mencoba restart userbot...**")
            success, result = await self.restart_userbot(int(user_bot[0]))
            
            if success:
                await msg.edit("""
✅ **Userbot berhasil direstart!**

Status:
• Proses: Berjalan
• Mode: Normal
• System: Aktif

📱 **Coba perintah berikut:**
• .help - Cek bantuan
                """)
            else:
                await msg.edit(f"""
❌ **Gagal restart userbot!**

Error: `{result}`

Solusi:
1. Tunggu 1 menit, coba lagi
2. Pastikan API ID/Hash valid
3. Hubungi admin jika masih error
                """)

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
            expires = datetime.fromisoformat(info['expires_at'])
            days_left = (expires - datetime.now()).days
            
            is_running = user_id in self.userbot_manager.running_bots
            
            status_text = f"{status} {'⚡️' if is_running else ''}"
            
            button_text = f"{status_text} {info['first_name']} ({days_left} hari)"
            
            buttons.append([Button.inline(button_text, f"toggle_{user_id}")])
        
        # Add pagination buttons if necessary 
        nav_buttons = []
        if page > 0:
            nav_buttons.append(Button.inline("⬅️ Kembali", f"page_{page-1}"))
        if page < total_pages - 1:
            nav_buttons.append(Button.inline("Lanjut ➡️", f"page_{page+1}"))
        if nav_buttons:
            buttons.append(nav_buttons)

        buttons.append([Button.inline("❓ Bantuan", "help_main")])

        active_count = sum(1 for _, info in data['userbots'].items() if info['active'])
        inactive_count = len(data['userbots']) - active_count
        running_count = len(self.userbot_manager.running_bots)
        premium_count = sum(1 for _, info in data['premium_users'].items() if datetime.fromisoformat(info['expires_at']) > datetime.now())
        
        text = f"""
📊 **Statistik Bot:**
• Total Userbot: `{len(data['userbots'])}`
• Userbot Aktif: `{active_count}`
• Userbot Berjalan: `{running_count}`
• Userbot Nonaktif: `{inactive_count}`
• User Premium: `{premium_count}`

🔄 **Daftar Userbot:**
Status: 🟢 Aktif | 🔴 Nonaktif | ⚡️ Berjalan
Klik status untuk mengubah aktif/nonaktif
        """
        
        if event.message:
            await event.reply(text, buttons=buttons)
        else:
            await event.edit(text, buttons=buttons)

    async def show_delete_list(self, event, page=0):
        """Show list of userbots for deletion"""
        data = load_data()
        
        if not data['userbots']:
            await event.reply("❌ **Tidak ada userbot yang ditemukan!**")
            return
            
        text = """
❌ **Hapus Userbot**

Silahkan pilih userbot yang ingin dihapus:
• Klik pada userbot untuk konfirmasi
• Proses tidak dapat dibatalkan
        """
        
        userbots = list(data['userbots'].items())
        total_pages = math.ceil(len(userbots) / self.page_size)
        start_idx = page * self.page_size
        end_idx = start_idx + self.page_size
        current_page_userbots = userbots[start_idx:end_idx]

        buttons = []
        for user_id, info in current_page_userbots:
            status = "🟢" if info['active'] else "🔴"
            expires = datetime.fromisoformat(info['expires_at'])
            days_left = (expires - datetime.now()).days
            is_running = user_id in self.userbot_manager.running_bots
            status_text = f"{status} {'⚡️' if is_running else ''}"
            button_text = f"{status_text} {info['first_name']} ({days_left} hari)"
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
                await event.reply("""
👋 **Selamat datang Admin!**

Silahkan pilih menu yang tersedia:

• Buat Userbot - Membuat userbot baru
• Add Premium - Menambah user premium
• Broadcast - Kirim pesan ke semua user
• Bantuan - Panduan penggunaan bot

⚡️ Status: Sistem berjalan normal
""", buttons=buttons)
                return

            if is_premium(user_id):
                text = """
👋 **Selamat datang User Premium!**

Silahkan pilih menu yang tersedia:
• Buat Userbot - Membuat userbot premium
• Bantuan - Panduan penggunaan bot

✨ Premium benefits:
• Userbot premium 30 hari
• Fitur autoforward
• Support prioritas
• Update otomatis
                """
                buttons = [
                    [Button.inline("🤖 Buat Userbot", "create_userbot")],
                    [Button.inline("❓ Bantuan", "help_main")]
                ]
            else:
                text = """
👋 **Selamat datang!**

🔒 Untuk membuat userbot, Anda memerlukan akses premium.

📦 **Keuntungan Premium:**
• Buat userbot pribadi
• Durasi aktif 30 hari
• Fitur autoforward
• Support prioritas
• Update otomatis
• Garansi puas

💎 **Harga Paket Premium:**
• 1 Bulan: Rp XX.XXX
• 3 Bulan: Rp XX.XXX
• 6 Bulan: Rp XX.XXX
• 1 Tahun: Rp XX.XXX

✨ **Bonus Premium:**
• Setup gratis
• Panduan lengkap
• Konsultasi 24/7
• Backup otomatis

👉 **Cara Berlangganan:**
1. Hubungi admin @admin
2. Pilih paket premium
3. Lakukan pembayaran
4. Dapatkan akses instant!
                """
                buttons = [
                    [Button.url("💬 Chat Admin", "https://t.me/admin")],
                    [Button.inline("❓ Bantuan", "help_main")]
                ]

            await event.reply(text, buttons=buttons)
            
        @self.bot.on(events.CallbackQuery(pattern=r'^help_(\w+)'))
        async def help_callback(event):
            page = event.data.decode().split('_')[1]
            if page == 'close':
                await event.delete()
                return

            help_page = self.help_pages.get(page, self.help_pages['main'])
            await event.edit(help_page['text'], buttons=help_page['buttons'])

        @self.bot.on(events.CallbackQuery(pattern="broadcast"))
        async def broadcast_button_handler(event):
            if event.sender_id not in ADMIN_IDS:
                await event.answer("⚠️ Hanya untuk admin!", alert=True)
                return

            async with self.bot.conversation(event.chat_id) as conv:
                try:
                    await event.delete()
                    await conv.send_message("""
📢 **Menu Broadcast**

Silahkan kirim pesan yang ingin di-broadcast.
Format didukung: Text, Markdown

Note: 
• Pesan akan dikirim ke semua user
• Tunggu hingga proses selesai
• Jangan kirim pesan lain saat proses
                    """)
                    msg = await conv.get_response(timeout=300)
                    
                    data = load_data()
                    success = 0
                    failed = 0
                    
                    progress_msg = await conv.send_message("📤 **Memulai broadcast...**")
                    
                    total_users = len(data['users'])
                    for i, (user_id, _) in enumerate(data['users'].items(), 1):
                        try:
                            await self.bot.send_message(int(user_id), msg.text, parse_mode='md')
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

📊 **Statistik Pengiriman:**
• Berhasil: `{success} user`
• Gagal: `{failed} user`
• Total: `{success + failed} user`
• Success Rate: `{(success/(success+failed))*100:.1f}%`

⚠️ Gagal terkirim biasanya karena:
• User memblokir bot
• User menghapus chat
• Error jaringan
                    """)

                    # Back to admin menu
                    buttons = [
                        [Button.inline("🤖 Buat Userbot", "create_userbot")],
                        [Button.inline("👥 Add Premium", "add_premium")],
                        [Button.inline("📢 Broadcast", "broadcast")],
                        [Button.inline("❓ Bantuan", "help_main")]
                    ]
                    await conv.send_message("👋 **Kembali ke menu admin.**", buttons=buttons)

                except asyncio.TimeoutError:
                    await conv.send_message("""
❌ **Waktu habis!**

Silahkan klik tombol broadcast untuk mencoba lagi.
                    """)

        @self.bot.on(events.CallbackQuery(pattern="check_status"))
        async def check_status_callback(event):
            """Handle check status button for premium users"""
            user_id = event.sender_id
            
            if not is_premium(user_id):
                return await not_premium_handler(event)
                
            data = load_data()
            user_bot = None
            for bot_id, info in data['userbots'].items():
                if str(info.get('owner_id')) == str(user_id):
                    user_bot = (bot_id, info)
                    break
                    
            if user_bot:
                bot_id, info = user_bot
                expires = datetime.fromisoformat(info['expires_at'])
                days_left = (expires - datetime.now()).days
                is_running = bot_id in self.userbot_manager.running_bots
                
                text = f"""
🤖 **Status Userbot Anda**

👤 **Detail Userbot:**
• Nama: `{info['first_name']}`
• Status: {"🟢 Aktif" if info['active'] else "🔴 Nonaktif"} {"⚡️ (Berjalan)" if is_running else ""}
• Nomor: `{info['phone']}`
• Dibuat: `{datetime.fromisoformat(info['created_at']).strftime('%Y-%m-%d %H:%M:%S')}`
• Kadaluarsa: `{datetime.fromisoformat(info['expires_at']).strftime('%Y-%m-%d %H:%M:%S')}`
• Sisa Durasi: {days_left} hari

📱 **Perintah Tersedia:**
• .help - Lihat panduan
• .hiyaok - Forward pesan
• .listgrup - Lihat grup
• .stop - Stop forward

💡 **Tips:**
• Gunakan /restart jika ada masalah
• Hubungi admin untuk perpanjang durasi
• Backup string session dengan aman
                """
                buttons = [[Button.inline("◀️ Kembali", "back_to_start")]]
                await event.edit(text, buttons=buttons)
            else:
                await event.answer("❌ Anda belum memiliki userbot!", alert=True)
                await not_premium_handler(event)

        @self.bot.on(events.CallbackQuery(pattern="add_premium"))
        async def premium_button_handler(event):
            if event.sender_id not in ADMIN_IDS:
                await event.answer("⚠️ Hanya untuk admin!", alert=True)
                return

            async with self.bot.conversation(event.chat_id) as conv:
                try:
                    await event.delete()
                    await conv.send_message("""
👥 **Menu Add Premium User**

Silahkan ikuti langkah berikut:
1. Masukkan ID user yang akan ditambahkan
2. Masukkan durasi premium dalam hari

Note:
• ID user bisa didapat dari @userinfobot
• Durasi minimal 1 hari
• User akan mendapat notifikasi otomatis
                    """)
                    
                    await conv.send_message("📝 **Masukkan ID user yang akan ditambahkan sebagai premium:**")
                    user_id_msg = await conv.get_response(timeout=300)
                    user_id = user_id_msg.text.strip()
                    
                    try:
                        user_id = int(user_id)
                    except ValueError:
                        await conv.send_message("❌ **Error: User ID harus berupa angka!**")
                        return
                    
                    # Check if already premium
                    if is_premium(user_id):
                        await conv.send_message("⚠️ **User  sudah memiliki akses premium!**")
                        return
                    
                    await conv.send_message("""
⏳ **Masukkan durasi premium dalam hari**

Contoh durasi:
• 30 = 1 bulan
• 90 = 3 bulan
• 180 = 6 bulan
• 365 = 1 tahun
                    """)
                    duration_msg = await conv.get_response(timeout=300)
                    try:
                        duration = int(duration_msg.text.strip())
                        if duration < 1:
                            raise ValueError("Durasi minimal 1 hari")
                    except ValueError:
                        await conv.send_message("❌ **Error: Durasi harus berupa angka positif!**")
                        return
                    
                    data = load_data()
                    expiry_date = (datetime.now() + timedelta(days=duration)).isoformat()
                    
                    # Check if user exists
                    try:
                        user = await self.bot.get_entity(user_id)
                        if not user:
                            raise ValueError("User  tidak ditemukan")
                    except Exception as e:
                        await conv.send_message("❌ **Error: User tidak ditemukan di Telegram!**")
                        return
                    
                    data['premium_users'][str(user_id)] = {
                        'added_at': datetime.now().isoformat(),
                        'expires_at': expiry_date,
                        'added_by': event.sender_id,
                        'username': user.username,
                        'first_name': user.first_name
                    }
                    
                    if save_data(data):
                        # Notify user
                        try:
                            text = f"""
🎉 **Selamat! Anda telah mendapatkan akses premium!**

📅 **Detail Premium:**
• Tanggal Mulai: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`
• Kadaluarsa: `{datetime.fromisoformat(expiry_date).strftime('%Y-%m-%d %H:%M:%S')}`
• Durasi: `{duration} hari`

✨ **Fitur Premium:**
• Buat userbot pribadi
• Fitur autoforward 
• Support prioritas
• Update otomatis
• Dan lainnya...

📱 **Cara Mulai:**
1. Kirim /start ke bot
2. Klik tombol "Buat Userbot"
3. Ikuti instruksi selanjutnya

💡 **Tips:**
• Simpan pesan ini untuk referensi
• Hubungi admin jika butuh bantuan
• Backup semua data penting

Selamat menggunakan fitur premium! 
                            """
                            await self.bot.send_message(user_id, text)
                            await conv.send_message(f"""
✅ **Berhasil menambahkan user premium!**

👤 **Detail User:**
• ID: `{user_id}`
• Username: @{user.username or "None"}
• Nama: {user.first_name}
• Durasi: {duration} hari
• Expires: {datetime.fromisoformat(expiry_date).strftime('%Y-%m-%d %H:%M:%S')}

✨ User telah dinotifikasi via bot
                            """)
                            
                            # Send back to admin menu
                            buttons = [
                                [Button.inline("🤖 Buat Userbot", "create_userbot")],
                                [Button.inline("👥 Add Premium", "add_premium")],
                                [Button.inline("📢 Broadcast", "broadcast")],
                                [Button.inline("❓ Bantuan", "help_main")]
                            ]
                            await conv.send_message("👋 **Kembali ke menu admin.**", buttons=buttons)
                            
                        except Exception as e:
                            logger.error(f"Error notifying premium user: {str(e)}")
                            await conv.send_message(f"""
⚠️ **Berhasil menambahkan premium, tapi gagal mengirim notifikasi ke user**

Error: `{str(e)}`
Mohon informasikan manual ke user.
                            """)
                    else:
                        await conv.send_message("❌ **Gagal menyimpan data premium user!**")
                    
                except asyncio.TimeoutError:
                    await conv.send_message("❌ **Waktu habis! Silahkan klik tombol Add Premium untuk mencoba lagi.**")
                except Exception as e:
                    logger.error(f"Error adding premium user: {str(e)}")
                    await conv.send_message(f"❌ **Error tidak terduga:** `{str(e)}`")
                    
        @self.bot.on(events.CallbackQuery(pattern="not_premium"))
        async def not_premium_handler(event):
            text = """
⚠️ **Akses Premium Diperlukan!**

Untuk membuat userbot, Anda memerlukan akses premium.

📦 **Keuntungan Premium:**
• Buat userbot pribadi
• Durasi aktif sesuai paket
• Fitur autoforward
• Support prioritas
• Update otomatis
• Garansi kepuasan

💎 **Harga Paket Premium:**
• 1 Bulan: Rp 10.000
• 3 Bulan: Rp 30.000
• 6 Bulan: Rp 60.000
• 1 Tahun: Rp XX.XXX

🎁 **Bonus Premium:**
• Setup gratis
• Panduan lengkap 
• Konsultasi 24/7
• Backup otomatis

👉 **Cara Berlangganan:**
1. Hubungi admin @admin
2. Pilih paket premium
3. Lakukan pembayaran 
4. Dapatkan akses instant!

✨ Upgrade sekarang dan nikmati semua fitur premium!
            """
            buttons = [
                [Button.url("💬 Chat Admin", "https://t.me/admin")],
                [Button.inline("◀️ Kembali ke Menu", "back_to_start")]
            ]
            await event.edit(text, buttons=buttons)

        @self.bot.on(events.CallbackQuery(pattern=r'^create_userbot$'))
        async def create_userbot_handler(event):
            user_id = event.sender_id
            
            if user_id not in ADMIN_IDS:
                if not is_premium(user_id):
                    await event.answer("⚠️ Anda harus premium untuk membuat userbot!", alert=True)
                    return await not_premium_handler(event)
                
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
• Running: {"⚡️ Ya" if str(user_id) in self.userbot_manager.running_bots else "❌ Tidak"}

📱 **Perintah Tersedia:**
• /restart - Restart userbot
• .help - Lihat panduan lengkap
• .stop - Stop semua tugas

💡 **Tips:**
• Gunakan /restart jika userbot error
• Hubungi admin jika butuh bantuan
                        """
                        buttons = [[Button.inline("◀️ Kembali", "back_to_start")]]
                        await event.edit(text, buttons=buttons)
                        return

            async with self.bot.conversation(event.chat_id) as conv:
                try:
                    await event.delete()
                    await conv.send_message("""
📱 **Form Pembuatan Userbot**

Silahkan ikuti langkah-langkah berikut:

1️⃣ Kunjungi my.telegram.org
2️⃣ Login dengan nomor telepon
3️⃣ Klik API Development Tools
4️⃣ Buat aplikasi baru untuk mendapat API ID & Hash

⚠️ **PENTING:**
• API ID berupa angka (contoh: 1234567)
• API Hash berupa huruf & angka
• Nomor telepon format: +628xxx
• Jangan bagikan API ID & Hash
• Simpan informasi dengan aman

Kirim /cancel untuk membatalkan
                    """)
                    
                    await conv.send_message("📝 **Masukkan API ID:**")
                    api_id_msg = await conv.get_response(timeout=300)
                    
                    # Check for cancel
                    if api_id_msg.text.lower() == "/cancel":
                        await conv.send_message("❌ Pembuatan userbot dibatalkan.")
                        return
                        
                    api_id = api_id_msg.text.strip()

                    await conv.send_message("📝 **Masukkan API Hash:**")
                    api_hash_msg = await conv.get_response(timeout=300)
                    
                    if api_hash_msg.text.lower() == "/cancel":
                        await conv.send_message("❌ Pembuatan userbot dibatalkan.")
                        return
                        
                    api_hash = api_hash_msg.text.strip()

                    await conv.send_message("📱 **Masukkan nomor telepon (format: +628xxx):**")
                    phone_msg = await conv.get_response(timeout=300)
                    
                    if phone_msg.text.lower() == "/cancel":
                        await conv.send_message("❌ Pembuatan userbot dibatalkan.") 
                        return
                        
                    phone = phone_msg.text.strip()
                    
                    # Validate phone number format
                    if not re.match(r'^\+\d{10,15}$', phone):
                        await conv.send_message("""
❌ **Format nomor telepon tidak valid!**

✅ Format yang benar: +628xxx
❌ Format yang salah: 
• 08xxx (tanpa +)
• 628xxx (tanpa +)
• +62-8xxx (ada tanda -)
                        """)
                        return

                    # Set duration based on user type
                    duration = 30 if user_id not in ADMIN_IDS else None
                    if duration is None:
                        await conv.send_message("""
⏳ **Masukkan durasi aktif userbot (dalam hari)**

Contoh durasi:
• 30 = 1 bulan
• 90 = 3 bulan
• 180 = 6 bulan
• 365 = 1 tahun
                        """)
                        duration_msg = await conv.get_response(timeout=300)
                        
                        if duration_msg.text.lower() == "/cancel":
                            await conv.send_message("❌ Pembuatan userbot dibatalkan.")
                            return
                            
                        try:
                            duration = int(duration_msg.text.strip())
                            if duration < 1:
                                raise ValueError("Durasi minimal 1 hari")
                        except ValueError:
                            await conv.send_message("❌ **Error: Durasi harus berupa angka positif!**")
                            return

                    # Create userbot
                    await self.create_new_userbot(conv, phone, api_id, api_hash, duration, user_id)
                    
                except asyncio.TimeoutError:
                    await conv.send_message("""
❌ **Waktu habis!**

Silahkan kirim `/start` untuk memulai ulang proses pembuatan userbot.
                    """)
                except Exception as e:
                    logger.error(f"Error in create_userbot_handler: {str(e)}")
                    await conv.send_message(f"""
❌ **Error tidak terduga!**

Detail error: `{str(e)}`
Silahkan hubungi admin untuk bantuan.
                    """)

        @self.bot.on(events.NewMessage(pattern=r'(?i)[!/\.]cek$'))
        async def check_userbot_handler(event):
            user_id = event.sender_id
            
            if user_id not in ADMIN_IDS:
                # For premium users, only show their userbot
                if is_premium(user_id):
                    data = load_data()
                    user_bot = None
                    for bot_id, info in data['userbots'].items():
                        if str(info.get('owner_id')) == str(user_id):
                            user_bot = (bot_id, info)
                            break
                            
                    if user_bot:
                        bot_id, info = user_bot
                        expires = datetime.fromisoformat(info['expires_at'])
                        days_left = (expires - datetime.now()).days
                        is_running = bot_id in self.userbot_manager.running_bots
                        
                        text = f"""
🤖 **Status Userbot Anda**

👤 **Detail:**
• Nama: `{info['first_name']}`
• Status: {"🟢 Aktif" if info['active'] else "🔴 Nonaktif"} {"⚡️ (Berjalan)" if is_running else ""}
• Nomor: `{info['phone']}`
• Dibuat: `{datetime.fromisoformat(info['created_at']).strftime('%Y-%m-%d %H:%M:%S')}`
• Kadaluarsa: `{datetime.fromisoformat(info['expires_at']).strftime('%Y-%m-%d %H:%M:%S')}`
• Sisa Durasi: {days_left} hari

💡 **Tips:**
• Gunakan /restart jika ada masalah
• Hubungi admin untuk perpanjang durasi
• Backup string session dengan aman
                        """
                        buttons = [[Button.inline("◀️ Kembali", "back_to_start")]]
                        await event.reply(text, buttons=buttons)
                    else:
                        await event.reply("❌ **Anda belum memiliki userbot!**")
                else:
                    return await not_premium_handler(event)
                return
                
            # For admin, show all userbots
            await self.show_userbot_list(event, page=0)

        @self.bot.on(events.CallbackQuery(pattern=r'^page_(\d+)'))
        async def page_callback(event):
            if event.sender_id not in ADMIN_IDS:
                await event.answer("⚠️ Hanya untuk admin!", alert=True)
                return
                
            page = int(event.data.decode().split('_')[1])
            await self.show_userbot_list(event, page)

        @self.bot.on(events.CallbackQuery(pattern="back_to_start"))
        async def back_to_start_handler(event):
            """Handle back to start button"""
            await event.delete()
            # Simulate /start command
            message = event.original_update.msg_id
            await start_handler(await event.get_message())

        # Cleanup expired userbots periodically
        async def cleanup_expired():
            while True:
                try:
                    data = load_data()
                    now = datetime.now()
                    expired = []
                    
                    # Check expired userbots
                    for user_id, info in data['userbots'].items():
                        try:
                            expiry = datetime.fromisoformat(info['expires_at'])
                            if expiry < now:
                                expired.append(user_id)
                                
                                # Stop process if running
                                if user_id in self.userbot_manager.running_bots:
                                    process = self.userbot_manager.running_bots[user_id]
                                    self.userbot_manager.stop_userbot(process)
                                    del self.userbot_manager.running_bots[user_id]
                                
                                # Notify owner
                                try:
                                    owner_id = int(info['owner_id'])
                                    text = f"""
⚠️ **Pemberitahuan Userbot**

🤖 **User  bot Anda telah kadaluarsa!**

Detail Userbot:
• Nama: `{info['first_name']}`
• Phone: `{info['phone']}`
• Status: Nonaktif (Expired)

Silahkan hubungi admin untuk perpanjang durasi.
                                    """
                                    await self.bot.send_message(owner_id, text)
                                except:
                                    pass
                        except (ValueError, KeyError):
                            continue
                    
                    if expired:
                        # Remove expired userbots
                        for user_id in expired:
                            del data['userbots'][user_id]
                        save_data(data)
                        logger.info(f"Cleaned up {len(expired)} expired userbots")
                        
                except Exception as e:
                    logger.error(f"Error in cleanup: {str(e)}")
                    
                await asyncio.sleep(3600)  # Check every hour

        # Start the cleanup task
        asyncio.create_task(cleanup_expired())

        # Start the bot
        await self.bot.start(bot_token=BOT_TOKEN)
        logger.info("Admin bot started.")
        await self.bot.run_until_disconnected()

# Run the bot
if __name__ == "__main__":
    bot = AdminBot()
    asyncio.run(bot.start())
