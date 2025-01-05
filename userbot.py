from telethon import TelegramClient, events, utils
from telethon.tl.types import InputPeerChannel
from telethon.errors import RPCError, FloodWaitError, ChatWriteForbiddenError
from telethon.sessions import StringSession
from config import *
import asyncio
import os
from typing import Dict, List
from datetime import datetime

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
                                   device_model=APP_VERSION)
        self.banned_groups = set()
        self.forward_tasks: Dict[str, ForwardTask] = {}  # key: task_id (chat_id_msg_id)
        
    async def start(self):
        await self.client.start()
        
        # Check expiry every hour
        asyncio.create_task(self._check_expiry())

        @self.client.on(events.NewMessage(pattern=r'(?i)[!/\.]help$'))
        async def help_handler(event):
            if event.sender_id != event.client.uid:
                return

            help_text = """
📱 **USERBOT COMMANDS**

📤 **Forward Commands:**
• `.hiyaok <delay>` - Start forwarding message (reply to message)
  Example: `.hiyaok 5` (5 minutes delay)
  
• `.detail` - Show active forward tasks details
• `.stop` - Stop all forward tasks
• `.delforward <task_id>` - Delete specific forward task
• `.setdelay <task_id> <minutes>` - Set delay for specific task

👥 **Group Management:**
• `.listgrup` - List all groups
• `.ban` - Ban current group from forwards
• `.listban` - List banned groups
• `.deleteban` - Remove current group from ban list

⚙️ **Notes:**
• Maximum 10 simultaneous forward tasks
• Each task will forward to all groups except banned ones
• Forward process: Send to all groups → Wait delay → Repeat
• Tasks auto-stop if original message is deleted

❗️ If you encounter any issues, use .stop to stop all tasks
"""
            await event.reply(help_text, parse_mode='md')

        @self.client.on(events.NewMessage(pattern=r'[!/\.]hiyaok'))
        async def hiyaok_handler(event):
            if event.sender_id != event.client.uid:
                return
                
            if not event.is_reply:
                await event.reply("❌ **Error:** Please reply to a message to forward", parse_mode='md')
                return
            
            # Check if maximum tasks reached
            if len(self.forward_tasks) >= 10:
                await event.reply(
                    "⚠️ **Error:** Maximum forward tasks (10) reached!\n"
                    "Use `.stop` or `.delforward` to remove existing tasks first.",
                    parse_mode='md'
                )
                return

            try:
                args = event.text.split()
                if len(args) != 2:
                    raise ValueError
                delay = int(args[1])
                if delay < 1:
                    await event.reply("⚠️ **Error:** Delay must be at least 1 minute", parse_mode='md')
                    return
            except ValueError:
                await event.reply(
                    "❌ **Error:** Invalid command format\n"
                    "Usage: `.hiyaok <delay>`\n"
                    "Example: `.hiyaok 5` (5 minutes delay)",
                    parse_mode='md'
                )
                return

            replied_msg = await event.get_reply_message()
            task_id = f"{replied_msg.chat_id}_{replied_msg.id}"

            if task_id in self.forward_tasks:
                await event.reply(
                    "⚠️ **Error:** This message is already being forwarded!\n"
                    f"Task ID: `{task_id}`",
                    parse_mode='md'
                )
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
            initial_msg = await event.reply("🔄 **Starting forward process...**", parse_mode='md')

            while task.running:
                try:
                    # Try to get the message first to check if it exists
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
                                failed_groups.append(f"{dialog.title}: Bot is banned/restricted")
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

📝 **Message Preview:**
`{task.last_preview[:100]}...`

📈 **Current Cycle:**
✅ Success: `{success}`
❌ Failed: `{failed}`

📊 **Total Stats:**
✅ Total Success: `{task.success_count}`
❌ Total Failed: `{task.failed_count}`

⚠️ **Failed Groups (Last Cycle):**
```
{chr(10).join(failed_groups[:5]) if failed_groups else 'None'}
{'...' if len(failed_groups) > 5 else ''}
```

⏳ Waiting {task.delay} minutes before next cycle...
                    """
                    await initial_msg.edit(status, parse_mode='md')

                    if task.running:
                        await asyncio.sleep(task.delay * 60)

                except RPCError as e:
                    if "MESSAGE_ID_INVALID" in str(e) or not message:
                        runtime = datetime.now() - task.start_time
                        error_msg = f"""
⚠️ **Forward Task Stopped!**

❌ **Reason:** Original message was deleted or not found
🆔 **Task ID:** `{task_id}`

📊 **Final Stats:**
✅ Total Success: `{task.success_count}`
❌ Total Failed: `{task.failed_count}`
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

Task will continue in {task.delay} minutes...
                        """
                        await initial_msg.edit(error_msg, parse_mode='md')
                        if task.running:
                            await asyncio.sleep(task.delay * 60)

                except Exception as e:
                    error_msg = f"""
⚠️ **Forward Error:**
Task ID: `{task_id}`
Error: `{str(e)}`

Task will continue in {task.delay} minutes...
                    """
                    await initial_msg.edit(error_msg, parse_mode='md')
                    if task.running:
                        await asyncio.sleep(task.delay * 60)

        @self.client.on(events.NewMessage(pattern=r'[!/\.]detail'))
        async def detail_handler(event):
            if event.sender_id != event.client.uid:
                return

            if not self.forward_tasks:
                await event.reply("📝 No active forward tasks.", parse_mode='md')
                return

            details = []
            for task_id, task in self.forward_tasks.items():
                runtime = datetime.now() - task.start_time
                hours, remainder = divmod(runtime.seconds, 3600)
                minutes, seconds = divmod(remainder, 60)

                details.append(f"""
