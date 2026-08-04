import io
import logging
import os
import threading
from typing import List, Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("voice-assistant")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
TTS_MODEL_ID = os.environ.get("TTS_MODEL_ID", "facebook/mms-tts-hyw")  # Meta MMS only ships Western Armenian TTS

SYSTEM_PROMPT = (
    "You are a warm, helpful voice assistant. Always answer in Armenian "
    "(հայերեն, Eastern Armenian, Armenian script), even if the user writes "
    "in English, Russian, or transliterated Armenian, unless they explicitly "
    "ask you to switch language. Keep answers concise and natural, since "
    "they will also be read aloud."
)

app = FastAPI(title="Armenian Voice Assistant")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    model: Optional[str] = None
    history: List[ChatMessage] = []


class SpeakRequest(BaseModel):
    text: str


def fetch_ollama_models():
    r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
    r.raise_for_status()
    return [m["name"] for m in r.json().get("models", [])]


@app.get("/api/health")
def health():
    try:
        models = fetch_ollama_models()
        ollama_ok = True
    except Exception as e:
        log.warning("Ollama unreachable: %s", e)
        models, ollama_ok = [], False
    return {
        "ollama": ollama_ok,
        "models": models,
        "default_model": DEFAULT_MODEL,
        "tts_loaded": _tts_model is not None,
    }


@app.get("/api/models")
def list_models():
    try:
        return {"models": fetch_ollama_models(), "default_model": DEFAULT_MODEL}
    except Exception as e:
        raise HTTPException(502, f"Could not reach Ollama at {OLLAMA_URL}: {e}")


@app.post("/api/chat")
def chat(req: ChatRequest):
    model = req.model or DEFAULT_MODEL
    text = req.message.strip()
    if not text:
        raise HTTPException(400, "message is required")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in req.history[-12:]:
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": text})

    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={"model": model, "messages": messages, "stream": False},
            timeout=300,
        )
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise HTTPException(502, f"Ollama request failed (is 'ollama serve' running, and is '{model}' pulled?): {e}")

    reply = r.json().get("message", {}).get("content", "").strip()
    if not reply:
        raise HTTPException(502, "Model returned an empty response")
    return {"reply": reply, "model": model}


# ---- Armenian text-to-speech (Meta MMS-TTS), lazy-loaded on first use ----
_tts_model = None
_tts_tokenizer = None
_tts_lock = threading.Lock()


def _load_tts():
    global _tts_model, _tts_tokenizer
    if _tts_model is not None:
        return _tts_model, _tts_tokenizer
    with _tts_lock:
        if _tts_model is None:
            log.info("Loading Armenian TTS model %s ...", TTS_MODEL_ID)
            from transformers import AutoTokenizer, VitsModel

            tokenizer = AutoTokenizer.from_pretrained(TTS_MODEL_ID)
            model = VitsModel.from_pretrained(TTS_MODEL_ID)
            model.eval()
            _tts_tokenizer = tokenizer
            _tts_model = model
            log.info("Armenian TTS model ready.")
    return _tts_model, _tts_tokenizer


@app.on_event("startup")
def warm_up_tts():
    # Load the TTS model in the background so the first real request isn't slow.
    threading.Thread(target=_load_tts, daemon=True).start()


@app.post("/api/speak")
def speak(req: SpeakRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "text is required")

    try:
        model, tokenizer = _load_tts()
        import numpy as np
        import scipy.io.wavfile as wavfile
        import torch

        inputs = tokenizer(text, return_tensors="pt")
        with torch.no_grad():
            waveform = model(**inputs).waveform

        audio = waveform.squeeze().cpu().numpy().astype(np.float32)
        buf = io.BytesIO()
        wavfile.write(buf, rate=model.config.sampling_rate, data=audio)
        buf.seek(0)
        return StreamingResponse(buf, media_type="audio/wav")
    except Exception as e:
        log.exception("TTS synthesis failed")
        raise HTTPException(500, f"TTS synthesis failed: {e}")


# ---- Serve the frontend ----
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
