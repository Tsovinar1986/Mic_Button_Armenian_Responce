import io
import logging
import os
import tempfile
import threading
from contextlib import asynccontextmanager
from typing import List, Optional

import requests
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("voice-assistant")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
TTS_MODEL_ID = os.environ.get("TTS_MODEL_ID", "facebook/mms-tts-hyw")  # Meta MMS only ships Western Armenian TTS
WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "medium")  # STT fallback for browsers without Web Speech API
# "small" tested live and hallucinated short Armenian phrases into
# nonsense words entirely (e.g. spoken "խաչապուրի" came back as
# "խաչապատ...ուտուստել", not real Armenian) even with the correct
# language pinned - Armenian is too low-resource for "small" to be
# reliable. "medium" is slower and heavier but much more accurate;
# set WHISPER_MODEL_SIZE=small back if you need the speed and don't
# care about Armenian accuracy.

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
LANGUAGE_NAMES = {"hy": "Armenian", "ru": "Russian", "en": "English"}

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
    threading.Thread(target=_load_stt, args=("hy",), daemon=True).start()
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
        "stt_loaded": "default" in _stt_models,
        "stt_armenian_loaded": "hy" in _stt_models,
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


# Scripts that should never legitimately appear in an Armenian/Russian/
# English reply at all - unlike SCRIPT_RANGES above (which the overall
# reply is expected to match), even a couple of stray characters from one
# of these blocks means the model code-switched mid-reply (observed live:
# qwen2.5:7b tailing off into Chinese or Greek script). A handful of
# contaminating characters in an otherwise-long, otherwise-correct reply
# isn't enough to drag script_ratio's overall average below its threshold,
# so that check alone missed this - this one checks for *any* presence,
# not proportion.
DISALLOWED_SCRIPT_RANGES = [
    ("一", "鿿"),  # CJK Unified Ideographs
    ("぀", "ヿ"),  # Hiragana/Katakana
    ("가", "힣"),  # Hangul
    ("Ͱ", "Ͽ"),  # Greek and Coptic
]


def has_stray_foreign_script(text: str, lang: str) -> bool:
    if any(lo <= c <= hi for c in text for lo, hi in DISALLOWED_SCRIPT_RANGES):
        return True
    # Latin is the *expected* script for English replies, but a stray Latin
    # word/fragment mixed into an Armenian or Russian reply (observed live:
    # qwen2.5:7b producing tokens like "քենդalled") is exactly
    # the same kind of contamination as a stray CJK/Greek character - so
    # treat it the same way when the reply isn't supposed to be English.
    if lang != "en":
        return any(c.isascii() and c.isalpha() for c in text)
    return False


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
    best_clean_reply = ""
    best_clean_ratio = -1.0
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
        clean = not has_stray_foreign_script(candidate, lang)
        if ratio > best_ratio:
            best_reply, best_ratio = candidate, ratio
        if clean and ratio > best_clean_ratio:
            best_clean_reply, best_clean_ratio = candidate, ratio
        if clean and ratio >= SCRIPT_RATIO_THRESHOLD:
            break
        log.warning(
            "Chat reply %d/%d looked garbled for detected language %r (script_ratio=%.2f, clean=%s), retrying: %r",
            attempt + 1,
            MAX_CHAT_ATTEMPTS,
            lang,
            ratio,
            clean,
            candidate[:80],
        )

    # Prefer a reply with no stray foreign-script contamination at all,
    # even if its script_ratio is lower than the best contaminated one -
    # a purely-correct-script reply beats a mostly-correct one with a
    # code-switched tail. Only fall back to the contaminated best if every
    # attempt had stray characters.
    reply = best_clean_reply or best_reply
    if not reply:
        raise HTTPException(502, "Model returned an empty response")

    # None of the MAX_CHAT_ATTEMPTS tries produced an acceptable reply - seen
    # live with an English "tell me about Yerevan's gardens" prompt, where
    # qwen2.5:3b answered in Armenian on all 3 attempts (ratios 0.15, 0.00,
    # 0.17) because the *topic* was Armenia-related, overriding the "reply
    # in the input language" instruction entirely. Open-ended generation
    # already failed 3 times, so instead of a 4th identical attempt, ask the
    # model to do a much narrower, easier task: translate its own
    # already-written answer into the right language, rather than write a
    # fresh one.
    if best_clean_ratio < SCRIPT_RATIO_THRESHOLD:
        try:
            r = requests.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                f"Translate the following text into {LANGUAGE_NAMES[lang]}. "
                                f"Respond with ONLY the raw translated text itself - no preamble, "
                                f"no \"here is the translation\", no explanation of what you're "
                                f"doing, just the translation:\n\n{reply}"
                            ),
                        }
                    ],
                    "stream": False,
                },
                timeout=300,
            )
            r.raise_for_status()
            candidate = r.json().get("message", {}).get("content", "").strip()
            ratio = script_ratio(candidate, lang)
            clean = not has_stray_foreign_script(candidate, lang)
            log.info(
                "Chat reply needed a translation-correction pass for language %r (script_ratio=%.2f, clean=%s)",
                lang,
                ratio,
                clean,
            )
            if candidate and clean and ratio > best_clean_ratio:
                reply = candidate
        except requests.exceptions.RequestException as e:
            log.warning("Translation-correction pass failed, keeping original reply: %s", e)

    # What script the *final* reply actually ended up in - not necessarily
    # `lang` (the detected input language), since the model can still miss
    # even after the correction pass above. The frontend uses this to pick
    # which voice to speak the reply with in voice mode, so playback always
    # matches what's actually on screen instead of assuming it matches the
    # input language.
    reply_lang = detect_language(reply)

    return {"reply": reply, "model": model, "reply_lang": reply_lang}


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
# WHISPER_MODEL_SIZE (generic, multilingual) handles Russian/English fine.
# For Armenian specifically, a dedicated fine-tuned model
# (Chillarmo/whisper-large-v3-turbo-armenian, converted to CTranslate2 - see
# README) is far more accurate than the generic model, which was never
# trained on much Armenian and hallucinates short/ambiguous phrases into
# nonsense words. So two models are loaded and picked per detected/selected
# language rather than one model for everything.
WHISPER_ARMENIAN_CT2_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whisper_armenian_ct2")

