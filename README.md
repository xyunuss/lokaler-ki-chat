# 💬 Lokaler KI-Chat (Flask + Ollama)

Ein vollständig lokaler KI-Chatbot mit Datei-Upload, Markdown-Rendering, Theme-Umschaltung und Chatverlauf.  
Er nutzt **Ollama** als Backend, um LLMs lokal laufen zu lassen – **ohne API-Keys oder Cloud**.

---

## 🚀 Funktionen
- 🧠 Chat mit lokalem KI-Modell (Ollama)
- 📄 Datei-Upload (PDF, TXT, DOCX) → automatische Analyse
- 💬 Live-Streaming der Antworten
- 🌓 Dark-/Lightmode + Themespeicherung
- 🗂️ Chat-Verlauf (Client-Session)
- 🧱 100 % lokal

---

## 🛠️ Tech Stack
| Bereich | Technologie |
|---|---|
| Backend | Python, Flask, PyPDF2, Requests |
| Frontend | HTML, Vanilla JS, CSS, marked.js |
| KI-Engine | Ollama (z. B. Llama 3, Mistral) |

---

## ⚙️ Installation
1. **Ollama installieren** → https://ollama.com/download  
2. **Modell laden** (Beispiel):
   ```bash
   ollama pull llama3
