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
import shutil
from dotenv import load_dotenv
from gesture_control import HandGestureController
from piper import PiperVoice
from piper.config import SynthesisConfig
import vosk
vosk.SetLogLevel(-1) # Silence Kaldi/Vosk logs

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
        
        # Initialize Speech Queue and Background Worker
        self.speech_queue = []
        self.speech_worker_thread = threading.Thread(target=self._speech_worker, daemon=True)
        self.speech_worker_thread.start()
        
        # Initialize Text-to-Speech
        try:
            self.engine = pyttsx3.init()
            self.set_voice_config()
        except Exception as e:
            print(f"[jarvis] Warning: TTS Engine failed to initialize: {e}")
            self.engine = None
        
        # Initialize Piper TTS
        try:
            model_path = "/home/justin/Desktop/jarvis_project/piper_tts/jarvis.onnx"
            # We assume the config .json is in the same folder with .json extension appended
            self.piper_voice = PiperVoice.load(model_path)
            print("[jarvis] Piper Neural TTS Initialized.")
        except Exception as e:
            print(f"[jarvis] Warning: Piper TTS failed to initialize: {e}")
            self.piper_voice = None
        
        # Initialize Speech Recognition
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 5000
        self.recognizer.pause_threshold = 0.6
        self.speech_process = None 
        
        # Check dependencies for health monitoring
        try:
            import psutil
            self.psutil = psutil
        except ImportError:
            self.psutil = None
            print("[jarvis] Warning: 'psutil' module not found. Health monitoring disabled.")

        # Initialize Gesture Controller
        self.gesture_controller = HandGestureController()
        
        # State tracking for deduplication
        self.last_spoken_text = ""
        self.last_spoken_time = 0.0
        try:
            with no_alsa_err():
                self.microphone = sr.Microphone()
        except Exception:
            self.microphone = sr.Microphone() # Fallback

        self.session = requests.Session()
        self.model = "llama3.2:1b"
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        
        # Startup Sequence
        print("[jarvis] Loading core modules...")
        self.emit_log("Connecting to satellite network...")
        self.perform_startup_check()
        
        # Start Background Health Monitor
        if self.psutil:
            self.monitor_thread = threading.Thread(target=self.monitor_system, daemon=True)
            self.monitor_thread.start()

        if self.psutil:
             self.telemetry_thread = threading.Thread(target=self.telemetry_loop, daemon=True)
             self.telemetry_thread.start()

    def perform_startup_check(self):
        """
        Speak a short, direct startup message.
        """
        current_time = time.strftime("%I:%M %p")
        stats = self.get_system_health()
        
        status_msg = f"Systems Online. {current_time}."
        if stats:
            batt = int(stats.get('battery', 0))
            status_msg += f" Battery {batt}%."
            
        self.log_and_speak(status_msg)

    def telemetry_loop(self):
        """
        Continuously emit system stats to the UI for real-time visualization.
        """
        while True:
            try:
                stats = self.get_system_health()
                if stats and self.event_callback:
                    self.event_callback('system_stats', stats)
            except Exception as e:
                print(f"[jarvis] Telemetry Error: {e}")
            time.sleep(5)

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
            print(f"[jarvis] Telegram Upload Error: {e}")
            self.log_and_speak("Upload failed due to network interference.")
            return f"Error: {e}"

    def emit_log(self, message, user=False):
        """Emit a log message to the UI and Print to Terminal."""
        prefix = "JUSTIN" if user else "jarvis"
        print(f"[{prefix}] {message}")
        if self.event_callback:
            self.event_callback('new_log', {'message': message, 'type': 'user' if user else 'system'})

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

    def _stream_piper_voice(self, text):
        """
        Generate and stream voice using Piper TTS directly to aplay.
        """
        if not self.piper_voice:
             print("[jarvis] Piper Voice not loaded. Fallback to print.")
             return

        # Prepare aplay command for raw 16-bit 22050Hz mono audio
        cmd = ["aplay", "-r", "22050", "-f", "S16_LE", "-t", "raw", "-"]
        
        try:
            self.speech_process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
            
            # Synthesize and stream directly to aplay's stdin
            # length_scale=1.05 for a slightly more sophisticated, deliberate tone
            config = SynthesisConfig(length_scale=1.05)
            for chunk in self.piper_voice.synthesize(text, syn_config=config):
                if self.speech_process is None: # Interrupted
                    break
                try:
                    self.speech_process.stdin.write(chunk.audio_int16_bytes)
                    self.speech_process.stdin.flush()
                except (BrokenPipeError, ValueError):
                    break
            
            # Close stdin to signal EOF
            if self.speech_process and self.speech_process.stdin:
                try:
                    self.speech_process.stdin.close()
                except:
                    pass
            
            # Wait for playback to finish
            if self.speech_process:
                self.speech_process.wait()
                
        except Exception as e:
            print(f"[jarvis] Piper Audio Error: {e}")
        finally:
            self.speech_process = None

    def _speak_thread(self, text):
        """
        Worker thread for Edge TTS execution.
        """
        try:
            if self.piper_voice:
                self._stream_piper_voice(text)
            elif self.engine:
                # Fallback to pyttsx3
                self.engine.say(text)
                self.engine.runAndWait()
            else:
                print(f"[jarvis] Fallback: {text}")
                
        except Exception as e:
            print(f"[jarvis] Voice Error: {e}")
        finally:
            pass # worker handles status

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

    def _speech_worker(self):
        """Background thread to process the speech queue sequentially."""
        while True:
            text = None
            with self.lock:
                if self.speech_queue:
                    text = self.speech_queue.pop(0)
            
            if text:
                self.is_speaking = True
                self.emit_status("speaking")
                self._stream_piper_voice(text)
                self.is_speaking = False
                self.emit_status("idle")
            else:
                time.sleep(0.1)

    def log_and_speak(self, text):
        """
        Print to console and queue the text for speech output.
        """
        self.emit_log(text)
        
        # Check for silent mode (e.g. from Telegram)
        if getattr(self.thread_local, 'silent', False):
            return
        
        # Anti-Echo: Prevent speaking the exact same phrase twice in < 2 seconds
        current_time = time.time()
        if text == self.last_spoken_text and (current_time - self.last_spoken_time) < 2.0:
             return
        
        self.last_spoken_text = text
        self.last_spoken_time = current_time

        with self.lock:
            self.speech_queue.append(text)

    def stop_speaking(self):
        """
        Immediately terminates the speech process and clears the queue.
        """
        with self.lock:
            self.speech_queue.clear()
        
        if self.speech_process:
            try:
                self.speech_process.terminate()
                self.speech_process.kill()
            except Exception as e:
                print(f"[jarvis] Error stopping speech: {e}")
            finally:
                self.speech_process = None
        
        self.is_speaking = False
        self.emit_status("idle")


    
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
            
        # PID
        stats['pid'] = os.getpid()

        return stats

    def send_notification(self, title, message):
        """
        Send a desktop notification using notify-send.
        """
        try:
            subprocess.run(["notify-send", title, message], check=False)
        except Exception as e:
            print(f"[jarvis] Notification error: {e}")

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
            print(f"[jarvis] Brightness error: {e}")
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
            print(f"[jarvis] Volume control error: {e}")
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
        if 'battery' in stats and stats['battery'] < 30 and not stats.get('plugged'):
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
                    if 'battery' in stats and stats['battery'] < 25 and not stats.get('plugged'):
                        alert_needed = True
                        msg_parts.append(f"Critical power level: {stats['battery']} percent.")
                    
                    # Check Temp
                    if 'temp' in stats and stats['temp'] > 75:
                        alert_needed = True
                        msg_parts.append(f"Caution: System overheating at {stats['temp']} degrees.")
                        
                    # Check CPU
                    if 'cpu' in stats and stats['cpu'] > 98:
                         alert_needed = True
                         msg_parts.append(f"System stress detected: {stats['cpu']} percent.")

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
                print(f"[jarvis] Monitor error: {e}")
            
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
                    # print("\n[jarvis] Listening...") # using emit_log
                    self.emit_status("listening")
                    self.emit_log("Listening...")
                    
                    # Disable dynamic thresholding to avoid calibration errors
                    self.recognizer.pause_threshold = 0.6 # Faster turnaround
                    self.recognizer.energy_threshold = 5000
                    
                    # Listen
                    try:
                        audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=10)
                    except sr.WaitTimeoutError:
                        return None
                
             self.emit_status("processing")
             self.emit_log("Processing...")
             # print("[jarvis] Processing...") # already emitted above
             try:
                 command = self.recognizer.recognize_google(audio).lower()
                 
                 if not command or not command.strip():
                     return None
                 
                 self.emit_log(f"Heard: '{command}'", user=True)

                 # Check for STOP command immediately (more permissive)
                 if any(w in command for w in ["stop", "silence", "shh", "quiet", "shut up"]):
                     self.stop_speaking()
                     self.emit_log("Command: STOP")
                     return None
                 
                 if command.startswith("jarvis"):
                     command = command.replace("jarvis", "").strip()
                 
                 if not command:
                     return None # Return None if command is empty after stripping "jarvis"
 
                 # Assuming process_command is called elsewhere or this method should return the command
                 # If process_command is meant to be called here, it needs to be defined or handled.
                 # For now, I'll return the command as per the original method's intent.
                 return command
             except sr.UnknownValueError:
                 self.emit_log("Audio not recognized.")
                 print("[jarvis] I didn't catch that, Sir.")
                 # Save debug audio
                 with open("debug_last_audio.wav", "wb") as f:
                     f.write(audio.get_wav_data())
                 print("[jarvis] Debug: Saved unrecognized audio to 'debug_last_audio.wav'")
                 return None
             except sr.RequestError as e:
                 self.emit_log(f"Speech Service Error: {e}")
                 self.log_and_speak("Speech service unreachable. Switching to text input.")
                 return input("[jarvis] Network Speech Error. Enter command: ").strip().lower()

        except Exception as e:
            print(f"[jarvis] Microphone error: {e}")
            return input("[jarvis] Enter command manually: ").strip().lower()

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
                print(f"[jarvis] Primary Topic: {header.get_text().strip()}")
            
            print("[jarvis] Intel retrieval complete.")
            
        except Exception as e:
            self.log_and_speak("Failed to retrieve intel.")
            print(f"[jarvis] Error: {e}")

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
            print(f"[jarvis] Web task protocol failed: {e}")
            self.log_and_speak("There was an error with the web driver.")

    def load_history(self):
        """
        Load conversation history from JSON file.
        """
        if os.path.exists("conversation_history.json"):
            try:
                with open("conversation_history.json", "r") as f:
                    return json.load(f)
            except:
                return []
        return []

    def save_history(self, entry):
        """
        Save a new interaction to the history file.
        """
        history = self.load_history()
        history.append(entry)
        try:
            with open("conversation_history.json", "w") as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            print(f"[jarvis] History save error: {e}")

    def get_full_history(self):
        """
        Return a formatted string of the entire history.
        """
        history = self.load_history()
        if not history:
            return "No history records found."
        
        output = ["--- CONVERSATION HISTORY ---"]
        for item in history:
            ts = item.get("timestamp", "Unknown Time")
            user = item.get("user", "")
            assistant = item.get("assistant", "")
            output.append(f"[{ts}]\nUser: {user}\njarvis: {assistant}\n")
        return "\n".join(output)

    def ask_ai(self, prompt, system_instruction=None, json_mode=False, include_history=False):
        """
        Send a prompt to local Ollama instance and return the AI's response.
        Arg: json_mode (bool) - If True, enforces JSON output from the model.
        Arg: include_history (bool) - If True, appends last 4 conversation turns to context.
        """
        if not system_instruction:
            system_instruction = """
            You are jarvis., a highly advanced AI. 
            Personality: British, sophisticated, slightly dry wit, loyal, and highly efficient. 
            Tone: Professional, calm, and brilliant. Call the user 'Sir'.
            Capabilities: You have full access to hardware metrics, camera, and terminal.
            Constraints: Never call yourself J.A.R.V.I.S. or mention Iron Man. 
            Do NOT output internal thoughts or JSON metadata. Speak ONLY natural dialogue.
            """

        # Prepare messages
        messages = [{"role": "system", "content": system_instruction}]

        # Inject Context (Last 4 interactions) if enabled
        if include_history:
            history = self.load_history()
            recent = history[-4:] # Last 4
            for item in recent:
                if item.get("user"):
                    messages.append({"role": "user", "content": item.get("user")})
                if item.get("assistant"):
                    messages.append({"role": "assistant", "content": item.get("assistant")})

        messages.append({"role": "user", "content": prompt})

        url = "http://localhost:11434/api/chat"
        
        data = {
            "model": self.model,
            "messages": messages,
            "stream": False
        }
        
        if json_mode:
            data["format"] = "json"

        try:
            response = self.session.post(url, json=data, timeout=30)
            response.raise_for_status()
            result = response.json()
            full_response = result['message']['content']
            
            if json_mode:
                return full_response.strip()

            # Final cleanup for the full response to remove any stray JSON blocks
            import re
            full_cleaned = re.sub(r'\{.*?\}', '', full_response, flags=re.DOTALL).strip()
            if not full_cleaned: full_cleaned = full_response
            
            return full_cleaned

        except requests.exceptions.ConnectionError:
            return "I cannot connect to my local neural core."
        except Exception as e:
            print(f"[jarvis] AI Error: {e}")
            return "I encountered a processing error."

    def determine_intent(self, command):
        """
        Analyze the user's intent using a two-stage approach:
        1. Fast Regex (Zero Latency) for trivial commands and common queries.
        2. "Dual-Mode Brain" (LLM) to decide between DIRECT_ACTION and AGENTIC_FLOW.
        """
        # --- STAGE 0: HYPER-FAST CACHE ---
        command_lower = command.lower().strip()
        FAST_CACHE = {
            "battery": {"action": "system_stats"},
            "cpu": {"action": "system_stats"},
            "percentage": {"action": "system_stats"},
            "status": {"action": "system_stats"},
            "screenshot": {"action": "screenshot", "sub_action": "take"},
            "take photo": {"action": "camera", "sub_action": "capture"},
            "search": {"action": "web", "type": "search", "query": command.replace("search", "").strip()},
        }
        for key, val in FAST_CACHE.items():
            if key in command_lower:
                return val

        # --- STAGE 1: FAST REGEX ---
        
        # Volume
        if any(w in command_lower for w in ["volume", "louder", "quieter", "mute", "silent"]):
             if "up" in command_lower or "louder" in command_lower: return {"action": "volume", "type": "up"}
             if "down" in command_lower or "quieter" in command_lower: return {"action": "volume", "type": "down"}
             if "mute" in command_lower or "silent" in command_lower: return {"action": "volume", "type": "mute"}

        # Stop
        if any(w in command_lower for w in ["stop", "cancel", "shh", "wait"]):
             self.stop_speaking()
             return {"action": "chat", "response": "Standing by."}

        # System
        if any(w in command_lower for w in ["shutdown", "quit program", "exit jarvis"]):
             return {"action": "system", "type": "shutdown"}

        # Identity / Chat
        if any(p in command_lower.strip("? .") for p in ["who are you", "what is your name", "hello", "hi jarvis", "are you there", "can you hear me"]):
             prompt = f"Reply to: '{command}'. Confirm you hear me and characterize jarvis."
             return {"action": "ask_ai", "prompt": prompt}

        # Apps (Regex heuristic)
        if command_lower.startswith("open ") or command_lower.startswith("launch "):
             app_name = command_lower.replace("open ", "").replace("launch ", "").strip()
             return {"action": "app", "name": app_name}
             
        # System Health (Zero Hallucination)
        if any(w in command_lower for w in ["battery", "cpu", "percentage", "ram", "temp", "health", "system check", "stats"]):
             return {"action": "system_stats"}

        # Default: Optimized Fast Path
        # Skip the complex "Router" LLM call and go straight to the local AI for general questions.
        # This significantly reduces latency for simple interactions.
        return {"action": "ask_ai", "prompt": command}

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
            
            print(f"[jarvis] {app_name} command sent.")
            
        except Exception as e:
            print(f"[jarvis] Desktop engagement error: {e}")

    def activate_gestures(self):
        self.log_and_speak("Activating holographic interface protocols.")
        try:
            self.gesture_controller.start()
            self.log_and_speak("Gesture control online.")
        except Exception as e:
            print(f"[jarvis] Gesture error: {e}")
            self.log_and_speak("Failed to initialize gesture sensors.")

    def deactivate_gestures(self):
        self.log_and_speak("Deactivating gesture control.")
        try:
            self.gesture_controller.stop()
        except Exception as e:
            print(f"[jarvis] Gesture stop error: {e}")

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
            print(f"[jarvis] Screenshot error: {e}")
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
            print(f"[jarvis] Camera error: {e}")
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
                print(f"[jarvis] Workflow error on {item}: {e}")
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
            print(f"[jarvis] Deletion error: {e}")
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
            self.emit_log(f"Error processing command: {e}")
            self.log_and_speak("I encountered a critical error.")
            return str(e)

    def get_device_info(self):
        """
        Gather OS and System Information for context.
        """
        import platform
        try:
            info = f"OS: {platform.system()} {platform.release()}\n"
            info += f"Distro: {subprocess.check_output('cat /etc/*release | grep PRETTY_NAME', shell=True).decode().strip()}"
        except:
            info = f"OS: {platform.system()} (Unknown Distro)"
        return info

    def agentic_terminal_action(self, goal, max_steps=10):
        """
        Robust Agentic Loop handling commands, GUI, and simple communication.
        """
        self.log_and_speak(f"Agentic Mode Engaged. Goal: {goal}")
        
        history = "" 
        import getpass
        import json
        current_user = getpass.getuser()
        
        for step_i in range(1, max_steps + 1):
             
             # Few-shot example-driven prompt for small models
             system_prompt = f"""
Goal: {goal}
Step: {step_i}

Recent actions:
{history[-300:] if history else "None"}

Valid response types:
1. "gui" - value format "hotkey:key+key", "type:text", or "press:key"
2. "terminal" - value is the shell command to execute
3. "done" - value is "true"

Examples:
To launch Chrome:
{{"thought": "open terminal", "type": "gui", "value": "hotkey:ctrl+alt+t"}}
{{"thought": "type chrome command", "type": "gui", "value": "type:google-chrome"}}

To execute directly (recommended for scripts):
{{"thought": "list files", "type": "terminal", "value": "ls -la"}}

If the previous step failed, try a different approach.
Your turn. Output ONLY JSON for step {step_i}:
             """
             
             # Get AI decision
             response = self.ask_ai("Generate next action", system_instruction=system_prompt, include_history=False, json_mode=True)
             
             try:
                 data = json.loads(response)
                 thought = data.get("thought", "Processing...")
                 action_type = data.get("type", "").lower()
                 action_val = data.get("value", "")
             except Exception as e:
                 self.emit_log(f"JSON Parse Error: {response[:100]}")
                 continue

             self.emit_log(f"Step {step_i}: {thought}")
             
             # Handle Execution
             if action_type == "done":
                 self.log_and_speak("Task complete.")
                 return "Task Completed."

             elif action_type == "gui" and action_val:
                 try:
                     if ":" not in action_val:
                         self.emit_log(f"Invalid GUI value format: {action_val}")
                         continue
                         
                     parts = action_val.split(":", 1)
                     act = parts[0].lower().strip()
                     val = parts[1].strip()
                     
                     if act == "hotkey":
                         keys = val.split("+")
                         self.emit_log(f"Pressing: {' + '.join(keys)}")
                         pyautogui.hotkey(*keys)
                         time.sleep(2.0)
                         history += f"\n[{step_i}] Hotkey: {val}"
                         
                     elif act == "type":
                         self.emit_log(f"Typing: {val[:50]}...")
                         pyautogui.write(val, interval=0.05)
                         time.sleep(0.5)
                         history += f"\n[{step_i}] Typed: {val}"
                         
                     elif act == "press":
                         self.emit_log(f"Pressing key: {val}")
                         pyautogui.press(val)
                         time.sleep(0.5)
                         history += f"\n[{step_i}] Pressed: {val}"
                     else:
                         self.emit_log(f"Unknown GUI action: {act}")
                         
                 except Exception as e:
                     self.emit_log(f"GUI Error: {e}")
                     history += f"\n[{step_i}] Error: {e}"
             
             elif action_type == "terminal" and action_val:
                 if str(action_val).strip().lower() != "none":
                     self.emit_log(f"Executing: {action_val}")
                     output, code = self.execute_visible_command(action_val)
                     history += f"\n[{step_i}] Terminal Output: {output[:100]} (Exit Code: {code})"
                 else:
                     self.emit_log("AI returned null command. Skipping.")
                     history += f"\n[{step_i}] Error: Null command received."

             else:
                 self.emit_log(f"Invalid action type: {action_type}")
                 history += f"\n[{step_i}] Invalid: {thought}"

             time.sleep(1.0)

        self.log_and_speak("Step limit reached.")
        return "Step limit reached."

    def execute_visible_command(self, command, timeout=30):
        """
        Launches command in a visible terminal window and captures output/exit code via log file.
        Returns: (output_str, exit_code_int)
        """
        import shlex
        
        # Use a unique log file per command invocation to prevent overlap
        timestamp = int(time.time() * 1000)
        log_file = os.path.abspath(f"jarvis_term_{timestamp}.log")
        
        # Clear log (create new)
        with open(log_file, 'w') as f:
            f.write("")
            
        sentinel = "jarvis_done"
        
        # Construct the complex wrapper logic
        # 1. Run command, capture stdout/stderr to file and terminal (tee)
        # 2. Capture exit code
        # 3. Write sentinel
        # 4. Keep terminal open (exec bash)
        
        # We need to be careful with escaping.
        # Inner script:
        # {command} 2>&1 | tee {log_file}; echo "EXIT:$?" >> {log_file}; echo "{sentinel}" >> {log_file}; exec bash
        
        inner_script = f"{{ {command} ; }} 2>&1 | tee {log_file}; echo \"EXIT:$?\" >> {log_file}; echo \"{sentinel}\" >> {log_file}; exec bash"
        
        # Launch Terminal
        # Prefer mate-terminal (Parrot) -> gnome-terminal -> x-terminal-emulator
        # We use a unique ID to maybe separate windows if possible, but distinct calls usually pop new windows.
        term_cmd = None
        if shutil.which("mate-terminal"):
            # mate-terminal requires -x bash -c ... or -- bash -c ...
            term_cmd = ["mate-terminal", "--window", "--", "bash", "-c", inner_script]
        elif shutil.which("gnome-terminal"):
            term_cmd = ["gnome-terminal", "--window", "--", "bash", "-c", inner_script]
        else:
            term_cmd = ["x-terminal-emulator", "-e", f"bash -c '{inner_script}'"]
            
        try:
            subprocess.Popen(term_cmd)
        except Exception as e:
            return f"Failed to launch terminal: {e}", 1

        # Poll log file for sentinel
        start_time = time.time()
        final_output = ""
        final_code = 1
        
        while (time.time() - start_time) < timeout:
            try:
                if os.path.exists(log_file):
                    with open(log_file, 'r', errors='replace') as f:
                        content = f.read()
                        
                    if sentinel in content:
                        # Parse
                        parts = content.split(sentinel)
                        raw_log = parts[0].strip()
                        
                        # Find exit code at end
                        # Format: ...\nEXIT:0\n
                        lines = raw_log.split('\n')
                        exit_line = [l for l in lines if l.startswith("EXIT:")]
                        if exit_line:
                            try:
                                final_code = int(exit_line[-1].split(":")[1])
                                # Remove exit line from output display
                                lines.remove(exit_line[-1])
                                final_output = "\n".join(lines)
                            except:
                                final_output = raw_log
                        else:
                            final_output = raw_log
                            
                        if final_output:
                            self.emit_log(f"Terminal Output: {final_output[:100]}...")
                        return final_output, final_code
                        
                time.sleep(0.5)
            except:
                pass
                
        # Timeout
        return "Command timed out or sentinel not found.", 124

    def process_command(self, command, silent=False):
        """
        Process a text command using LLM-based intent analysis.
        """
        self.thread_local.silent = silent
        
        try:
            if not command:
                return None

            self.stop_speaking() # Interrupt previous reply if Sir is speaking again
            intent = self.determine_intent(command)
            action = intent.get("action")
            
            self.emit_log(f"Identified Intent: {intent.get('action')}")
            print(f"[jarvis] Identified Intent: {intent}")

            if action == "agentic":
                goal = intent.get("goal")
                return self.agentic_terminal_action(goal)

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
                    # Use the agentic loop to launch apps (e.g. try different commands)
                    return self.agentic_terminal_action(f"launch {app_name}")

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

            elif action == "history":
                hist_text = self.get_full_history()
                print(f"\n{hist_text}\n")
                self.log_and_speak("History has been logged to the console.")
                return "History displayed."
            
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
                    # The new agentic loop handles retries internally
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
                    # Grounding for character and reliability
                    sys_inst = """
                    You are jarvis. Respond concisely, with sophistication and a dry wit. 
                    Address the user as 'Sir'. Never mention J.A.R.V.I.S or Iron Man.
                    """
                    response = self.ask_ai(prompt, system_instruction=sys_inst, include_history=True)
                    self.log_and_speak(response)
                    return response

            elif action == "system_stats":
                stats = self.get_system_health()
                level = stats.get('battery', 'unknown')
                cpu = stats.get('cpu', 'unknown')
                temp = stats.get('temp', 'stable')
                
                msg = f"Systems are operating within normal parameters, Sir. Battery at {level} percent. CPU load is at {cpu} percent. Thermal readings are {temp} degrees."
                self.log_and_speak(msg)
                return msg

            # Default to Chat
            response_text = intent.get("response", "I am not sure how to respond to that.")
            self.log_and_speak(response_text)
            return response_text

        except Exception as e:
            print(f"[jarvis] Error processing command: {e}")
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
                
                # Log Interaction to History
                if response:
                    entry = {
                        "user": command,
                        "assistant": str(response),
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                    }
                    self.save_history(entry)
                
                # Check for exit condition (based on the processed command)
                if response == "Powering down system. Goodbye, Sir.":
                    break

            except KeyboardInterrupt:
                print("\n[jarvis] Forced shutdown.")
                break
            except Exception as e:
                print(f"[jarvis] Critical error: {e}")

if __name__ == "__main__":
    jarvis = JarvisAssistant()
    jarvis.central_command()