_stt_models = {}
_stt_lock = threading.Lock()


def _load_stt(lang: Optional[str] = None):
    key = "hy" if lang == "hy" and os.path.isdir(WHISPER_ARMENIAN_CT2_DIR) else "default"
    if key in _stt_models:
        return _stt_models[key]
    with _stt_lock:
        if key not in _stt_models:
            from faster_whisper import WhisperModel

            if key == "hy":
                log.info("Loading fine-tuned Armenian Whisper model (%s) ...", WHISPER_ARMENIAN_CT2_DIR)
                _stt_models[key] = WhisperModel(WHISPER_ARMENIAN_CT2_DIR, device="cpu", compute_type="int8")
            else:
                log.info("Loading Whisper STT model (%s) ...", WHISPER_MODEL_SIZE)
                _stt_models[key] = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
            log.info("Whisper STT model (%s) ready.", key)
    return _stt_models[key]


WHISPER_LANGUAGES = {"hy", "ru", "en"}


@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...), language: Optional[str] = Form(None)):
    data = await audio.read()
    if not data:
        raise HTTPException(400, "empty audio upload")

    # `language` is the language-switcher button currently active in the UI
    # (see frontend/app.js setLanguage) - Whisper's own language-ID step is
    # unreliable for short/ambiguous Armenian audio (Armenian is low-
    # resource for Whisper, unlike Russian/English), so a plain auto-detect
    # would sometimes misidentify Armenian speech before transcription even
    # starts and garble the result. Pinning to the UI's selected language
    # fixes that for Armenian while still letting Russian/English work
    # (both transcribe cleanly either pinned or auto-detected). Falls back
    # to auto-detect only if the frontend didn't send a recognized language.
    whisper_lang = language if language in WHISPER_LANGUAGES else None

    suffix = os.path.splitext(audio.filename or "")[1] or ".webm"
    try:
        model = _load_stt(whisper_lang)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
            tmp.write(data)
            tmp.flush()
            segments, info = model.transcribe(tmp.name, language=whisper_lang, vad_filter=True)
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
