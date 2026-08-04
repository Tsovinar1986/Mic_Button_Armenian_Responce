# Privacy Policy

_Last updated: 2026-08-04_

This is a self-hosted, local-first app. There is no account system, no
analytics, no tracking cookies, and no third-party server that this project
controls. This document describes exactly what happens to your data, based
on how the app is actually built — not boilerplate.

## What data this app handles

- **Text you type**, or that gets transcribed from your voice.
- **Microphone audio**, only while you're actively using the mic button.
- **Conversation history for the current browser tab**, kept in memory only
  (a JavaScript variable) so the assistant has context — never written to
  disk, `localStorage`, or a cookie. Reloading the page erases it.

## Where that data goes

**Typed or transcribed text (`/api/chat`)**: sent from your browser to the
backend running on your own machine, which forwards it to your local
**Ollama** server (`localhost:11434`) to generate a reply. Nothing here
leaves your computer — Ollama runs entirely locally.

**Microphone audio, if you're on Chrome or Edge**: the browser's built-in
Web Speech Recognition API streams your voice directly to **Google's**
speech-recognition servers to convert it to text — this happens inside the
browser itself, not through this app's backend, and this app never receives
or stores the raw audio in that path. That transfer is governed by Google's
own privacy policy, not this project's, since this app has no control over
it. This is the one part of the app where audio leaves your machine.

**Microphone audio, if you're on Safari or Firefox**: recorded in your
browser and uploaded to this app's own backend (`/api/transcribe`), which
transcribes it locally using a **Whisper** model (`faster-whisper`) running
on your own machine. The audio is written to a temporary file only for the
duration of transcription and is deleted immediately after — it is never
stored, logged, or sent anywhere else.

**Text sent to `/api/speak`** (Armenian text-to-speech, Meta's MMS model):
processed entirely locally on your machine. This endpoint isn't currently
called by the app's UI, but it's still reachable if you or another tool
calls it directly.

## What this app does NOT do

- No analytics, telemetry, or usage tracking of any kind.
- No cookies, no accounts, no sign-in.
- No persistent storage of your messages or audio — nothing is written to a
  database or log file beyond the local terminal output you see while the
  server is running (which is on your own machine, under your own control).
- No data is sold, shared, or sent to any server other than the two
  described above (your own local Ollama/Whisper/MMS-TTS, and — only for
  Chrome/Edge mic input — Google's speech recognition service).

## Your responsibility if you deploy this beyond localhost

This policy describes the app as built: running on `localhost` for local,
personal use. If you ever deploy this somewhere reachable by other people
(a shared server, a public URL), you become responsible for how you handle
data in that context — e.g. server logs may then capture real user IP
addresses and message content, and you'd need to disclose that. This
document does not cover that scenario.
