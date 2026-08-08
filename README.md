# Armenian Voice Assistant — Mic Button

A mic-button voice assistant: speak or type in Armenian, Russian, or
English, and get a **text-only** reply back in whichever of those three
languages you used. Voice *output* is intentionally not wired up in this
app anymore — see "Audio output" below.

- **Frontend**: `frontend/` — plain HTML/CSS/JS served via a **Vite** dev
  server on `:5178` (proxies `/api/*` to the backend, so no CORS setup
  needed). Mic button prefers the browser's Web Speech Recognition API
  (Chrome/Edge); in Safari/Firefox, where that API doesn't exist, it
  automatically falls back to recording audio and sending it to the backend
  for transcription. A text box covers typed input too. Replies are
  text-only — no audio is played back in the browser.
- **Backend**: `backend/app.py` — FastAPI on `:8191`. Talks to a local
  **Ollama** server for the LLM reply and to local **Whisper** models
  (`faster-whisper`) for the Safari/Firefox speech-to-text fallback. It also
  serves `frontend/` as static files, so `:8191` alone works too if you
  don't want to run Vite.

## How it works

1. You speak (mic button) or type a message in the topbar's `ՀԱՅ`/`РУС`/`ENG`
   language, or just type — the app doesn't require picking a language to
   type in, only to disambiguate voice input (see step 2).
