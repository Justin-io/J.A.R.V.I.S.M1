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
        await context.bot.send_message(chat_id=update.effective_chat.id, text="J.A.R.V.I.S. Online. Awaiting commands.")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message:
            user_text = update.message.text
            chat_id = update.effective_chat.id
            
            # Store ID for outbound messages
            if self.jarvis:
                if self.jarvis.telegram_chat_id != str(chat_id):
                    self.jarvis.telegram_chat_id = str(chat_id)
                    # Persist to .env
                    try:
                        with open(".env", "a") as f:
                            f.write(f"\nTELEGRAM_CHAT_ID={chat_id}")
                        print(f"[TELEGRAM] Secured new uplink ID: {chat_id}")
                    except Exception as e:
                        print(f"[JARVIS] Failed to persist chat ID: {e}")
            
            print(f"[TELEGRAM] Received: {user_text}")
        
        # Log to Jarvis UI as a user command
        self.jarvis.emit_log(f"[TELEGRAM] {user_text}", user=True)
        
        # Process command via Jarvis
        # Run in a separate thread to prevent blocking the async loop
        response = await asyncio.to_thread(self.jarvis.process_command, user_text, silent=True)
        
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
                except Exception as e:
                    print(f"[TELEGRAM] Error parsing screenshot path: {e}")

            # Send photo if available
            if photo_path:
                try:
                    await context.bot.send_photo(chat_id=update.effective_chat.id, photo=open(photo_path, 'rb'))
                except Exception as e:
                    print(f"[TELEGRAM] Failed to send photo: {e}")
                    text_to_send += " [Failed to upload screenshot]"

            # Send text response
            if text_to_send:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=text_to_send)
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Command processed.")

    def _run_bot(self):
        if not self.token:
            print("[JARVIS] Warning: TELEGRAM_BOT_TOKEN not found. Telegram interface disabled.")
            return

        # Create a new event loop for this thread
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        # Configure request with longer timeouts for file uploads
        request = HTTPXRequest(connect_timeout=60, read_timeout=60)
        self.application = ApplicationBuilder().token(self.token).request(request).build()
        
        start_handler = CommandHandler('start', self.start)
        echo_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), self.handle_message)
        
        self.application.add_handler(start_handler)
        self.application.add_handler(echo_handler)
        
        # Disable signal handling since we are in a background thread
        print("[JARVIS] Telegram Interface Initialized.")
        self.application.run_polling(stop_signals=None)

    def start_polling(self):
        """
        Starts the Telegram bot in a separate background thread.
        """
        thread = threading.Thread(target=self._run_bot, daemon=True)
        thread.start()
