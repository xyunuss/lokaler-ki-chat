# 💬 Lokaler KI-Chat (Flask + Ollama)

Ein vollständig **lokaler KI-Chatbot**, der **über die eigene Grafikkarte (GPU)** läuft – kein API-Key, keine Cloud.  
Er kombiniert eine minimalistische Weboberfläche mit **Ollama** als Backend, um große Sprachmodelle wie **LLaMA 3** oder **Mistral** direkt **offline auf dem eigenen Rechner** auszuführen.

---
## 🖥️ Demo

**Darkmode**

![Screenshot der Chat-UI](assets/screenshot_ui.png)

---

**Lightmode + Modellauswahl**

![Screenshot der Chat-UI (Whitemode)](assets/screenshot_ui_whitemode.png)

---

## 🚀 Funktionen

-  **Chat mit lokalem KI-Modell (Ollama)**
-  **Läuft vollständig auf der eigenen GPU / CPU**  
  → keine Internetverbindung oder Cloud-Abhängigkeit
-  **PDF Datei-Upload** mit automatischer Textextraktion  
-  **Echtzeit-Streaming** der Antworten (Zeichenweise wie bei ChatGPT)  
-  **Dark-/Lightmode** mit Themespeicherung  
-  **100 % lokal & datensicher**
-  **Markdown-Unterstützung** (Codeblöcke, Listen, Formatierungen)

---

## 🛠️ Tech Stack

| Bereich | Technologien |
|----------|---------------|
| **Frontend** | HTML, CSS, Vanilla JS, marked.js, Material Icons |
| **Backend** | Python, Flask, Flask-CORS, Requests, PyPDF2 |
| **KI-Engine** | Ollama (lokal auf GPU/CPU) – z. B. LLaMA 3, deepseek-coder, gpt-oss |
---

## ⚙️ Installation & Setup

1. **Ollama installieren** → https://ollama.com/download  

2. **Modell laden** (Beispiel):
   ```bash
   ollama run gpt-oss:20b

Bibliothek für weitere Modelle: https://ollama.com/library

3. **Projekt starten**
   ```bash
    # Repository klonen
    git clone https://github.com/xyunuss/local-ai-chat

    # Abhängigkeiten
    pip install flask flask-cors requests PyPDF2

    # Backend starten
    python server.py

    # Benutzen
    index.html im Browser öffnen