2. **Speech → text**, only if you used the mic:
   - Chrome/Edge: the browser's own Web Speech API transcribes it, told
     which language to expect via the topbar buttons.
   - Safari/Firefox: the recording is sent to `POST /api/transcribe`, which
     runs it through a local Whisper model — the Armenian-fine-tuned one if
     `ՀԱՅ` is selected, the generic multilingual one otherwise (see "Models
     used" below).
3. **Text → reply**: `POST /api/chat` looks at the message's script to guess
   which of the three languages it's in (`detect_language`), routes it to
   whichever Ollama model is best for that language (`LANGUAGE_MODELS`), and
   checks the reply for script contamination (stray Chinese/Greek/Latin
   characters the local models sometimes produce), retrying up to 3 times if
   the first attempt looks garbled.
4. The reply is added to the chat as plain text. Nothing is ever spoken back
   — see "Audio output" below for why.

## Models used

| Model | Used for | Why this one |
|---|---|---|
| `qwen2.5:7b` (Ollama) | Chat replies when the message is Armenian | Best Armenian output of the models tested so far — still imperfect, see "Known limitation" below |
| `qwen2.5:3b` (Ollama) | Chat replies when the message is Russian or English | Tested reliably coherent for both — `qwen2.5:7b` ignored the "reply in this language" instruction for Russian/English entirely |
| `faster-whisper` generic (`WHISPER_MODEL_SIZE`, default `medium`) | Mic transcription (Safari/Firefox) when Russian or English is selected | Solid multilingual accuracy; Armenian specifically is where it falls down, hence the next row |
| `Chillarmo/whisper-large-v3-turbo-armenian`, converted to CTranslate2 (`backend/whisper_armenian_ct2/`) | Mic transcription (Safari/Firefox) when `ՀԱՅ` is selected | Fine-tuned specifically on Armenian (15.3% WER) — the generic Whisper model hallucinated short Armenian phrases into nonsense words even with the correct language pinned |
| `facebook/mms-tts-hyw` (Meta MMS) | `POST /api/speak` only — **not called by the UI** | Kept as a reference/manual-testing endpoint; see "Audio output" |

All four language-model roles (2 chat + 2 STT) are picked automatically per
detected/selected language — there's no model picker in the UI.

## Project structure

```
MIC_Button_Trying_response/
├── backend/
│   ├── app.py                    # FastAPI app: /api/chat, /api/speak, /api/transcribe, /api/health, /api/models
│   ├── whisper_armenian_ct2/     # converted Armenian Whisper model (gitignored, built by you - see Setup)
│   └── requirements.txt
├── frontend/
│   ├── index.html                 # includes the ՀԱՅ/РУС/ENG language switcher
│   ├── app.js                     # chat UI, mic input (native + Whisper fallback), no audio playback
│   ├── style.css
│   ├── vite.config.js             # dev server on :5178, proxies /api to :8191
│   └── package.json
├── venv/                    # local Python virtualenv (gitignored)
├── start.sh                  # Mac/Linux launcher (backend :8191 + Vite :5178)
├── start.ps1                 # Windows launcher (same behavior as start.sh)
├── start.bat                  # double-click wrapper for start.ps1
├── PRIVACY.md
├── .gitignore
└── README.md
```

See [PRIVACY.md](PRIVACY.md) for exactly what happens to your voice/text
data (short version: everything stays local except Chrome/Edge's native mic
transcription, which is Google's, not this app's).

## Design

Colors/layout are unified with the sibling `Speach_to_text_upload_video_document`
app — same violet+teal accent palette, flat dark background with blurred
`.bg-blob` accents instead of a busy multi-color gradient, and the same
light-mode override via `prefers-color-scheme`, which this app didn't have
before. Chosen over this app's original 3-accent (violet/pink/cyan) look
because the shared one is calmer, more consistent as part of the same
Armenian-app family, and — unlike the original — actually supports light
mode. If you tweak one app's palette, update the other to match.

## Audio output

The frontend no longer calls any TTS — replies are text-only by design, so
you can wire up your own **Piper**-based voice output separately (per your
plan to train/use Piper directly rather than the non-commercial MMS voice —
see the license note below). The backend's `POST /api/speak` endpoint
(Meta MMS-TTS, Western Armenian) is still there and still works if you want
to call it directly or use it as a reference while you build the Piper
integration — it's just not wired into the UI anymore.

## Why these choices

- **LLM**: routed through Ollama, picked automatically per detected input
  language (see "Language support" above) — no model picker in the UI.
  Armenian uses `OLLAMA_MODEL` (default `qwen2.5:7b`), Russian/English use
  `OLLAMA_MODEL_RU`/`OLLAMA_MODEL_EN` (default `qwen2.5:3b` each). Change
  any of them with `ollama pull` + restarting the backend. See "Known
  limitation" below for why none of the current options are great for
  Armenian — `7b` is just the least-bad one tested so far, not a solved
  problem.
- **STT (mic → text)**: browser Web Speech API first choice — zero backend
  cost, streams audio to Google's servers for recognition (needs internet,
  behaves the same on Mac and Windows). Real Chromium browsers (Chrome, Edge)
  use it, with `recognition.lang` set from the language-switcher buttons in
  the topbar (ՀԱՅ/РУС/ENG) so the engine knows which language to expect —
  Web Speech API can't auto-detect the spoken language, it has to be told in
  advance, so pick the matching button before you talk. Everything else
  (Safari, Firefox) falls back to `MediaRecorder` + a local **Whisper** model
  (`faster-whisper`, CPU) on the backend — slower (few seconds of processing
  after you stop talking) and fully offline once the models are downloaded
  once.

  `/api/transcribe` used to force `language="hy"` on every recording
  regardless of what was actually spoken — a real bug, since it silently
  mangled Russian/English speech into garbled Armenian-ish text before it
  ever reached the chat endpoint. Dropping that pin entirely and letting
  Whisper auto-detect fixed Russian/English, but broke Armenian: Armenian is
  low-resource enough for Whisper that its language-ID step can misidentify
  short/ambiguous Armenian speech before transcription even starts (tested —
  a 1s silent clip auto-detected as `en` at only 39% confidence, showing how
  easily it misfires). So `/api/transcribe` now takes an optional `language`
  form field, which `frontend/app.js` fills in from the same language-switcher
  buttons (`hy`/`ru`/`en`) used for the native path above — pinning the
  correct language when the frontend knows it, falling back to auto-detect
  only if that field is missing or unrecognized.

  Pinning the language fixed *which* language Whisper decoded as, but not
  accuracy within Armenian — the generic model (`WHISPER_MODEL_SIZE`) still
  hallucinated real Armenian input into nonsense words (tested live: spoken
  "խաչապուրի" came back as "խաչապատ...ուտուստել") because it was never
  trained on much Armenian. So `/api/transcribe` now loads **two** Whisper
  models (`_load_stt` in `backend/app.py`) and picks between them by the
  `language` field: the fine-tuned `Chillarmo/whisper-large-v3-turbo-armenian`
  for `hy`, the generic `WHISPER_MODEL_SIZE` model for everything else. The
  fine-tuned model ships as a plain Transformers/Safetensors checkpoint, not
  the CTranslate2 format `faster-whisper` needs, so it's converted once
  (`ctranslate2.converters.transformers`, `--quantization int8`) into
  `backend/whisper_armenian_ct2/` (gitignored — a local build artifact, not
  checked in) — see "Setup" for the conversion command.

  **Gotcha that broke this once**: feature-detecting `webkitSpeechRecognition`
  isn't enough to decide which path to use — **Safari defines that API in the
  DOM but it doesn't actually work there** (`.start()` is a silent no-op, no
  events ever fire, no error either). Detecting it as "supported" made the
  code take the native-recognition branch in Safari and then do nothing at
  all, with the Whisper fallback never getting a chance to run. Fixed by
  gating native recognition on an actual Chromium check (`window.chrome` /
  `Edg/` / `CriOS` in the user agent), not just API presence — Safari now
  correctly falls through to the working Whisper path.
