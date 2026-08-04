# Armenian Voice Assistant — Mic Button

A mic-button voice assistant: speak or type in Armenian, get a text + spoken
reply back in Armenian.

- **Frontend**: `frontend/` — plain HTML/CSS/JS served via a **Vite** dev
  server on `:5178` (proxies `/api/*` to the backend, so no CORS setup
  needed). Mic button prefers the browser's Web Speech Recognition API
  (Chrome/Edge); in Safari/Firefox, where that API doesn't exist, it
  automatically falls back to recording audio and sending it to the backend
  for transcription. A text box covers typed input too. Every reply is shown
  as text *and* spoken aloud.
- **Backend**: `backend/app.py` — FastAPI on `:8008`. Talks to a local
  **Ollama** server for the LLM reply, to Meta's **MMS-TTS** model for
  Armenian speech synthesis, and to a local **Whisper** model (`faster-whisper`)
  for the Safari/Firefox speech-to-text fallback. It also serves `frontend/`
  as static files, so `:8008` alone works too if you don't want to run Vite.

## Why these choices

- **LLM**: routed through Ollama, fixed to `OLLAMA_MODEL` (env var, default
  `qwen2.5:3b`) — no model picker in the UI. Change it with `ollama pull` +
  restarting the backend with a different `OLLAMA_MODEL`. See "Known
  limitation" below for why none of the current options are great.
- **STT (mic → text)**: browser Web Speech API first choice — zero backend
  cost, streams audio to Google's servers for recognition (needs internet,
  behaves the same on Mac and Windows). Only implemented in Chromium browsers
  though, so Safari and Firefox fall back to `MediaRecorder` + a local
  **Whisper** model (`faster-whisper`, `small` size, CPU, Armenian language
  hint) on the backend — slower (few seconds of processing after you stop
  talking) and fully offline once the model is downloaded once.
- **TTS (text → voice)**: backend model `facebook/mms-tts-hyw` (Meta MMS),
  with a fallback to the browser's own `speechSynthesis` if the backend call
  fails for any reason. The backend path runs in Python and sounds identical
  on Mac and Windows. This is the only Western Armenian voice used — no
  Eastern Armenian option exists or is used anywhere in this app.

  **License heads-up**: `facebook/mms-tts-hyw` is **CC-BY-NC-4.0
  (non-commercial only)** — fine for personal/research use, but not for a
  product you'd sell or monetize. I searched HuggingFace for a permissively-
  licensed alternative and didn't find one: the one other Armenian TTS
  checkpoint I found (`davit312/piper-TTS-Armenian`, GPL-2.0) turned out to
  be **Eastern** Armenian (`hy_AM`) despite the better license, so it's not a
  substitute. There's also no free, unrestricted Western Armenian speech
  dataset to train a new one from — HuggingFace/Common Voice's only open
  Armenian speech corpus (`Chillarmo/common_voice_20_armenian`, CC0) is
  Eastern Armenian too. Western Armenian is a genuinely low-resource dialect
  for open datasets. If you outgrow the non-commercial license, the real
  options are: (a) get a commercial license/quote from Meta for MMS, or (b)
  fund/collect a Western Armenian voice dataset (e.g. commission a native
  speaker for a few hours of recorded, transcribed speech) and fine-tune an
  open toolkit like [Piper](https://github.com/rhasspy/piper) (MIT-licensed)
  on it — that's a real data-collection project, not a code change.
  The browser fallback voice is OS-dependent, and neither macOS nor Windows
  ships a native Armenian system voice by default — treat it as a last
  resort, not a reliable Armenian voice.
- The `tencent/Hy-Embodied-VLM-1.0` link isn't used here — that model is a
  robotics vision-language-action model (controls robot arms from camera
  frames), not a text/voice chat model, so it doesn't fit this use case.

## Known limitation: local Armenian LLM quality

The system prompt asks for **Western Armenian** specifically (to match the
TTS voice, see above), but this doesn't fix the underlying reliability
problem — it's not a prompt-wording issue. The same model, same prompt, same
kind of question can come back perfectly clean Armenian one call and
garbled-with-stray-Chinese-characters-and-English-fragments the next. Making
the prompt more elaborate (explicitly naming "classical Mesropian
orthography" etc.) made a weak model's output *worse*, not better — small
models seem to do best with short, plain instructions. Tested against the
models already pulled in your Ollama:

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

To compare another model's Armenian output, `ollama pull` it (e.g.
`gemma2:9b`, `aya-expanse`, `command-r`), set `OLLAMA_MODEL` to its name, and
restart the backend. In practice, small (2–4B) open models are generally
weak at Armenian; if quality matters, plan on either a larger model (7B+) or
a model specifically fine-tuned for Armenian.

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
4. Open **http://localhost:5178** in any modern browser — Chrome/Edge use
   native speech recognition for the mic button, Safari/Firefox use the
   Whisper fallback automatically. Ports were picked to avoid clashing with
   your other local projects (`:8001` BetterTalkNowAI, `:8000/:5173` etc.
   elsewhere).

The first spoken reply (~30–60s) and first mic use in Safari/Firefox
(~10-20s) will be slow while the TTS/Whisper models download and load into
memory; both are cached in RAM after that for the rest of the session, and
on disk (`~/.cache/huggingface`) for future runs.

## Config (env vars, optional)

- `OLLAMA_URL` — default `http://localhost:11434`
- `OLLAMA_MODEL` — default `qwen2.5:3b` (used when the UI doesn't pass a model)
- `TTS_MODEL_ID` — default `facebook/mms-tts-hyw`
- `WHISPER_MODEL_SIZE` — default `small` (Safari/Firefox STT fallback; larger
  = more accurate but slower on CPU)

## API

- `GET /api/health` — Ollama connectivity + available models
- `GET /api/models` — list of pulled Ollama models (debugging only, not used by the UI)
- `POST /api/chat` `{message, model?, history?}` → `{reply, model}` — `model`
  is optional and only useful for scripting/testing; the UI never sends it
- `POST /api/speak` `{text}` → `audio/wav` bytes
- `POST /api/transcribe` (multipart, field `audio`) → `{text}` — Whisper
  fallback used by browsers without Web Speech Recognition
