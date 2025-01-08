from telethon import TelegramClient, events,utils
from telethon.tl.types import InputPeerChannel
from telethon.errors import RPCError, FloodWaitError, ChatWriteForbiddenError
from telethon.sessions import StringSession
import asyncio
import os
import sys
import time
from typing import Dict
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('userbot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class ForwardTask:
    def __init__(self, message_id: int, chat_id: int, delay: int):
        self.message_id = message_id
        self.chat_id = chat_id
        self.delay = delay
        self.running = True
        self.success_count = 0
        self.failed_count = 0
        self.failed_groups = []
        self.last_preview = None
        self.start_time = datetime.now()

class Userbot:
    def __init__(self, session_string, api_id, api_hash):
        self.client = TelegramClient(StringSession(session_string), api_id, api_hash, 
                                   device_model="Userbot v1.0")
        self.banned_groups = set()
        self.forward_tasks: Dict[str, ForwardTask] = {}  # key: task_id (chat_id_msg_id)

    async def start(self):
        """Start userbot and register handlers"""
        await self.client.start()
        print("Userbot started successfully!")

        @self.client.on(events.NewMessage(pattern=r'(?i)[!/\.]help$'))
        async def help_handler(event):
            if event.sender_id != event.client.uid:
                return

            help_text = """
📱 **USERBOT COMMANDS**

📤 **Forward Commands:**
• `.hiyaok <delay>` - Start forwarding message (reply ke pesan)
  Example: `.hiyaok 5` (delay 5 menit)
  
• `.detail` - Tampilkan detail forward yang aktif
• `.stop` - Stop semua forward task
• `.delforward <task_id>` - Hapus forward task tertentu
• `.setdelay <task_id> <menit>` - Set delay untuk task

👥 **Group Commands:**
• `.listgrup` - List semua grup
• `.ban` - Ban grup dari forward
• `.listban` - List grup yang dibanned
• `.deleteban` - Hapus grup dari ban list

⚙️ **Catatan:**
• Maksimal 10 forward task bersamaan
• Forward akan ke semua grup kecuali yang dibanned
• Proses: Kirim ke semua grup → Tunggu delay → Ulangi
• Task berhenti jika pesan sumber dihapus

❗️ Jika ada masalah, gunakan .stop untuk hentikan semua task
"""
            await event.reply(help_text, parse_mode='md')

        @self.client.on(events.NewMessage(pattern=r'[!/\.]hiyaok'))
        async def hiyaok_handler(event):
            if event.sender_id != event.client.uid:
                return

            if not event.is_reply:
                await event.reply("""
❌ **Error:** Harap reply ke pesan yang ingin diforward

Contoh penggunaan:
1. Reply ke pesan yang mau diforward
2. Ketik: `.hiyaok 5` (delay 5 menit)
                """, parse_mode='md')
                return

            # Check if maximum tasks reached
            if len(self.forward_tasks) >= 10:
                await event.reply("""
⚠️ **Error:** Maksimal forward task (10) tercapai!

Gunakan:
• `.stop` untuk stop semua task
• `.delforward` untuk hapus task tertentu
• `.detail` untuk lihat task yang aktif
                """, parse_mode='md')
                return

            try:
                args = event.text.split()
                if len(args) != 2:
                    raise ValueError
                delay = int(args[1])
                if delay < 1:
                    await event.reply("""
⚠️ **Error:** Delay minimal 1 menit

Format command:
`.hiyaok <delay_in_minutes>`
Example: `.hiyaok 5`
                    """, parse_mode='md')
                    return
            except ValueError:
                await event.reply("""
❌ **Error:** Format command tidak valid

Penggunaan yang benar:
• `.hiyaok <delay>`
• Example: `.hiyaok 5` (delay 5 menit)
                """, parse_mode='md')
                return

            replied_msg = await event.get_reply_message()
            task_id = f"{replied_msg.chat_id}_{replied_msg.id}"

            if task_id in self.forward_tasks:
                await event.reply(f"""
⚠️ **Error:** Pesan ini sudah dalam proses forward!

Task ID: `{task_id}`
Gunakan `.detail` untuk cek status
                """, parse_mode='md')
                return

            self.forward_tasks[task_id] = ForwardTask(
                message_id=replied_msg.id,
                chat_id=replied_msg.chat_id,
                delay=delay
            )

            # Start forward task
            asyncio.create_task(self._forward_message(task_id, event))

        async def _forward_message(self, task_id: str, event):
            task = self.forward_tasks[task_id]
            initial_msg = await event.reply("🔄 **Memulai proses forward...**", parse_mode='md')

            while task.running:
                try:
                    # Check if source message still exists
                    message = await self.client.get_messages(task.chat_id, ids=task.message_id)
                    if not message:
                        raise RPCError("Message was deleted")

                    task.last_preview = message.text[:200] if message.text else "[Media Message]"
                    success = 0
                    failed = 0
                    failed_groups = []

                    async for dialog in self.client.iter_dialogs():
                        if not task.running:
                            break

                        if dialog.is_group and dialog.id not in self.banned_groups:
                            try:
                                await self.client.forward_messages(dialog.id, message)
                                success += 1
                                await asyncio.sleep(2)  # Small delay between forwards
                            except FloodWaitError as e:
                                await asyncio.sleep(e.seconds)
                                # Retry once after flood wait
                                try:
                                    await self.client.forward_messages(dialog.id, message)
                                    success += 1
                                except:
                                    failed += 1
                                    failed_groups.append(f"{dialog.title}: Flood limit")
                            except ChatWriteForbiddenError:
                                failed += 1
                                failed_groups.append(f"{dialog.title}: Bot dibanned/dibatasi")
                            except Exception as e:
                                failed += 1
                                failed_groups.append(f"{dialog.title}: {str(e)}")

                    task.success_count += success
                    task.failed_count += failed
                    task.failed_groups = failed_groups

                    runtime = datetime.now() - task.start_time
                    hours, remainder = divmod(runtime.seconds, 3600)
                    minutes, seconds = divmod(remainder, 60)

                    status = f"""
📊 **Forward Status:**
🆔 Task ID: `{task_id}`
⏱ Runtime: `{hours}h {minutes}m {seconds}s`

📝 **Pesan Preview:**
`{task.last_preview[:100]}...`

📈 **Cycle Ini:**
✅ Sukses: `{success}`
❌ Gagal: `{failed}`

📊 **Total Statistik:**
✅ Total Sukses: `{task.success_count}`
❌ Total Gagal: `{task.failed_count}`

⚠️ **Grup yang Gagal (Cycle Ini):**
```
{chr(10).join(failed_groups[:5]) if failed_groups else 'Tidak ada'}
{'...' if len(failed_groups) > 5 else ''}
```

⏳ Menunggu {task.delay} menit untuk cycle berikutnya...
                    """
                    await initial_msg.edit(status, parse_mode='md')

                    if task.running:
                        await asyncio.sleep(task.delay * 60)

                except RPCError as e:
                    if "MESSAGE_ID_INVALID" in str(e) or not message:
                        runtime = datetime.now() - task.start_time
                        error_msg = f"""
⚠️ **Forward Task Berhenti!**

❌ **Alasan:** Pesan sumber dihapus/tidak ditemukan
🆔 **Task ID:** `{task_id}`

📊 **Statistik Akhir:**
✅ Total Sukses: `{task.success_count}`
❌ Total Gagal: `{task.failed_count}`
⏱ Runtime: `{hours}h {minutes}m {seconds}s`
                        """
                        await initial_msg.edit(error_msg, parse_mode='md')
                        if task_id in self.forward_tasks:
                            del self.forward_tasks[task_id]
                        break
                    else:
                        error_msg = f"""
⚠️ **Forward Error:**
Task ID: `{task_id}`
Error: `{str(e)}`

Task akan dilanjutkan dalam {task.delay} menit...
                        """
                        await initial_msg.edit(error_msg, parse_mode='md')
                        if task.running:
                            await asyncio.sleep(task.delay * 60)

                except Exception as e:
                    error_msg = f"""
⚠️ **Forward Error:**
Task ID: `{task_id}`
Error: `{str(e)}`

Task akan dilanjutkan dalam {task.delay} menit...
                    """
                    await initial_msg.edit(error_msg, parse_mode='md')
                    if task.running:
                        await asyncio.sleep(task.delay * 60)

        @self.client.on(events.NewMessage(pattern=r'[!/\.]detail'))
        async def detail_handler(event):
            if event.sender_id != event.client.uid:
                return

            if not self.forward_tasks:
                await event.reply("📝 Tidak ada forward task yang aktif.", parse_mode='md')
                return

            details = []
            for task_id, task in self.forward_tasks.items():
                runtime = datetime.now() - task.start_time
                hours, remainder = divmod(runtime.seconds, 3600)
                minutes, seconds = divmod(remainder, 60)

                details.append(f"""
🔄 **Task ID:** `{task_id}`
📝 **Preview:** `{task.last_preview[:100]}...`
⏱ **Delay:** `{task.delay} menit`
⏳ **Runtime:** `{hours}h {minutes}m {seconds}s`
📊 **Statistik:**
• Total Sukses: `{task.success_count}`
• Total Gagal: `{task.failed_count}`
""")

            await event.reply(
                "📋 **Active Forward Tasks:**\n" + "\n".join(details),
                parse_mode='md'
            )

        @self.client.on(events.NewMessage(pattern=r'[!/\.]setdelay'))
        async def setdelay_handler(event):
            if event.sender_id != event.client.uid:
                return

            try:
                args = event.text.split()
                if len(args) != 3:
                    raise ValueError

                task_id = args[1]
                delay = int(args[2])

                if delay < 1:
                    await event.reply("""
⚠️ **Error:** Delay minimal 1 menit

Format: `.setdelay <task_id> <minutes>`
                    """, parse_mode='md')
                    return

                if task_id in self.forward_tasks:
                    self.forward_tasks[task_id].delay = delay
                    await event.reply(f"""
⏱️ **Berhasil!**
Delay untuk task `{task_id}` diset ke `{delay}` menit
                    """, parse_mode='md')
                else:
                    await event.reply("""
❌ **Error:** Task tidak ditemukan!
Gunakan `.detail` untuk cek task yang aktif
                    """, parse_mode='md')
            except ValueError:
                await event.reply("""
❌ **Error:** Format command tidak valid

Penggunaan:
• `.setdelay <task_id> <minutes>`
• Example: `.setdelay 123_456 5`
                """, parse_mode='md')

        @self.client.on(events.NewMessage(pattern=r'[!/\.]stop'))
        async def stop_handler(event):
            if event.sender_id != event.client.uid:
                return

            stopped_count = len(self.forward_tasks)
            if stopped_count == 0:
                await event.reply("ℹ️ Tidak ada task yang aktif.", parse_mode='md')
                return

            task_details = []
            for task_id, task in self.forward_tasks.items():
                runtime = datetime.now() - task.start_time
                hours, remainder = divmod(runtime.seconds, 3600)
                minutes, seconds = divmod(remainder, 60)

                task_details.append(f"""
🆔 Task ID: `{task_id}`
📊 Stats:
• Success: `{task.success_count}`
• Failed: `{task.failed_count}`
⏱ Runtime: `{hours}h {minutes}m {seconds}s`""")
                task.running = False

            self.forward_tasks.clear()

            await event.reply(f"""
🛑 **Menghentikan {stopped_count} forward task**

**Detail Task yang Dihentikan:**{chr(10).join(task_details)}
                """, parse_mode='md')

        @self.client.on(events.NewMessage(pattern=r'[!/\.]delforward'))
        async def delforward_handler(event):
            if event.sender_id != event.client.uid:
                return

            try:
                task_id = event.text.split()[1]
                if task_id in self.forward_tasks:
                    task = self.forward_tasks[task_id]
                    runtime = datetime.now() - task.start_time
                    hours, remainder = divmod(runtime.seconds, 3600)
                    minutes, seconds = divmod(remainder, 60)

                    task.running = False
                    del self.forward_tasks[task_id]

                    await event.reply(f"""
✅ **Forward task dihapus!**

🆔 **Detail Task:**
• Task ID: `{task_id}`
• Success: `{task.success_count}`
• Failed: `{task.failed_count}`
• Runtime: `{hours}h {minutes}m {seconds}s`
                    """, parse_mode='md')
                else:
                    await event.reply("""
❌ **Error:** Task tidak ditemukan!

Gunakan `.detail` untuk lihat task yang aktif.
                    """, parse_mode='md')
            except IndexError:
                await event.reply("""
❌ **Error:** Harap sertakan Task ID

Penggunaan:
• `.delforward <task_id>`
• Gunakan `.detail` untuk lihat Task ID
                """, parse_mode='md')

        @self.client.on(events.NewMessage(pattern=r'[!/\.]listgrup'))
        async def listgrup_handler(event):
            if event.sender_id != event.client.uid:
                return

            groups = []
            async for dialog in self.client.iter_dialogs():
                if dialog.is_group:
                    try:
                        member_count = await self.client.get_participants(dialog, limit=0)
                        groups.append(f"""
📢 Grup: {dialog.title}
🆔 ID: `{dialog.id}`
👥 Members: {len(member_count)}
{('🚫 Di-ban' if dialog.id in self.banned_groups else '✅ Aktif')}
                        """)
                    except Exception as e:
                        groups.append(f"""
📢 Grup: {dialog.title}
🆔 ID: `{dialog.id}`
👥 Members: Error counting
⚠️ Error: {str(e)}
                        """)

            groups_text = "\n".join(groups)

            if len(groups_text) > 4000:
                # Split into multiple messages if too long
                message_parts = []
                current_part = "📋 **Daftar Grup:**\n"

                for group in groups:
                    if len(current_part) + len(group) > 4000:
                        message_parts.append(current_part)
                        current_part = "📋 **Daftar Grup (Lanjutan):**\n" + group
                    else:
                        current_part += group

                if current_part:
                    message_parts.append(current_part)

                for part in message_parts:
                    await event.reply(part, parse_mode='md')
            else:
                await event.reply(
                    f"📋 **Daftar Grup:**\n{groups_text}",
                    parse_mode='md'
                )

        @self.client.on(events.NewMessage(pattern=r'[!/\.]ban'))
        async def ban_handler(event):
            if event.sender_id != event.client.uid:
                return

            if event.is_group:
                if event.chat_id not in self.banned_groups:
                    self.banned_groups.add(event.chat_id)
                    group = await event.get_chat()
                    await event.reply(f"""
🚫 **Grup Di-ban dari Forward**

👥 **Detail Grup:**
• Nama: `{group.title}`
• ID: `{event.chat_id}`

Gunakan `.deleteban` di grup ini untuk unban.
                    """, parse_mode='md')
                else:
                    await event.reply("ℹ️ Grup ini sudah di-ban dari forward.", parse_mode='md')
            else:
                await event.reply("❌ Command ini hanya berfungsi di grup!", parse_mode='md')

        @self.client.on(events.NewMessage(pattern=r'[!/\.]listban'))
        async def listban_handler(event):
            if event.sender_id != event.client.uid:
                return

            if not self.banned_groups:
                await event.reply("📋 **Tidak ada grup yang di-ban**", parse_mode='md')
                return

            banned = []
            for group_id in self.banned_groups:
                try:
                    group = await self.client.get_entity(group_id)
                    banned.append(f"• {group.title} (`{group_id}`)")
                except:
                    banned.append(f"• Unknown Group (`{group_id}`)")

            await event.reply(f"""
📋 **Daftar Grup yang Di-ban:**
{chr(10).join(banned)}

Total: `{len(self.banned_groups)}` grup
            """, parse_mode='md')

        @self.client.on(events.NewMessage(pattern=r'[!/\.]deleteban'))
        async def deleteban_handler(event):
            if event.sender_id != event.client.uid:
                return

            if event.is_group:
                if event.chat_id in self.banned_groups:
                    self.banned_groups.remove(event.chat_id)
                    group = await event.get_chat()
                    await event.reply(f"""
✅ **Grup Berhasil Di-unban**

👥 **Detail Grup:**
• Nama: `{group.title}`
• ID: `{event.chat_id}`

Grup ini akan menerima forward lagi.
                    """, parse_mode='md')
                else:
                    await event.reply("ℹ️ Grup ini tidak sedang di-ban.", parse_mode='md')
            else:
                await event.reply("❌ Command ini hanya berfungsi di grup!", parse_mode='md')

        # Add status command
        @self.client.on(events.NewMessage(pattern=r'[!/\.]status'))
        async def status_handler(event):
            if event.sender_id != event.client.uid:
                return
            
            me = await self.client.get_me()
            active_tasks = len(self.forward_tasks)
            banned_count = len(self.banned_groups)
            
            total_forwards = sum(task.success_count for task in self.forward_tasks.values())
            total_fails = sum(task.failed_count for task in self.forward_tasks.values())
            
            await event.reply(f"""
🤖 **Userbot Status**

👤 **Account Info:**
• Name: `{me.first_name}`
• ID: `{me.id}`
• Phone: `{me.phone}`

📊 **Statistics:**
• Active Tasks: `{active_tasks}/10`
• Banned Groups: `{banned_count}`
• Total Forwards: `{total_forwards}`
• Total Fails: `{total_fails}`

💡 Use `.help` for commands list
            """, parse_mode='md')

if __name__ == "__main__":
    # Check arguments
    if len(sys.argv) != 4:
        print("Usage: python userbot.py <session_string> <api_id> <api_hash>")
        sys.exit(1)

    session_string = sys.argv[1]
    api_id = int(sys.argv[2])
    api_hash = sys.argv[3]

    # Create and start userbot
    print("Starting userbot...")
    userbot = Userbot(session_string, api_id, api_hash)

    loop = asyncio.get_event_loop()
    
    try:
        print("Connecting to Telegram...")
        loop.run_until_complete(userbot.start())
        print("Userbot is running!")
        loop.run_forever()
    except KeyboardInterrupt:
        print("Stopping userbot...")
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        loop.close()