🔄 **Task ID:** `{task_id}`
📝 **Preview:** `{task.last_preview[:100]}...`
⏱ **Delay:** `{task.delay} minutes`
⏳ **Runtime:** `{hours}h {minutes}m {seconds}s`
📊 **Stats:**
• Total Success: `{task.success_count}`
• Total Failed: `{task.failed_count}`
""")

            await event.reply("📋 **Active Forward Tasks:**\n" + "\n".join(details), parse_mode='md')

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
                    await event.reply("⚠️ **Error:** Delay must be at least 1 minute", parse_mode='md')
                    return

                if task_id in self.forward_tasks:
                    self.forward_tasks[task_id].delay = delay
                    await event.reply(
                        f"⏱️ **Success:** Delay for task `{task_id}` set to `{delay}` minutes", 
                        parse_mode='md'
                    )
                else:
                    await event.reply("❌ **Error:** Task not found!", parse_mode='md')
            except ValueError:
                await event.reply(
                    "❌ **Error:** Invalid command format\n"
                    "Usage: `.setdelay <task_id> <minutes>`\n"
                    "Example: `.setdelay 123_456 5`",
                    parse_mode='md'
                )

        @self.client.on(events.NewMessage(pattern=r'[!/\.]stop'))
        async def stop_handler(event):
            if event.sender_id != event.client.uid:
                return
                
            stopped_count = len(self.forward_tasks)
            if stopped_count == 0:
                await event.reply("ℹ️ No active tasks to stop.", parse_mode='md')
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
                
            await event.reply(
                f"🛑 **Stopped {stopped_count} forward tasks**\n\n"
                "**Task Details:**" + "\n".join(task_details),
                parse_mode='md'
            )

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
✅ **Forward task deleted**

🆔 **Task Details:**
• Task ID: `{task_id}`
• Success: `{task.success_count}`
• Failed: `{task.failed_count}`
• Runtime: `{hours}h {minutes}m {seconds}s`
                    """, parse_mode='md')
                else:
                    await event.reply(
                        "❌ **Error:** Task not found!\n"
                        "Use `.detail` to see active tasks.",
                        parse_mode='md'
                    )
            except IndexError:
                await event.reply(
                    "❌ **Error:** Please specify task ID\n"
                    "Usage: `.delforward <task_id>`\n"
                    "Use `.detail` to see task IDs.",
                    parse_mode='md'
                )

        @self.client.on(events.NewMessage(pattern=r'[!/\.]listgrup'))
        async def listgrup_handler(event):
            if event.sender_id != event.client.uid:
                return
                
            groups = []
            async for dialog in self.client.iter_dialogs():
                if dialog.is_group:
                    member_count = await self.client.get_participants(dialog, limit=0)
                    groups.append(f"📢 Group: {dialog.title}\n"
                                f"🆔 ID: `{dialog.id}`\n"
                                f"👥 Members: {len(member_count)}\n"
                                f"{'🚫 Banned' if dialog.id in self.banned_groups else '✅ Active'}\n")
            
            groups_text = "\n".join(groups)
            
            if len(groups_text) > 4000:
                with open("groups_list.txt", "w", encoding='utf-8') as f:
                    f.write(groups_text)
                await event.reply("📋 Group list is too long, sending as file...",
                                  file="groups_list.txt")
                os.remove("groups_list.txt")
            else:
                await event.reply(f"**📋 Your Groups List:**\n\n{groups_text}",
                                  parse_mode='md')

        @self.client.on(events.NewMessage(pattern=r'[!/\.]ban'))
        async def ban_handler(event):
            if event.sender_id != event.client.uid:
                return
                
            if event.is_group:
                if event.chat_id not in self.banned_groups:
                    self.banned_groups.add(event.chat_id)
                    group = await event.get_chat()
                    await event.reply(f"""
🚫 **Group Banned from Forwards**

👥 **Group Details:**
• Name: `{group.title}`
• ID: `{event.chat_id}`

Use `.deleteban` in this group to unban.
                    """, parse_mode='md')
                else:
                    await event.reply("ℹ️ This group is already banned from forwards.", parse_mode='md')
            else:
                await event.reply("❌ This command only works in groups!", parse_mode='md')

        @self.client.on(events.NewMessage(pattern=r'[!/\.]listban'))
        async def listban_handler(event):
            if event.sender_id != event.client.uid:
                return
                
            if not self.banned_groups:
                await event.reply("📋 **No banned groups**", parse_mode='md')
                return
                
            banned = []
            for group_id in self.banned_groups:
                try:
                    group = await self.client.get_entity(group_id)
                    banned.append(f"• {group.title} (`{group_id}`)")
                except:
                    banned.append(f"• Unknown Group (`{group_id}`)")
            
            await event.reply(f"""
📋 **Banned Groups List:**
{chr(10).join(banned)}

Total: `{len(self.banned_groups)}` groups
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
✅ **Group Unbanned**

👥 **Group Details:**
• Name: `{group.title}`
• ID: `{event.chat_id}`

This group will now receive forwards.
                    """, parse_mode='md')
                else:
                    await event.reply("ℹ️ This group is not banned.", parse_mode='md')
            else:
                await event.reply("❌ This command only works in groups!", parse_mode='md')

    async def _check_expiry(self):
        while True:
            check_expiry()
            await asyncio.sleep(3600)  # Check every hour
