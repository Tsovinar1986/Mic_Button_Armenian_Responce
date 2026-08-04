# Armenian Voice Assistant — Mic Button

A mic-button voice assistant: speak or type in Armenian, get a text + spoken
reply back in Armenian.

- **Frontend**: `frontend/` — plain HTML/CSS/JS served via a **Vite** dev
  server on `:5178` (proxies `/api/*` to the backend, so no CORS setup
  needed). Mic button uses the browser's Web Speech Recognition API
  (Chromium-only) for voice input; a text box covers typed input too. Every
  reply is shown as text *and* spoken aloud.
- **Backend**: `backend/app.py` — FastAPI on `:8008`. Talks to a local
  **Ollama** server for the LLM reply, and to Meta's **MMS-TTS** model for
  Armenian speech synthesis. It also serves `frontend/` as static files, so
  `:8008` alone works too if you don't want to run Vite.

## Why these choices

- **LLM**: routed through Ollama so you can swap models freely — the model
  picker in the top bar lists whatever you've `ollama pull`ed and lets you
  compare Armenian quality live. See "Known limitation" below.
- **STT (mic → text)**: browser Web Speech API, per your choice — zero backend
  cost. Only works in Chromium browsers (Chrome, Edge) on either Mac or
  Windows — Safari support is spotty and Firefox has none. It streams audio
  to Google's servers for recognition rather than using an OS speech pack, so
  it needs internet access but behaves the same on Mac and Windows.
- **TTS (text → voice)**: backend model `facebook/mms-tts-hyw` (Meta MMS),
  with a fallback to the browser's own `speechSynthesis` if the backend call
  fails for any reason. The backend path runs in Python and sounds identical
  on Mac and Windows. Note: MMS only ships a **Western Armenian** voice —
  there is no Eastern Armenian TTS model in that family, so the accent will
  sound Western-Armenian rather than the Yerevan-standard dialect. The browser
  fallback voice is OS-dependent, and neither macOS nor Windows ships a native
  Armenian system voice by default — so treat it as a last resort, not a
  reliable Armenian voice.
- The `tencent/Hy-Embodied-VLM-1.0` link isn't used here — that model is a
  robotics vision-language-action model (controls robot arms from camera
  frames), not a text/voice chat model, so it doesn't fit this use case.

## Known limitation: local Armenian LLM quality

Tested against the models already pulled in your Ollama:

- `qwen2.5:3b` → produces broken/garbled Armenian (mixed-in stray
  characters), unusable as-is.
- `gemma2:2b` → real Armenian words but grammatically broken word-salad, not
  a coherent sentence — worse than qwen2.5:3b, not usable either.
- `qwen2.5:7b` → best of the four, opens with a mostly-coherent Armenian
  sentence, but still degrades mid-reply into garbled characters and then
  code-switches into Greek script entirely unprompted. Also much slower on
  CPU (~2 minutes per reply). Better, but still not reliable.
- `armenia-lawyer-router` / `-v2` → per your own `Armenian_Chat_Status_and_TODO.md`
  notes in the sibling legal project, these degrade into gibberish after the
  first clause — same underlying issue, not fixed by this project.

The UI's model dropdown exists specifically so you can `ollama pull` other
candidates (e.g. `gemma2:2b`, `gemma2:9b`, `aya-expanse`, `command-r`) and
compare their Armenian output live without touching code. In practice,
small (2–4B) open models are generally weak at Armenian; if quality matters,
plan on either a larger model (7B+) or a model specifically fine-tuned for
Armenian.

## Setup

Backend Python deps go in `./venv` (isolated virtualenv, not your global
Python — see `backend/requirements.txt`). Frontend deps go in
`frontend/node_modules` (just Vite).

1. First time only:
   ```bash
   python3 -m venv venv
   ./venv/bin/pip install -r backend/requirements.txt
   cd frontend && npm install && cd ..
   ```
2. Make sure Ollama is running and has at least one model pulled:
   ```bash
   ollama serve &          # if not already running
   ollama pull qwen2.5:3b  # or gemma2:2b, qwen2.5:7b, etc.
   ```
3. Start everything (backend on `:8008` + Vite on `:5178`):
   ```bash
   ./start.sh
   ```
4. Open **http://localhost:5178** in Chrome or Edge (needed for the mic
   button — Web Speech Recognition isn't supported in Safari/Firefox). Ports
   were picked to avoid clashing with your other local projects
   (`:8001` BetterTalkNowAI, `:8000/:5173` etc. elsewhere).

The first spoken reply will take ~30–60s while the TTS model downloads and
loads into memory; it's cached in RAM after that (fast for the rest of the
session), and cached on disk (`~/.cache/huggingface`) for future runs.

## Config (env vars, optional)

- `OLLAMA_URL` — default `http://localhost:11434`
- `OLLAMA_MODEL` — default `qwen2.5:3b` (used when the UI doesn't pass a model)
- `TTS_MODEL_ID` — default `facebook/mms-tts-hyw`

## API

- `GET /api/health` — Ollama connectivity + available models
- `GET /api/models` — list of pulled Ollama models
- `POST /api/chat` `{message, model?, history?}` → `{reply, model}`
- `POST /api/speak` `{text}` → `audio/wav` bytes