- **TTS (text → voice)**: not used by the frontend (see "Audio output"
  above). The backend still exposes `facebook/mms-tts-hyw` (Meta MMS) at
  `POST /api/speak` for anyone who wants to call it directly.

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
  on it — that's a real data-collection project, not a code change. This is
  exactly the path you're taking with your own Piper setup.
- The `tencent/Hy-Embodied-VLM-1.0` link isn't used here — that model is a
  robotics vision-language-action model (controls robot arms from camera
  frames), not a text/voice chat model, so it doesn't fit this use case.

## Language support: Armenian, Russian, English

`/api/chat` replies in whichever of the three languages the user's message
was written in, instead of forcing every reply into Armenian. The system
prompt tells the model to mirror the user's language (Armenian → Armenian,
Russian → Russian, English → English, defaulting to Armenian if it can't
tell), and the backend independently guesses the input language itself
(`detect_language`, a character-script heuristic: Armenian block
U+0530–U+058F, Cyrillic U+0400–U+04FF, or ASCII for English) so it knows
which script the *reply* should come back in.

**Model is routed by detected input language, not fixed.** Tested live:
`qwen2.5:7b` (`DEFAULT_MODEL`/`OLLAMA_MODEL`, the best of the bunch for
Armenian) simply ignores the "reply in the input language" instruction for
Russian and English input and answers in broken Armenian regardless —
a prompt tweak alone couldn't fix this, since the model won't follow the
instruction. `qwen2.5:3b` tested reliably coherent for both Russian and
English in a live side-by-side (though it's the weaker option for Armenian,
per "Known limitation" below — an inconsistent mix of decent and
mixed-script-garbled replies across runs). So `/api/chat` now maps detected
language → model (`LANGUAGE_MODELS` in `backend/app.py`): Armenian uses
`OLLAMA_MODEL`, Russian and English each default to `qwen2.5:3b`,
overridable via `OLLAMA_MODEL_RU` / `OLLAMA_MODEL_EN`. An explicit `model`
in the request body (scripting/testing only — the UI never sends one) still
overrides the automatic routing.

**Automatic correction, generalized across all three languages**:
`/api/chat` checks what fraction of the reply's letters are actually in the
script expected for the detected input language (`script_ratio`) and, if
that ratio is below 85%, silently retries the same request (up to 3
attempts total), keeping whichever attempt scored highest. This is the same
garbled-output guard as before (stray Latin/Cyrillic/CJK/Greek/Armenian
characters mixed into a reply that should be a single script), just no
longer hardcoded to only accept Armenian — a Russian or English reply won't
be endlessly retried for "not being Armenian" anymore. It's a real fix for
that specific problem, not a prompt tweak, though it can't turn an
incoherent reply into a correct one, only a script-clean one into the
response you get. It also means a chat call can now take up to 3x longer in
the worst case (each retry is a full model call).

**A second, stricter check catches contamination the ratio alone misses**:
tested live, `qwen2.5:7b` would sometimes write a long, otherwise-correct
Armenian reply and then tail off into a few characters of Chinese or Greek
script — not enough to drag the overall `script_ratio` below 85%, so the
ratio check alone let it through. `has_stray_foreign_script` checks for *any*
presence of CJK, Hiragana/Katakana, Hangul, or Greek characters (never
legitimate in an Armenian/Russian/English reply) and, for Armenian/Russian
specifically, *any* stray Latin-script fragment too (also observed live,
e.g. a token like "քենդalled") — Latin isn't flagged for English replies
since that's the expected script there. `/api/chat` prefers the first reply
across its 3 attempts that's both script-clean and above the ratio
threshold, falling back to the best-ratio reply (even if contaminated) only
if every attempt had some stray script in it. This makes Armenian replies
noticeably slower in the worst case (more retries get burned chasing a fully
clean attempt), and it's still a filter, not a fix for the underlying model
weakness — see "Known limitation" below.

## Known limitation: local Armenian LLM quality

