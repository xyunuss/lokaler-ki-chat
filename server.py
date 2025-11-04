
from flask import Flask, request, Response, stream_with_context, jsonify
from flask_cors import CORS
import requests, subprocess, json, os
from PyPDF2 import PdfReader
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.route("/api/models", methods=["GET"])
def list_models():
    """Liest die lokal installierten Ollama-Modelle aus"""
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
        lines = result.stdout.strip().split("\n")[1:]
        models = [line.split()[0] for line in lines if line.strip()]
        return jsonify({"models": models})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat", methods=["POST"])
def chat():
    """Chat mit Verlauf (Kontext bleibt erhalten, solange der Client offen ist)"""
    data = request.get_json()
    model = data.get("model", "llama3")
    history = data.get("history", [])

    def generate():
        try:
            # Verwende Ollamas /api/chat, damit der Verlauf berücksichtigt wird
            with requests.post(
                "http://localhost:11434/api/chat",
                json={"model": model, "messages": history, "stream": True},
                stream=True,
                timeout=300
            ) as r:
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        data_line = json.loads(line.decode("utf-8"))
                        # Ollama liefert Chat-Objekte im Feld "message"
                        if "message" in data_line and "content" in data_line["message"]:
                            yield data_line["message"]["content"]
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            yield f"\n[Fehler: {str(e)}]"

    return Response(stream_with_context(generate()), mimetype='text/plain')


@app.route("/api/chat-file", methods=["POST"])
def chat_file():
    """Verarbeitet Datei-Uploads und kombiniert sie mit Prompt + Verlauf"""
    model = request.form.get("model", "llama3")
    prompt = request.form.get("prompt", "")
    file = request.files.get("file")
    history_json = request.form.get("history", "[]")
    history = json.loads(history_json)

    if not file:
        return jsonify({"error": "Keine Datei hochgeladen"}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    # Text aus Datei extrahieren
    text_content = ""
    if filename.lower().endswith(".pdf"):
        reader = PdfReader(filepath)
        for page in reader.pages:
            text_content += page.extract_text() + "\n"
    else:
        text_content = file.read().decode("utf-8", errors="ignore")

    # Kombinierter Benutzer-Input
    user_msg = f"{prompt}\n\n---\nHier ist der Inhalt der Datei '{filename}':\n{text_content[:15000]}"
    history.append({"role": "user", "content": user_msg})

    def generate():
        try:
            with requests.post(
                "http://localhost:11434/api/chat",
                json={"model": model, "messages": history, "stream": True},
                stream=True,
                timeout=300
            ) as r:
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        data_line = json.loads(line.decode("utf-8"))
                        if "message" in data_line and "content" in data_line["message"]:
                            yield data_line["message"]["content"]
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            yield f"\n[Fehler beim Generieren: {str(e)}]"

    return Response(stream_with_context(generate()), mimetype="text/plain")


if __name__ == "__main__":
    app.run(port=5000)


