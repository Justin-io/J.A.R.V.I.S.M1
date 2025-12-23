# J.A.R.V.I.S. Desktop Assistant

![Status](https://img.shields.io/badge/Status-Online-cyan)
![Platform](https://img.shields.io/badge/Platform-Linux-orange)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)

**J.A.R.V.I.S.** (Just A Rather Very Intelligent System) is a highly advanced, voice-activated desktop assistant designed for Linux systems. Combining local AI processing with real-time web visualizations, it offers a cinematic "Iron Man" style interface while providing powerful system control, automation, and intelligent conversation capabilities.

---

## 🚀 Features

### 🧠 **Hybrid AI Core**
- **Local Intelligence**: Runs efficiently on `Ollama` (using models like `llama3.2`) for privacy and speed.
- **Agentic Workflow**: Capable of executing complex, multi-step terminal tasks with self-correction (e.g., "Clean up all png files on my desktop").
- **Context Awareness**: Remembers recent actions and adapts to user context.

### 🖥️ **Futuristic Interface**
- **Real-Time Dashboard**: A stunning, responsive WebUI built with **Flask** and **Socket.IO**.
- **Neural Visualization**: Interactive 3D brain visualization using **Three.js** that reacts to system status.
- **Live Telemetry**: Monitors and displays CPU, RAM, Disk, Temperature, and Battery levels in real-time.
- **Terminal Feed**: Watch the AI's "thought process" and command execution logs live on screen.

### 🛠️ **System Control & Automation**
- **Voice Commands**: Wake up JARVIS with natural speech.
- **App Management**: Launch applications, close windows, and control volume/brightness.
- **File Operations**: Create folders, organize files, and manage directories via voice.
- **Web Automation**: Search Google, scrape websites for "intel", and open URLs.
- **Visual Intelligence**: Take screenshots or webcam photos and send them directly to **Telegram**.
- **Gesture Control**: (Experimental) Hand tracking for touch-free interface interaction.

---

## 🛠️ Technology Stack

- **Backend**: Python 3, Flask, Socket.IO
- **Frontend**: HTML5, TailwindCSS, Vanilla JS, Three.js
- **AI/ML**: Ollama (LLM), SpeechRecognition (STT), Edge-TTS (Text-to-Speech), TensorFlow Lite (Gestures)
- **System**: PyAutoGUI, Psutil, OpenCV, Subprocess

---

## 📋 Prerequisites

- **OS**: Linux (Optimized for Parrot OS / Debian-based distributions).
- **Python**: Version 3.10 or higher.
- **Hardware**: Microphone and Webcam (optional for gestures/photos).
- **AI Backend**: [Ollama](https://ollama.ai/) installed and running locally.

---

## ⚡ Installation

1.  **Clone the Repository**
    ```bash
    git clone https://github.com/your-username/jarvis_project.git
    cd jarvis_project
    ```

2.  **Set Up Virtual Environment**
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```
    *(Note: You may need system libraries like `portaudio19-dev` and `python3-tk`)*

4.  **Configure Environment**
    Create a `.env` file in the root directory:
    ```ini
    TELEGRAM_BOT_TOKEN=your_token_here
    TELEGRAM_CHAT_ID=your_chat_id_here
    OPENROUTER_API_KEY=optional_fallback_key
    ```

5.  **Start Ollama Service**
    Ensure your local LLM is running:
    ```bash
    ollama serve
    ```
    *(Pull the model user helper: `ollama pull llama3.2`)*

---

## 🕹️ Usage

**One-Click Start:**
Run the included startup script to launch the backend and open the web interface automatically:

```bash
./run_jarvis.sh
```

**Manual Start:**
```bash
source .venv/bin/activate
python app.py
```

Access the interface at `http://localhost:5200` (or the port specified in the logs).

---

## 🗣️ Command Examples

| Category | Voice Command Examples |
| :--- | :--- |
| **System** | "Shutdown system", "Set brightness to 50%", "Mute volume" |
| **Apps** | "Open Firefox", "Launch Visual Studio Code" |
| **Web** | "Search Google for latest tech news", "Get intel from wikipedia.org" |
| **Files** | "Delete all screenshots", "List files in documents", "Create a folder named Project X" |
| **Visuals** | "Take a screenshot", "Send this to Telegram", "Take a selfie" |
| **Chat** | "Who are you?", "Write a python script to calculate pi" |

---

## 📂 Project Structure

```
jarvis_project/
├── app.py                  # Flask Web Server entry point
├── jarvis_assistant.py     # Main AI Logic & Voice Processing
├── gesture_control.py      # Hand Gesture Recognition module
├── telegram_interface.py   # Telegram Bot polling handler
├── templates/
│   └── index.html          # Main Web Interface (dashboard)
├── static/
│   └── js/
│       └── script.js       # Frontend logic (Socket.IO, Three.js)
├── .env                    # Secrets and Config
└── run_jarvis.sh           # Launcher script
```

---

## 🛡️ License

This project is licensed under the MIT License - see the LICENSE file for details.

---

<p align="center">
  <i>"I am always here to serve you, Sir."</i>
</p>