The system prompt asks for plain "Armenian" (no dialect specifier) when
replying in Armenian, which in practice reads as Eastern Armenian —
deliberately, since these models were more precise and coherent that way.
Earlier the prompt forced **Western Armenian** specifically (to match the
MMS TTS voice, back when that was wired into the UI), but forcing that
dialect made an already-weak model's output *less* reliable — small models
seem to have much less Western Armenian in their training data, so asking
for it added a second hard constraint on top of "be coherent Armenian at
all" and precision suffered. Net effect: **Armenian text output here is
Eastern-flavored Armenian.** If/when your own Piper voice is Western
Armenian, that's a known dialect mismatch between this app's text and your
audio — worth keeping in mind, and something only a genuinely reliable
Western-Armenian-capable LLM would fix. Making the prompt more elaborate in
general (explicitly naming "classical Mesropian orthography" etc.) made
output *worse* too — small models seem to do best with short, plain
instructions. This limitation is specific to the Armenian branch; the
Russian and English replies aren't affected by it.

Tested against the models already pulled in your Ollama:

- `qwen2.5:3b` → produces broken/garbled Armenian (mixed-in stray
  characters), unusable as-is.
- `gemma2:2b` → real Armenian words but grammatically broken word-salad, not
  a coherent sentence — worse than qwen2.5:3b, not usable either.
- `qwen2.5:7b` (**current default**) → best of the four, opens with a
  mostly-coherent Armenian sentence, but still degrades mid-reply into
  garbled characters and then code-switches into Greek script entirely
  unprompted in some replies. Also much slower on CPU (~2 minutes per
  reply). In a direct side-by-side against `qwen2.5:3b` on the same
  question (a comment about the weather), `7b` actually stayed on-topic —
  `3b` replied with an unrelated non-sequitur about "your famous book" —
  but `7b`'s second sentence still trailed off into an invented, not-quite-
  real Armenian word. Better, but still not reliable — set as the default
  because it's the least-bad option tested so far, not because it's good.
- `armenia-lawyer-router` / `-v2` → per your own `Armenian_Chat_Status_and_TODO.md`
  notes in the sibling legal project, these degrade into gibberish after the
  first clause — same underlying issue, not fixed by this project.
- `gemma2:9b` → **not viable on this hardware, full stop** - tested live,
  timed out at 300s on every single request with no response at all, worse
  than `qwen2.5:7b`'s already-slow ~2 min/reply. This isn't a quality
  tradeoff to weigh, it's just too slow to use for an interactive assistant
  on CPU. Not worth re-testing without a GPU.

Beyond the models above, two more hallucination-flavored failure modes were
observed with `qwen2.5:7b` that are **not** script/language bugs and can't
be fixed by the retry/filter logic in `/api/chat`, since the text is
perfectly well-formed in the right language/script - the model just
confidently makes things up:
- **Topic-driven language drift**: asked in English "give me Yerevan's
  garden names," it answered in Armenian on all 3 attempts (script ratios
  0.15, 0.00, 0.17) even though the input was unambiguously English - the
  Armenia-related *topic* pulled it into Armenian regardless of the
  system prompt's language instruction. `/api/chat` now runs one corrective
  translation pass when this happens (see "Automatic correction" above),
  which fixes the *script* (the reply comes back genuinely in the right
  language) but can't fix content that was hallucinated garbage in the
  first place - translating nonsense produces nonsense in a different
  language, not a correct answer.
- **Fabricated facts**: asked in Armenian for real Yerevan park names, it
  returned a confident, grammatically fine, numbered list of 10 names -
  none of which are real parks. This is base-model hallucination (no real
  knowledge of local Yerevan geography), not a formatting problem; fixing
  it for real would need either a model with genuine local knowledge or a
  retrieval/grounding step (looking up real data instead of letting the
  model invent it), not more prompt engineering.

To compare another model's Armenian output, `ollama pull` it (e.g.
`aya-expanse`, `command-r`), set `OLLAMA_MODEL` to its name, and restart the
backend - but check it actually runs fast enough on your hardware first;
see the `gemma2:9b` result above. In practice, small (2–4B) open models are
generally weak at Armenian, and CPU inference makes anything much larger
than `qwen2.5:7b` impractically slow; if quality matters, plan on either a
GPU or a model specifically fine-tuned for Armenian.

## Setup

Backend Python deps go in `./venv` (isolated virtualenv, not your global
Python — see `backend/requirements.txt`). Frontend deps go in
`frontend/node_modules` (just Vite).

1. First time only:
   ```bash
   # Mac/Linux
   python3 -m venv venv
   ./venv/bin/pip install -r backend/requirements.txt
   cd frontend && npm install && cd ..
   ```
   ```powershell
   # Windows
   python -m venv venv
   .\venv\Scripts\pip install -r backend\requirements.txt
   cd frontend; npm install; cd ..
   ```
