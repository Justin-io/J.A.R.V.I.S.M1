import sys
import time
import requests
import threading
import subprocess
import cv2
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import pyautogui
import psutil
import speech_recognition as sr
import pyttsx3
import os
import json
import glob
import asyncio
import edge_tts
from contextlib import contextmanager
from dotenv import load_dotenv
from gesture_control import HandGestureController

# Load environment variables from .env file
load_dotenv()

# ==========================================
# ALSA ERROR SUPPRESSION (Linux Specific)
# ==========================================
@contextmanager
def no_alsa_err():
    """
    Suppress ALSA error messages by redirecting stderr to /dev/null.
    This catches C-level errors from ALSA/PyAudio that Python's try/except cannot.
    """
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        old_stderr = os.dup(sys.stderr.fileno())
        sys.stderr.flush()
        os.dup2(devnull, sys.stderr.fileno())
    except Exception:
        yield
        return

    try:
        yield
    finally:
        try:
            sys.stderr.flush()
            os.dup2(old_stderr, sys.stderr.fileno())
            os.close(old_stderr)
            os.close(devnull)
        except Exception:
            pass
# ==========================================

class JarvisAssistant:
    def __init__(self, event_callback=None):
        """
        Initialize the system, TTS engine, and print a "Systems Online" startup sequence.
        param event_callback: A function(event_name, data_dict) to send updates to UI.
        """
        self.event_callback = event_callback
        self.lock = threading.Lock()
        self.thread_local = threading.local()
        self.is_speaking = False
        self.last_created_item = None # Context for "that folder"
        
        # Initialize Text-to-Speech
        try:
            self.engine = pyttsx3.init()
            self.set_voice_config()
        except Exception as e:
            print(f"[JARVIS] Warning: TTS Engine failed to initialize: {e}")
            self.engine = None
        
        # Initialize Speech Recognition
        self.recognizer = sr.Recognizer()
        self.speech_process = None # Handle for the TTS process
        
        # Initialize Microphone with suppressed ALSA errors
        try:
            with no_alsa_err():
                self.microphone = sr.Microphone()
        except Exception:
            self.microphone = sr.Microphone() # Fallback

        # Check dependencies for health monitoring
        try:
            import psutil
            self.psutil = psutil
        except ImportError:
            self.psutil = None
            print("[JARVIS] Warning: 'psutil' module not found. Health monitoring disabled.")

        # OpenRouter Configuration
        self.api_key = os.getenv("OPENROUTER_API_KEY") # Kept for potential fallback, unused in offline mode
        self.model = "llama3.2:1b"
        
        # Startup Sequence
        # self.log_and_speak("Initializing systems...")
        # time.sleep(0.5)
        print("[JARVIS] Loading core modules...")
        # time.sleep(0.5)
        print("[JARVIS] Connecting to satellite network...")
        # time.sleep(0.5)
        self.log_and_speak("Systems Online.")
        
        # Start Background Health Monitor
        if self.psutil:
            self.monitor_thread = threading.Thread(target=self.monitor_system, daemon=True)
            self.monitor_thread.start()
            
        # Initialize Gesture Controller
        self.gesture_controller = HandGestureController()
        
        # Telegram Integration Context
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

    def emit_status(self, status):
        """Emit a status update to the UI."""
        if self.event_callback:
            self.event_callback('status_update', {'status': status})

    def send_telegram_photo(self, photo_path):
        """
        Directly uploads a photo to Telegram using the stored Chat ID.
        """
        if not self.telegram_chat_id:
            self.log_and_speak("I cannot establish a secure uplink. Please message me on Telegram first to handshake.")
            return "Chat ID missing."

        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            self.log_and_speak("Telegram protocols are not configured.")
            return "Token missing."

        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        self.log_and_speak("Transmitting visual data to secure device...")
        
        try:
            with open(photo_path, 'rb') as f:
                response = requests.post(url, data={'chat_id': self.telegram_chat_id}, files={'photo': f}, timeout=60)
                response.raise_for_status()
            
            self.log_and_speak("Transmission successful.")
            return "Screenshot sent to Telegram."
        except Exception as e:
            print(f"[JARVIS] Telegram Upload Error: {e}")
            self.log_and_speak("Upload failed due to network interference.")
            return f"Error: {e}"

    def emit_log(self, message, user=False):
        """Emit a log message to the UI."""
        if self.event_callback:
            event = 'user_log' if user else 'jarvis_log'
            self.event_callback(event, {'message': message})

    def set_voice_config(self):
        """
        Configure TTS voice settings for a more 'Jarvis-like' feel.
        """
        if not self.engine:
            return
            
        voices = self.engine.getProperty('voices')
        # Attempt to select a male English voice
        for voice in voices:
            if 'english' in voice.name.lower():
                self.engine.setProperty('voice', voice.id)
                if 'us' in voice.name.lower():
                    break
        
        self.engine.setProperty('rate', 160)
        self.engine.setProperty('volume', 1.0)

    async def _generate_edge_voice(self, text, output_file):
        """
        Generate voice file using Edge TTS (async).
        Voice: 'en-GB-RyanNeural' (Closest to JARVIS style) or 'en-US-ChristopherNeural'
        """
        voice = "en-GB-RyanNeural" 
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_file)

    def _speak_thread(self, text):
        """
        Worker thread for Edge TTS execution.
        """
        try:
            # Create a temporary file for the audio
            temp_file = os.path.join(os.getcwd(), "jarvis_voice_output.mp3")
            
            # Run the async generation in a new even loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._generate_edge_voice(text, temp_file))
            loop.close()

            # Play the audio file
            # Using mpg123 for playing mp3 in terminal/linux is robust
            if os.path.exists(temp_file):
                # Use subproccess Popen to allow killing the process
                self.speech_process = subprocess.Popen(["mpg123", "-q", temp_file])
                
                # Wait for process while checking for interrupt
                while self.speech_process.poll() is None:
                     if self.check_for_interrupt():
                         self.speech_process.terminate()
                         print("[JARVIS] Speech interrupted.")
                         break
                     time.sleep(0.1)
                
            # Cleanup
            if os.path.exists(temp_file):
                os.remove(temp_file)
                
        except Exception as e:
            print(f"[JARVIS] Voice Error: {e}")
        finally:
            self.is_speaking = False
            self.is_speaking = False
            self.emit_status("idle")
            self.speech_process = None

    def check_for_interrupt(self):
        """
        Listens for a brief moment to check for 'stop' keywords.
        Returns True if interrupted.
        """
        # We need a separate recognizer instance to avoid conflict with main loop if threaded (but here we are in speak thread)
        # Actually, using a simple short-listen strategy with Energy Threshold
        try:
            # Only check if we are actually speaking
            if not self.is_speaking:
                return False

            # Non-blocking check? It is hard in a while loop.
            # Faster approach: Use a dedicated 'Hotword' listener style or check microphone energy.
            # For simplicity in this loop without blocking playback too much:
            # We can't really "listen" for words while playing audio without echo cancellation
            # BUT the user asked for it. We will try to peek at audio levels or just a generic 'stop' input if possible.
            
            # Since full recog is slow, we will assume the main loop handles the listening?
            # NO, the main loop is BLOCKED by t.join() in log_and_speak.
            # We need to change log_and_speak to NOT join if we want parallel listening.
            return False 
        except:
            return False

    def log_and_speak(self, text):
        """
        Print to console and speak the text using Edge TTS.
        """
        # Ensure only one thread speaks at a time
        with self.lock:
            print(f"[JARVIS] {text}")
            self.emit_log(text)
            
            # Check for silent mode (e.g. from Telegram)
            if getattr(self.thread_local, 'silent', False):
                return

            self.emit_status("speaking")
            self.is_speaking = True
            
            # Start speaking in a separate thread
            t = threading.Thread(target=self._speak_thread, args=(text,))
            t.start()

            # Listen for interruption while speaking
            # We create a temporary recognizer for interruption
            interrupt_rec = sr.Recognizer()
            interrupt_rec.energy_threshold = 3000
            
            # Monitor until speech thread ends
            while t.is_alive():
                try:
                    with no_alsa_err():
                         with sr.Microphone() as source:
                            # Short listen span
                            try:
                                audio = interrupt_rec.listen(source, timeout=1, phrase_time_limit=2)
                                word = interrupt_rec.recognize_google(audio).lower()
                                if any(k in word for k in ["stop", "jarvis", "hey", "no", "cancel", "shut up"]):
                                    # Signal interrupt
                                    if self.speech_process:
                                        self.speech_process.terminate()
                                    t.join(timeout=0.1)
                                    print(f"[JARVIS] Interrupted by user: {word}")
                                    break
                            except sr.WaitTimeoutError:
                                pass # No speech, continue playing
                            except sr.UnknownValueError:
                                pass # Speech not recognized, continue
                            except:
                                pass
                except:
                    pass
                time.sleep(0.1)

            # Ensure thread finishes
            t.join()

    
    def get_system_health(self):
        """
        Retrieves battery and temperature stats using psutil.
        Returns a dictionary with 'battery', 'plugged', and 'temp' (if available).
        """
        if not self.psutil:
            return None
            
        stats = {}
        battery = self.psutil.sensors_battery()
        if battery:
            stats['battery'] = battery.percent
            stats['plugged'] = battery.power_plugged
        
        # Note: Temperature is OS/hardware dependent
        temps = self.psutil.sensors_temperatures() if hasattr(self.psutil, "sensors_temperatures") else {}
        # Try to find a core temperature (common keys: 'coretemp', 'cpu_thermal', 'k10temp')
        core_temp = None
        for key in ['coretemp', 'package_id_0', 'cpu_thermal', 'k10temp']:
            if key in temps:
                core_temp = temps[key][0].current
                break
        
        if core_temp:
            stats['temp'] = core_temp
        
        # CPU Usage
        stats['cpu'] = self.psutil.cpu_percent(interval=0.1)
        
        # Memory Usage
        mem = self.psutil.virtual_memory()
        stats['memory'] = mem.percent
        
        # Disk Usage
        disk = self.psutil.disk_usage('/')
        stats['disk'] = disk.percent
        
        # Battery Time Left
        if battery and not battery.power_plugged:
            secsleft = battery.secsleft
            if secsleft != self.psutil.POWER_TIME_UNLIMITED and secsleft != self.psutil.POWER_TIME_UNKNOWN:
                stats['time_left'] = f"{secsleft // 3600} hours and {(secsleft % 3600) // 60} minutes"
            
        return stats

    def send_notification(self, title, message):
        """
        Send a desktop notification using notify-send.
        """
        try:
            subprocess.run(["notify-send", title, message], check=False)
        except Exception as e:
            print(f"[JARVIS] Notification error: {e}")

    def set_brightness(self, level_percent):
        """
        Set screen brightness using xrandr.
        Arg: level_percent (int) 0-100
        """
        try:
            # 1. auto-detect output
            output = subprocess.check_output("xrandr | grep ' connected' | awk '{print $1}'", shell=True).decode().strip().split('\n')[0]
            
            if not output:
                self.log_and_speak("Unable to detect display output.")
                return

            # Convert 0-100 to 0.0-1.0
            val = max(10, min(100, int(level_percent))) / 100.0
            
            cmd = f"xrandr --output {output} --brightness {val}"
            os.system(cmd)
            self.log_and_speak(f"Display brightness set to {level_percent} percent.")
            
        except Exception as e:
            print(f"[JARVIS] Brightness error: {e}")
            self.log_and_speak("Brightness control failed.")

    def control_volume(self, command):
        """
        Control system volume using amixer.
        Args: 'up', 'down', 'mute'
        """
        try:
            if command == "up":
                subprocess.run(["amixer", "-D", "pulse", "sset", "Master", "5%+", "unmute"], check=False)
                self.log_and_speak("Volume raised.")
            elif command == "down":
                subprocess.run(["amixer", "-D", "pulse", "sset", "Master", "5%-", "unmute"], check=False)
                self.log_and_speak("Volume lowered.")
            elif command == "mute":
                subprocess.run(["amixer", "-D", "pulse", "sset", "Master", "toggle"], check=False)
                self.log_and_speak("Audio output toggled.")
        except Exception as e:
            print(f"[JARVIS] Volume control error: {e}")
            self.log_and_speak("I cannot access audio controls.")

    def report_health(self):
        """
        Analyzes health stats.
        If critical (Battery < 20% or Temp > 80C), speaks details.
        Otherwise, gives a standard 'Systems optimal' response.
        """
        stats = self.get_system_health()
        if not stats:
            self.log_and_speak("Diagnostic systems unavailable.")
            return

        issues = []
        if 'battery' in stats and stats['battery'] < 20 and not stats.get('plugged'):
            issues.append(f"Battery level critical at {stats['battery']} percent.")
            if 'time_left' in stats:
                issues.append(f"Estimated time remaining: {stats['time_left']}.")
        
        if 'temp' in stats and stats['temp'] > 80:
            issues.append(f"Core temperature high at {stats['temp']} degrees.")
        
        if 'cpu' in stats and stats['cpu'] > 90:
            issues.append(f"CPU usage critical at {stats['cpu']} percent.")
            
        if 'memory' in stats and stats['memory'] > 90:
            issues.append(f"Memory usage critical at {stats['memory']} percent.")

        if issues:
            self.log_and_speak("Warning. " + " ".join(issues))
        else:
            status_summary = f"Systems optimal. Battery at {stats.get('battery', 'unknown')} percent. CPU at {stats.get('cpu', 'unknown')} percent."
            self.log_and_speak(status_summary)

    def monitor_system(self):
        """
        Background thread to check system health periodically.
        Speaks ONLY if critical thresholds are breached.
        """
        while True:
            try:
                stats = self.get_system_health()
                if stats:
                    alert_needed = False
                    msg_parts = []
                    
                    # Check Battery
                    if 'battery' in stats and stats['battery'] < 15 and not stats.get('plugged'):
                        alert_needed = True
                        msg_parts.append(f"Critical power level: {stats['battery']} percent.")
                    
                    # Check Temp
                    if 'temp' in stats and stats['temp'] > 85:
                        alert_needed = True
                        msg_parts.append(f"Caution: System overheating at {stats['temp']} degrees.")
                        
                    # Check CPU
                    if 'cpu' in stats and stats['cpu'] > 95:
                         alert_needed = True
                         msg_parts.append(f"High CPU load detected: {stats['cpu']} percent.")

                    # Check Memory
                    if 'memory' in stats and stats['memory'] > 95:
                         alert_needed = True
                         msg_parts.append(f"Memory resources depleted: {stats['memory']} percent.")
                    
                    if alert_needed:
                        # Send desktop notification as well
                        self.send_notification("System Alert", " ".join(msg_parts))
                        self.log_and_speak("Alert. " + " ".join(msg_parts))
                        # Wait longer if we just spoke an alert to avoid spamming (e.g., 5 minutes)
                        time.sleep(300) 
                        continue

            except Exception as e:
                print(f"[JARVIS] Monitor error: {e}")
            
            # Check every minute
            time.sleep(60)

    def listen(self):
        """
        Listen for voice input and return recognized text. 
        Detailed for 'well optimised' performance and error handling.
        """
        try:
             # Find 'pulse' device index if available, otherwise default
             mic_index = None
             for i, name in enumerate(sr.Microphone.list_microphone_names()):
                 if "pulse" in name.lower():
                     mic_index = i
                     break
            
             # Apply suppression when opening the microphone stream
             with no_alsa_err():
                 with sr.Microphone(device_index=mic_index) as source:
                    print("\n[JARVIS] Listening...")
                    self.emit_status("listening")
                    
                    # Disable dynamic thresholding to avoid calibration errors
                    self.recognizer.dynamic_energy_threshold = False
                    self.recognizer.energy_threshold = 3000
                    print(f"[JARVIS] Energy Threshold fixed to: {self.recognizer.energy_threshold}")
                    
                    # Listen
                    try:
                        audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=8)
                    except sr.WaitTimeoutError:
                        return None
                
             print("[JARVIS] Processing...")
             self.emit_status("processing")
             
             try:
                 command = self.recognizer.recognize_google(audio).lower()
                 print(f"[JUSTIN] {command}")
                 self.emit_log(command, user=True)
                 return command
             except sr.UnknownValueError:
                 self.log_and_speak("I didn't catch that, Sir.")
                 # Save debug audio
                 with open("debug_last_audio.wav", "wb") as f:
                     f.write(audio.get_wav_data())
                 print("[JARVIS] Debug: Saved unrecognized audio to 'debug_last_audio.wav'")
                 return None
             except sr.RequestError:
                 self.log_and_speak("Network error. Switching to text input.")
                 return input("[JARVIS] Network Speech Error. Enter command: ").strip().lower()

        except Exception as e:
            print(f"[JARVIS] Microphone error: {e}")
            return input("[JARVIS] Enter command manually: ").strip().lower()

    def retrieve_intel(self, url):
        """
        Use BeautifulSoup to fetch a URL and strip specific text.
        """
        self.log_and_speak(f"Retrieving intel from {url}")
        try:
            response = requests.get(url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            title = soup.title.string.strip() if soup.title else "No Title Found"
            self.log_and_speak(f"Report Title: {title}")
            
            header = soup.find('h1')
            if header:
                print(f"[JARVIS] Primary Topic: {header.get_text().strip()}")
            
            print("[JARVIS] Intel retrieval complete.")
            
        except Exception as e:
            self.log_and_speak("Failed to retrieve intel.")
            print(f"[JARVIS] Error: {e}")

    def execute_web_task(self, query):
        """
        Use Selenium to launch Chrome, search for the query, and keep browser open.
        Arg: query (str) - The search term.
        """
        self.log_and_speak(f"Initiating web protocol for {query}")
        try:
            options = webdriver.ChromeOptions()
            options.add_experimental_option("detach", True)
            
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            
            driver.get("https://www.google.com")
            
            search_box = driver.find_element(By.NAME, "q")
            search_box.send_keys(query)
            search_box.send_keys(Keys.RETURN)
            
            self.log_and_speak("Search executed.")
            
        except Exception as e:
            print(f"[JARVIS] Web task protocol failed: {e}")
            self.log_and_speak("There was an error with the web driver.")

    def ask_ai(self, prompt, system_instruction=None, json_mode=False):
        """
        Send a prompt to local Ollama instance and return the AI's response.
        Arg: json_mode (bool) - If True, enforces JSON output from the model.
        """
        if not system_instruction:
            system_instruction = "You are J.A.R.V.I.S., a highly intelligent AI assistant. Keep responses concise, sophisticated, and professional."

        # self.log_and_speak("Processing locally...")
        url = "http://localhost:11434/api/chat"
        
        data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            "stream": False
        }
        
        if json_mode:
            data["format"] = "json"

        try:
            response = requests.post(url, json=data, timeout=30)
            response.raise_for_status()
            result = response.json()
            ai_message = result['message']['content']
            return ai_message.strip()
        except requests.exceptions.ConnectionError:
            print("[JARVIS] Ollama connection failed. Is the server running?")
            return "I cannot connect to my local neural core. Please ensure the Ollama service is active."
        except Exception as e:
            print(f"[JARVIS] AI Error: {e}")
            return "I encountered a processing error in my offline node."

    def determine_intent(self, command):
        """
        Analyze the user's intent. First checks a regex-based fast path.
        If no match, falls back to the LLM.
        """
        # 1. Fast Path (Bypass LLM for speed)
        command_lower = command.lower().strip()
        
        # Volume
        if any(w in command_lower for w in ["volume up", "louder", "turn it up"]):
            return {"action": "volume", "type": "up"}
        if any(w in command_lower for w in ["volume down", "quieter", "turn it down", "lower output"]):
            return {"action": "volume", "type": "down"}
        if "mute" in command_lower or "silent" in command_lower:
            return {"action": "volume", "type": "mute"}
            
        # Visuals
        if "screenshot" in command_lower:
            if "delete" in command_lower:
                 return {"action": "screenshot", "sub_action": "delete_latest"}
            if "telegram" in command_lower or "send" in command_lower:
                 return {"action": "telegram", "sub_action": "send_latest_screenshot"}
            return {"action": "screenshot", "sub_action": "take"}
            
        if any(w in command_lower for w in ["photo", "picture", "selfie", "camera"]):
            if "open" in command_lower or "show" in command_lower:
                return {"action": "file", "operation": "open", "name": "latest_photo"}
            return {"action": "camera", "sub_action": "take_photo"}

        # System
        if any(w in command_lower for w in ["shutdown system", "power off", "quit program", "exit jarvis"]):
            return {"action": "system", "type": "shutdown"}
        if "brightness" in command_lower:
            # Extract number
            import re
            nums = re.findall(r'\d+', command_lower)
            level = nums[0] if nums else "50"
            return {"action": "brightness", "level": str(level)}

        # Apps
        if command_lower.startswith("open ") or command_lower.startswith("launch "):
            app_name = command_lower.replace("open ", "").replace("launch ", "").strip()
            # Catch "the photo" special case early
            if app_name in ["photo", "picture", "image", "latest photo"]:
                 return {"action": "file", "operation": "open", "name": "latest_photo"}
            return {"action": "app", "name": app_name}
            
        # Web
        if "google" in command_lower or "search for" in command_lower or "search" in command_lower:
            query = command_lower.replace("search for", "").replace("search", "").replace("google", "").strip()
            return {"action": "web", "type": "search", "query": query}
            
        # Files
        if "list files" in command_lower or "ls" in command_lower:
             return {"action": "file", "operation": "list", "name": "."}
             
        # Gestures
        if "gesture" in command_lower:
            if "on" in command_lower or "activate" in command_lower:
                return {"action": "system", "type": "gesture_on"}
            if "off" in command_lower or "deactivate" in command_lower or "stop" in command_lower:
                return {"action": "system", "type": "gesture_off"}

        # Fallback to Terminal for simple "turn on/off" things not covered by system
        if "turn on" in command_lower or "turn off" in command_lower:
            # This is faster than LLM for simple toggles
            return {"action": "terminal", "instruction": command_lower}

        # Common Q&A Patterns (Fast Path to ASK_AI)
        qa_triggers = ["what is", "who is", "define", "how to", "tell me", "explain", "write a"]
        if any(command_lower.startswith(t) for t in qa_triggers):
             return {"action": "ask_ai", "prompt": command}

        # 2. Slow Path (LLM) - Only for unknown queries
        self.log_and_speak("Analyzing complex request...") # Re-enable log for slow path so user knows why it's waiting
        system_prompt = """
        You are an intent classifier. Map the user's command to the most appropriate JSON object from the list below.
        
        Supported Actions:
        - SCREENSHOT: {"action": "screenshot", "sub_action": "take"}
        - CAMERA: {"action": "camera", "sub_action": "take_photo"}
        - DELETE LAST SCREENSHOT: {"action": "screenshot", "sub_action": "delete_latest"}
        - SEND SCREENSHOT TO TELEGRAM: {"action": "telegram", "sub_action": "send_latest_screenshot"}
        - WEB SEARCH: {"action": "web", "type": "search", "query": "search terms"}
        - WEB INTEL: {"action": "web", "type": "scrape", "url": "http://url..."}
        - OPEN APP: {"action": "app", "name": "app name"}
        - SYSTEM HEALTH: {"action": "system", "type": "health"}
        - SYSTEM SHUTDOWN: {"action": "system", "type": "shutdown"} (ONLY for power off/reboot/quit)
        - BRIGHTNESS: {"action": "brightness", "level": "50"}
        - TERMINAL: {"action": "terminal", "instruction": "instruction"} (Use for wifi, ping, lists, updates, etc.)
        - GESTURES: {"action": "system", "type": "gesture_on" or "gesture_off"}
        - FILE OPEN: {"action": "file", "operation": "open", "name": "filename or 'latest_photo'"}
        - CHAT: {"action": "chat", "response": "Reply text"}
        - ASK_AI: {"action": "ask_ai", "prompt": "User's question"}

        Examples:
        "Define thermometer" -> {"action": "ask_ai", "prompt": "Define thermometer"}
        "Who is the president?" -> {"action": "ask_ai", "prompt": "Who is the president?"}
        "Write a poem" -> {"action": "ask_ai", "prompt": "Write a poem"}
        "Take a screenshot" -> {"action": "screenshot", "sub_action": "take"}
        "Send to telegram" -> {"action": "telegram", "sub_action": "send_latest_screenshot"}
        "Search Google for cats" -> {"action": "web", "type": "search", "query": "cats"}
        "Open calculator" -> {"action": "app", "name": "calculator"}
        "Quit" -> {"action": "system", "type": "shutdown"}
        "Open calculator" -> {"action": "app", "name": "calculator"}
        "Quit" -> {"action": "system", "type": "shutdown"}
        "Turn off the computer" -> {"action": "system", "type": "shutdown"}
        "Turn on wifi" -> {"action": "terminal", "instruction": "turn on wifi"}
        "Check disk usage" -> {"action": "terminal", "instruction": "check disk usage"}
        "List files" -> {"action": "terminal", "instruction": "list files"}
        "Update system" -> {"action": "terminal", "instruction": "update system"}
        "Set brightness to 50%" -> {"action": "brightness", "level": "50"}
        "Hello" -> {"action": "chat", "response": "Hello, Sir."}
        "Can you hear me?" -> {"action": "chat", "response": "Loud and clear, Sir."}
        "Are you there?" -> {"action": "chat", "response": "I am always here."}
        "Who are you?" -> {"action": "chat", "response": "I am J.A.R.V.I.S."}
        
        Respond with ONLY the JSON object.
        """
        
        try:
            # Enable JSON mode to force structured output
            response = self.ask_ai(command, system_instruction=system_prompt, json_mode=True)
            
            # Basic cleanup just in case
            clean_json = response.replace("```json", "").replace("```", "").strip()
            return json.loads(clean_json)
        except json.JSONDecodeError:
            print(f"[JARVIS] Intent parsing failed. Raw: {response}")
            return {"action": "chat", "response": str(response)}
        except Exception as e:
            print(f"[JARVIS] Intent Error: {e}")
            return {"action": "chat", "response": "Internal processing error."}

    def engage_desktop_mode(self, app_name):
        """
        Use PyAutoGUI to minimize windows, open Run dialog, and launch an app.
        """
        self.log_and_speak(f"Launching {app_name}")
        try:
            # Minimize all windows
            pyautogui.hotkey('win', 'd')
            time.sleep(0.5)
            
            # Open Run dialog
            if os.name == 'nt': # Windows
                pyautogui.hotkey('win', 'r')
                time.sleep(0.5)
                pyautogui.typewrite(app_name)
                pyautogui.press('enter')
            else:
                # Linux/Mac fallback
                pyautogui.hotkey('alt', 'f2') 
                time.sleep(1)
                pyautogui.typewrite(app_name)
                pyautogui.press('enter')
            
            print(f"[JARVIS] {app_name} command sent.")
            
        except Exception as e:
            print(f"[JARVIS] Desktop engagement error: {e}")

    def activate_gestures(self):
        self.log_and_speak("Activating holographic interface protocols.")
        try:
            self.gesture_controller.start()
            self.log_and_speak("Gesture control online.")
        except Exception as e:
            print(f"[JARVIS] Gesture error: {e}")
            self.log_and_speak("Failed to initialize gesture sensors.")

    def deactivate_gestures(self):
        self.log_and_speak("Deactivating gesture control.")
        try:
            self.gesture_controller.stop()
        except Exception as e:
            print(f"[JARVIS] Gesture stop error: {e}")

    def take_screenshot(self):
        """
        Capture the current screen and save it to a file.
        """
        self.log_and_speak("Capturing visual data...")
        try:
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            filename = f"jarvis_screenshot_{timestamp}.png"
            screenshot = pyautogui.screenshot()
            screenshot.save(filename)
            self.log_and_speak(f"Screenshot saved as {filename}")
            return os.path.abspath(filename)
        except Exception as e:
            print(f"[JARVIS] Screenshot error: {e}")
            self.log_and_speak("I missed the shot, Sir.")

    def take_photo(self):
        """
        Capture a photo using the webcam.
        """
        self.log_and_speak("Accessing optical sensors...")
        try:
            cam = cv2.VideoCapture(0)
            if not cam.isOpened():
                self.log_and_speak("Optical sensors unresponsive.")
                return None
            
            # Allow camera to warm up
            time.sleep(0.5)
            
            ret, frame = cam.read()
            cam.release()
            
            if not ret:
                self.log_and_speak("Failed to capture visual image.")
                return None
            
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            filename = f"jarvis_camera_{timestamp}.png"
            cv2.imwrite(filename, frame)
            
            self.log_and_speak(f"Image captured.")
            return os.path.abspath(filename)
            
        except Exception as e:
            print(f"[JARVIS] Camera error: {e}")
            self.log_and_speak("Optical sensor malfunction.")
            return None

    def execute_iterative_workflow(self, items, action_func, description="processing items"):
        """
        Executes a workflow on a list of items, providing step-by-step feedback (Agentic behavior).
        """
        if not items:
            self.log_and_speak(f"No targets found for {description}.")
            return "No items found."

        total = len(items)
        self.log_and_speak(f"Initiating agentic workflow. Identified {total} targets for {description}.")
        time.sleep(0.5)
        
        completed = 0
        for i, item in enumerate(items, 1):
            item_name = os.path.basename(item)
            self.log_and_speak(f"Step {i}: Processing {item_name}...")
            try:
                action_func(item)
                completed += 1
            except Exception as e:
                print(f"[JARVIS] Workflow error on {item}: {e}")
                self.log_and_speak(f"Failed to process {item_name}.")
            
            # Artificial delay to mimic "thinking"/processing and allow user to appreciate the flow
            time.sleep(0.5)
        
        self.log_and_speak(f"Workflow complete. Successfully processed {completed} of {total} items.")
        return f"Processed {completed} items."

    def delete_latest_screenshot(self):
        """
        Find and delete the most recent screenshot.
        """
        try:
            # Find files matching the pattern
            list_of_files = glob.glob('jarvis_screenshot_*.png')
            if not list_of_files:
                self.log_and_speak("No screenshots found to delete, Sir.")
                return

            # Find the latest file based on modification time
            latest_file = max(list_of_files, key=os.path.getmtime)
            
            self.log_and_speak(f"Deleting most recent capture: {os.path.basename(latest_file)}")
            os.remove(latest_file)
            self.log_and_speak("Deletion confirmed.")
            
        except Exception as e:
            print(f"[JARVIS] Deletion error: {e}")
            self.log_and_speak("I was unable to delete the file, Sir.")

    def perform_file_operation(self, operation, target):
        """
        Handle file system operations like creating folders or files.
        Arg: operation (str) - create_folder, create_file, list
        Arg: target (str) - path/name
        """
        try:
            # Resolve target path relative to CWD if not absolute
            if not os.path.isabs(target):
                target = os.path.join(os.getcwd(), target)
            
            # handle root path or empty basename
            display_name = os.path.basename(target) or target

            if operation == "create_folder":
                os.makedirs(target, exist_ok=True)
                self.last_created_item = target 
                self.log_and_speak(f"Created folder {display_name}")
                return f"Created folder {display_name}"
            
            elif operation == "create_file":
                if "." not in target:
                    target += ".txt"
                with open(target, 'w') as f:
                    pass
                self.last_created_item = target
                self.log_and_speak(f"Created file {display_name}")
                return f"Created file {display_name}"
            
            elif operation == "list" or operation == "list_files" or operation == "list_folder":
                if os.path.isdir(target):
                    items = os.listdir(target)
                    items_str = ", ".join(items[:20]) # Limit to 20 items for brevity
                    if len(items) > 20:
                        items_str += f" ... and {len(items)-20} more."
                    self.log_and_speak(f"Contents of {display_name}")
                    return f"Files in {display_name}:\n{items_str}"
                else:
                    return f"Directory not found: {display_name}"
                
            return "Operation not understood."

        except Exception as e:
            print(f"[JARVIS] File op error: {e}")
            self.log_and_speak("I encountered an error with the file system.")
            return f"Error: {e}"

    def agentic_terminal_action(self, instruction):
        """
        Uses AI to generate a terminal command and GUI automation to execute it.
        """
        self.log_and_speak("Engaging terminal agent.")
        
        # Safety Check: Block explicit shutdown commands here
        forbidden = ["shutdown", "reboot", "poweroff", "init 0", "init 6", "rm -rf /"]
        if any(f in instruction.lower() for f in forbidden):
             self.log_and_speak("Safety protocols prevent me from executing that instruction directly.")
             return "Command blocked by safety protocol."

        # 1. Generate Command via AI
        prompt = f"""
        You are a Linux Bash Command Generator. 
        User Request: "{instruction}"
        Context: Current Directory is "{os.getcwd()}". 
        Last Created Item: "{self.last_created_item if self.last_created_item else 'None'}"
        Task: Generate ONLY the one-line bash command to perform this. 
        If the user says "that folder", refer to Last Created Item.
        Use absolute paths if possible.
        Do NOT output markdown (```). Do NOT output explanations. ONLY the command string.
        """
        
        command_to_run = self.ask_ai(prompt)
        if not command_to_run:
            return "Failed to generate command."
            
        # Clean cleanup if AI adds quotes or markdown despite instructions
        command_to_run = command_to_run.replace("```bash", "").replace("```", "").strip()
        
        self.log_and_speak(f"Executing: {command_to_run}")
        
        try:
            # 2. Open Terminal (Win+T)
            pyautogui.hotkey('win', 't')
            time.sleep(1.5) # Wait for terminal
            
            # 3. Type command
            pyautogui.typewrite(command_to_run, interval=0.05)
            pyautogui.press('enter')
            
            # 4. Wait for execution (Simple heuristic delay)
            time.sleep(1.0)
            
            # 5. Close Terminal
            pyautogui.typewrite('exit', interval=0.05) 
            pyautogui.press('enter')
            
            return f"Executed: {command_to_run}"
            
        except Exception as e:
            print(f"[JARVIS] Terminal Agent Error: {e}")
            return f"Agent failed: {e}"

    def process_command(self, command, silent=False):
        """
        Process a text command using LLM-based intent analysis.
        """
        self.thread_local.silent = silent
        
        try:
            if not command:
                return None

            intent = self.determine_intent(command)
            action = intent.get("action")
            
            print(f"[JARVIS] Identified Intent: {intent}")

            if action == "screenshot":
                sub = intent.get("sub_action")
                if sub == "take":
                    filepath = self.take_screenshot()
                    return f"Screenshot taken.||SCREENSHOT:{filepath}||"
                elif sub == "delete_latest":
                    self.delete_latest_screenshot()
                    return "Latest screenshot deleted."
                elif sub == "delete_all":
                    screenshots = glob.glob('jarvis_screenshot_*.png')
                    screenshots.sort(key=os.path.getmtime)
                    return self.execute_iterative_workflow(
                        screenshots, 
                        os.remove, 
                        description="deleting all visual logs"
                    )

            elif action == "camera":
                if intent.get("sub_action") == "take_photo":
                    filepath = self.take_photo()
                    if filepath:
                        # Using SCREENSHOT tag to reuse existing Telegram logic
                        return f"Photo captured.||SCREENSHOT:{filepath}||"
                    return "Camera failed."

            elif action == "telegram":
                if intent.get("sub_action") == "send_latest_screenshot":
                     # Find latest screenshot OR camera photo
                    list_of_files = glob.glob('jarvis_screenshot_*.png') + glob.glob('jarvis_camera_*.png')
                    if not list_of_files:
                        self.log_and_speak("No visuals found.")
                        return "No files."
                    
                    latest_file = max(list_of_files, key=os.path.getmtime)
                    return self.send_telegram_photo(latest_file)

            elif action == "web":
                mode = intent.get("type")
                if mode == "search":
                    query = intent.get("query")
                    if query:
                        self.execute_web_task(query)
                        return f"Searching for {query}"
                elif mode == "scrape":
                    url = intent.get("url")
                    if url:
                        if not url.startswith("http"):
                            url = "http://" + url
                        self.retrieve_intel(url)
                        return "Intel retrieval initiated."

            elif action == "app":
                app_name = intent.get("name")
                if app_name:
                    # Use existing agentic terminal action or direct desktop engage
                    # We can reuse agentic_terminal_action for broader 'run/move/open' support
                    return self.agentic_terminal_action(f"open {app_name}")

            elif action == "system":
                ctype = intent.get("type")
                if ctype == "health":
                    self.report_health()
                    return "Health report complete."
                elif ctype in ["shutdown", "quit", "exit"]:
                    msg = "Powering down system. Goodbye, Sir."
                    self.log_and_speak(msg)
                    return msg
                elif ctype == "gesture_on":
                    self.activate_gestures()
                    return "Gestures activated."
                elif ctype == "gesture_off":
                    self.deactivate_gestures()
                    return "Gestures deactivated."
            
            elif action == "brightness":
                level = intent.get("level", 100)
                try:
                    self.set_brightness(int(str(level).replace("%", "")))
                except:
                    self.set_brightness(100)
                return f"Brightness set to {level}."

            elif action == "terminal":
                instruction = intent.get("instruction")
                if instruction:
                    return self.agentic_terminal_action(instruction)

            elif action == "volume":
                vtype = intent.get("type")
                if vtype:
                    self.control_volume(vtype)
                    return f"Volume {vtype}"

            elif action == "file":
                op = intent.get("operation")
                name = intent.get("name")
                
                if op == "open" and name == "latest_photo":
                    # Find latest visual (latest of *screenshots* or *camera*)
                    all_visuals = glob.glob('jarvis_screenshot_*.png') + glob.glob('jarvis_camera_*.png')
                    if all_visuals:
                        latest_file = max(all_visuals, key=os.path.getmtime)
                        # Construct absolute path
                        abs_path = os.path.abspath(latest_file)
                        self.log_and_speak("Displaying visual data.")
                        return self.agentic_terminal_action(f"xdg-open {abs_path}")
                    else:
                        self.log_and_speak("No photos found in archive.")
                        return "No photos."

                # Normalize name "." or nothing to current dir
                if not name or name == "root":
                    name = "."
                return self.perform_file_operation(op, name)

            elif action == "ask_ai":
                prompt = intent.get("prompt")
                if prompt:
                    # Direct query to the LLM (no JSON mode)
                    response = self.ask_ai(prompt, system_instruction="You are a helpful assistant. Be concise.")
                    self.log_and_speak(response)
                    return response

            # Default to Chat
            response_text = intent.get("response", "I am not sure how to respond to that.")
            self.log_and_speak(response_text)
            return response_text

        except Exception as e:
            print(f"[JARVIS] Error processing command: {e}")
            return "An error occurred while processing your command."
        finally:
            self.thread_local.silent = False

    def central_command(self):
        """
        Main loop to route commands to the correct method.
        """
        while True:
            try:
                self.emit_status("idle")
                command = self.listen()
                
                if not command:
                    continue

                # Process the command
                response = self.process_command(command)
                
                # Check for exit condition (based on the processed command)
                if response == "Powering down system. Goodbye, Sir.":
                    break

            except KeyboardInterrupt:
                print("\n[JARVIS] Forced shutdown.")
                break
            except Exception as e:
                print(f"[JARVIS] Critical error: {e}")

if __name__ == "__main__":
    jarvis = JarvisAssistant()
    jarvis.central_command()
