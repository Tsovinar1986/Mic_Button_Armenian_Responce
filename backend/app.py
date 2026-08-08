import io
import logging
import os
import tempfile
import threading
from contextlib import asynccontextmanager
from typing import List, Optional

import requests
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("voice-assistant")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
TTS_MODEL_ID = os.environ.get("TTS_MODEL_ID", "facebook/mms-tts-hyw")  # Meta MMS only ships Western Armenian TTS
WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "small")  # STT fallback for browsers without Web Speech API

# qwen2.5:7b (DEFAULT_MODEL) is the least-bad option for Armenian but, tested
# live, ignores the "reply in the input language" instruction for Russian/
# English input and just answers in broken Armenian anyway. qwen2.5:3b tested
# reliably coherent for both Russian and English (worse for Armenian, which
# is why it isn't DEFAULT_MODEL) - so route by detected input language
# instead of trusting one fixed model to do all three.
LANGUAGE_MODELS = {
    "hy": DEFAULT_MODEL,
    "ru": os.environ.get("OLLAMA_MODEL_RU", "qwen2.5:3b"),
    "en": os.environ.get("OLLAMA_MODEL_EN", "qwen2.5:3b"),
}

SYSTEM_PROMPT = (
    "You are a warm, helpful voice assistant. Always answer in the same "
    "language the user just wrote in: Armenian (հայերեն, Armenian script) "
    "for Armenian input, Russian (русский, Cyrillic script) for Russian "
    "input, or English for English input. If you can't tell, default to "
    "Armenian. Don't mix languages or scripts within a reply, and don't "
    "switch language unless the user does. Keep answers short and natural."
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the TTS/STT models in the background so the first real request
    # isn't slow. _load_tts/_load_stt are defined further down, but that's
    # fine - this only runs at startup, well after the whole module (and
    # both functions) have finished being defined.
    threading.Thread(target=_load_tts, daemon=True).start()
    threading.Thread(target=_load_stt, daemon=True).start()
    yield


app = FastAPI(title="Voice Assistant", lifespan=lifespan)
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
        "stt_loaded": _stt_model is not None,
    }


@app.get("/api/models")
def list_models():
    try:
        return {"models": fetch_ollama_models(), "default_model": DEFAULT_MODEL}
    except Exception as e:
        raise HTTPException(502, f"Could not reach Ollama at {OLLAMA_URL}: {e}")


def detect_language(text: str) -> str:
    """Guess which of the three supported languages a message is written
    in, from character script alone. Used to pick which script the reply
    is expected to be in (see script_ratio)."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "hy"
    armenian = sum(1 for c in letters if "԰" <= c <= "֏")
    cyrillic = sum(1 for c in letters if "Ѐ" <= c <= "ӿ")
    latin = sum(1 for c in letters if c.isascii())
    counts = {"hy": armenian, "ru": cyrillic, "en": latin}
    return max(counts, key=counts.get)


SCRIPT_RANGES = {
    "hy": ("԰", "֏"),
    "ru": ("Ѐ", "ӿ"),
    "en": None,  # checked via str.isascii() instead of a unicode range
}


def script_ratio(text: str, lang: str) -> float:
    """Fraction of alphabetic characters that are actually in the script
    expected for `lang`. Used to detect the garbled/mixed-script output the
    local models sometimes produce (stray Latin/Cyrillic/CJK/Greek/Armenian
    characters mixed into a reply that should be a single script)."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    if lang == "en":
        matching = sum(1 for c in letters if c.isascii())
    else:
        lo, hi = SCRIPT_RANGES[lang]
        matching = sum(1 for c in letters if lo <= c <= hi)
    return matching / len(letters)


SCRIPT_RATIO_THRESHOLD = 0.85
MAX_CHAT_ATTEMPTS = 3


@app.post("/api/chat")
def chat(req: ChatRequest):
    text = req.message.strip()
    if not text:
        raise HTTPException(400, "message is required")

    lang = detect_language(text)
    # The UI never sends `model` (see README), so in practice this always
    # routes by detected language; an explicit `model` (scripting/testing)
    # still overrides it.
    model = req.model or LANGUAGE_MODELS[lang]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in req.history[-12:]:
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": text})

    best_reply = ""
    best_ratio = -1.0
    for attempt in range(MAX_CHAT_ATTEMPTS):
        try:
            r = requests.post(
                f"{OLLAMA_URL}/api/chat",
                json={"model": model, "messages": messages, "stream": False},
                timeout=300,
            )
            r.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise HTTPException(
                502, f"Ollama request failed (is 'ollama serve' running, and is '{model}' pulled?): {e}"
            )

        candidate = r.json().get("message", {}).get("content", "").strip()
        ratio = script_ratio(candidate, lang)
        if ratio > best_ratio:
            best_reply, best_ratio = candidate, ratio
        if ratio >= SCRIPT_RATIO_THRESHOLD:
            break
        log.warning(
            "Chat reply %d/%d looked garbled for detected language %r (script_ratio=%.2f), retrying: %r",
            attempt + 1,
            MAX_CHAT_ATTEMPTS,
            lang,
            ratio,
            candidate[:80],
        )

    reply = best_reply
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


# ---- Speech-to-text (faster-whisper), for browsers without Web Speech API ----
_stt_model = None
_stt_lock = threading.Lock()


def _load_stt():
    global _stt_model
    if _stt_model is not None:
        return _stt_model
    with _stt_lock:
        if _stt_model is None:
            log.info("Loading Whisper STT model (%s) ...", WHISPER_MODEL_SIZE)
            from faster_whisper import WhisperModel

            _stt_model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
            log.info("Whisper STT model ready.")
    return _stt_model


@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    data = await audio.read()
    if not data:
        raise HTTPException(400, "empty audio upload")

    suffix = os.path.splitext(audio.filename or "")[1] or ".webm"
    try:
        model = _load_stt()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
            tmp.write(data)
            tmp.flush()
            # No `language=` pin: Whisper auto-detects Armenian/Russian/
            # English (or anything else) from the audio itself. Forcing
            # language="hy" here used to make it force-decode every
            # recording as Armenian regardless of what was actually
            # spoken - Russian speech came out as garbled Armenian-ish
            # text, which then correctly-but-wrongly got an Armenian reply
            # since the (already corrupted) transcript looked Armenian.
            segments, info = model.transcribe(tmp.name, vad_filter=True)
            text = " ".join(seg.text.strip() for seg in segments).strip()
            log.info("Transcribed audio as language=%s (p=%.2f): %r", info.language, info.language_probability, text[:80])
        return {"text": text}
    except Exception as e:
        log.exception("Transcription failed")
        raise HTTPException(500, f"Transcription failed: {e}")


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


if __name__ == "__main__":
    # Lets `python3 app.py` work directly (no --reload here; use
    # `uvicorn backend.app:app --reload`, or ../start.sh, for that).
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8191)))