2. Make sure Ollama is running and has at least one model pulled:
   ```bash
   ollama serve &          # if not already running
   ollama pull qwen2.5:7b  # the default; or qwen2.5:3b, gemma2:2b, etc.
   ```
3. **One-time, optional but recommended**: convert the fine-tuned Armenian
   Whisper model so `/api/transcribe` can use it for Armenian mic input
   (skip this if you only care about Russian/English voice input, or don't
   use Safari/Firefox at all — Chrome/Edge never hit Whisper). Downloads
   ~3GB and needs `ctranslate2`, already in `backend/requirements.txt`:
   ```bash
   ./venv/bin/python3 -c "
   import sys
   from ctranslate2.converters.transformers import main
   sys.argv = [
       'ct2-transformers-converter',
       '--model', 'Chillarmo/whisper-large-v3-turbo-armenian',
       '--output_dir', 'backend/whisper_armenian_ct2',
       '--copy_files', 'tokenizer_config.json', 'preprocessor_config.json',
       '--quantization', 'int8',
       '--force',
   ]
   sys.exit(main())
   "
   ```
   If `backend/whisper_armenian_ct2/` doesn't exist, Armenian mic input
   just falls back to the generic `WHISPER_MODEL_SIZE` model — still works,
   just less accurate for Armenian specifically (see "Models used").
4. Start everything (backend on `:8191` + Vite on `:5178`):
   ```bash
   ./start.sh          # Mac/Linux
   ```
   On Windows, double-click `start.bat` (or run `start.ps1` directly in
   PowerShell) — same behavior as `start.sh`, backend port `:8191` fixed
   either way so it never collides with the frontend's `:5178`.

   Backend only, without Vite: `cd backend && python3 app.py` also works
   directly (no `--reload` though — use `uvicorn backend.app:app --reload`
   from the project root, or `../start.sh`, if you want that).
5. Open **http://localhost:5178** in any modern browser — Chrome/Edge use
   native speech recognition for the mic button, Safari/Firefox use the
   Whisper fallback automatically. Port `:8191` was picked to avoid clashing
   with your other local projects (`:8001` BetterTalkNowAI, `:8000/:5173`
   etc. elsewhere).

First mic use in Safari/Firefox (~10-20s) will be slow while the Whisper
model downloads and loads into memory; it's cached in RAM after that for the
rest of the session, and on disk (`~/.cache/huggingface`) for future runs.
The backend also warms up the (unused-by-UI) MMS-TTS model on startup for
the same reason, in case you call `/api/speak` directly.

## Config (env vars, optional)

- `OLLAMA_URL` — default `http://localhost:11434`
- `OLLAMA_MODEL` — default `qwen2.5:7b`, used for Armenian-detected input
  (and whenever the caller doesn't pass an explicit `model`)
- `OLLAMA_MODEL_RU` — default `qwen2.5:3b`, used for Russian-detected input
- `OLLAMA_MODEL_EN` — default `qwen2.5:3b`, used for English-detected input
- `TTS_MODEL_ID` — default `facebook/mms-tts-hyw`
- `WHISPER_MODEL_SIZE` — default `medium` (Safari/Firefox STT fallback for
  Russian/English; larger = more accurate but slower on CPU). Only affects
  the *generic* Whisper model — Armenian mic input uses the dedicated
  fine-tuned model in `backend/whisper_armenian_ct2/` instead (see "Models
  used" and "Setup"), not this one. Used to default to `small`, which
  garbled/hallucinated short phrases (e.g. "Բարև ոնց ես" transcribed as
  unrelated, mixed-script gibberish) instead of failing cleanly — bumped to
  `medium` after that was observed live. Chrome/Edge don't hit either
  Whisper model at all since they skip straight to the browser's native
  speech recognition.

## API

- `GET /api/health` — Ollama connectivity + available models
- `GET /api/models` — list of pulled Ollama models (debugging only, not used by the UI)
- `POST /api/chat` `{message, model?, history?}` → `{reply, model}` — `model`
  is optional and only useful for scripting/testing; the UI never sends it
- `POST /api/speak` `{text}` → `audio/wav` bytes
- `POST /api/transcribe` (multipart, fields `audio`, optional `language`
  = `hy`/`ru`/`en`) → `{text}` — Whisper fallback used by browsers without
  Web Speech Recognition. `language` picks which Whisper model runs (the
  Armenian fine-tune for `hy`, the generic model otherwise) and pins
  Whisper's decode language; omit it to auto-detect instead (less reliable
  for Armenian specifically — see "Why these choices"). The UI always sends
  it, from whichever language-switcher button is active.
