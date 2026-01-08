from flask import Flask, render_template
from flask_socketio import SocketIO
from jarvis_assistant import JarvisAssistant
import threading
import webbrowser
import time
import os
from telegram_interface import TelegramInterface

# Define the Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'jarvis_secret_key'
socketio = SocketIO(app, cors_allowed_origins="*")

# Suppress annoying engineio/socketio logs
import logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.getLogger('engineio').setLevel(logging.ERROR)
logging.getLogger('socketio').setLevel(logging.ERROR)

# Global variables
jarvis = None
jarvis_thread = None

def jarvis_event_handler(event_name, data):
    """
    Callback function provided to JarvisAssistant to emit SocketIO events.
    """
    socketio.emit(event_name, data)

@socketio.on('stop_command')
def handle_stop_command():
    """
    Handle interrupt signal from Web UI.
    """
    print("[WebUI] Interrupt signal received.")
    if jarvis:
        jarvis.stop_speaking()


@app.route('/')
def index():
    return render_template('index.html')

def run_jarvis_logic():
    """
    Wrapper to run Jarvis in a background thread.
    """
    global jarvis
    # Initialize Jarvis with the event handler
    jarvis = JarvisAssistant(event_callback=jarvis_event_handler)
    
    # Initialize and start Telegram Interface
    telegram_bot = TelegramInterface(jarvis)
    telegram_bot.start_polling()
    
    # Wait a bit for the server to start fully before systems online
    time.sleep(2)
    
    # Start the central command loop
    jarvis.central_command()

if __name__ == '__main__':
    # Start Jarvis Logic in a separate thread
    jarvis_thread = threading.Thread(target=run_jarvis_logic, daemon=True)
    jarvis_thread.start()
    
    # Open the browser to the web UI
    # We delay slightly to ensure Flask is up
    threading.Timer(1.5, lambda: webbrowser.open('http://127.0.0.1:5200')).start()
    
    # Run the Flask server
    # Note: debug=True interacts poorly with threads/reloader in some envs, keeping False for stability
    socketio.run(app, host='0.0.0.0', port=5200, debug=False, allow_unsafe_werkzeug=True)
