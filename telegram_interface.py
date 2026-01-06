import os
import asyncio
import threading
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from telegram.request import HTTPXRequest

class TelegramInterface:
    def __init__(self, jarvis_instance):
        self.jarvis = jarvis_instance
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.application = None
        self.loop = None

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="jarvis online. Awaiting commands, Sir.")

    async def process_input(self, text, update, context):
        """
        Common processor for text and commands.
        """
        chat_id = update.effective_chat.id
        self.jarvis.emit_log(f"[telegram] {text}", user=True)
        
        # Store ID if new
        if self.jarvis and self.jarvis.telegram_chat_id != str(chat_id):
            self.jarvis.telegram_chat_id = str(chat_id)
            try:
                with open(".env", "a") as f:
                    f.write(f"\nTELEGRAM_CHAT_ID={chat_id}")
            except:
                pass

        # Process via Jarvis
        # We enforce "screenshot" command if it maps to that intent, 
        # but here we just pass the text.
        response = await asyncio.to_thread(self.jarvis.process_command, text, silent=True)
        
        if response:
            text_to_send = response
            photo_path = None
            
            # Check for screenshot attachment tag
            if "||SCREENSHOT:" in response:
                try:
                    parts = response.split("||SCREENSHOT:")
                    text_to_send = parts[0]
                    path_part = parts[1].replace("||", "").strip()
                    if path_part and path_part != "None" and os.path.exists(path_part):
                        photo_path = path_part
                except Exception:
                    pass

            # Send photo if available
            if photo_path:
                try:
                    await context.bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'))
                except Exception as e:
                    print(f"[telegram] Failed to send photo: {e}")
                    text_to_send += " [Upload Failed]"

            # Send text response
            if text_to_send and text_to_send.strip():
                await context.bot.send_message(chat_id=chat_id, text=text_to_send)
        else:
            await context.bot.send_message(chat_id=chat_id, text="Command processed.")


    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message and update.message.text:
            await self.process_input(update.message.text, update, context)

    async def cmd_screenshot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Force the input to be just "screenshot" to ensure the intent is caught
        await self.process_input("screenshot", update, context)

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        print(f"[telegram] Error: {context.error}")

    def _run_bot(self):
        if not self.token:
            print("[jarvis] Warning: TELEGRAM_BOT_TOKEN missing.")
            return

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        request = HTTPXRequest(connect_timeout=60, read_timeout=60)
        self.application = ApplicationBuilder().token(self.token).request(request).build()
        
        # Handlers
        self.application.add_handler(CommandHandler('start', self.start))
        self.application.add_handler(CommandHandler('screenshot', self.cmd_screenshot))
        self.application.add_handler(CommandHandler('photo', self.cmd_screenshot))
        
        # Catch-all for text AND other commands (slash commands not explicitly handled above)
        # We removed (~filters.COMMAND) so /any_other_command is passed as text
        self.application.add_handler(MessageHandler(filters.TEXT, self.handle_message))
        
        self.application.add_error_handler(self.error_handler)
        
        print("[jarvis] Telegram Interface Initialized.")
        try:
            self.application.run_polling(stop_signals=None, bootstrap_retries=-1)
        except Exception as e:
            print(f"[jarvis] Telegram Polling Stopped: {e}")

    def start_polling(self):
        """
        Starts the Telegram bot in a separate background thread.
        """
        thread = threading.Thread(target=self._run_bot, daemon=True)
        thread.start()
