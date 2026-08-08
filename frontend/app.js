(() => {
  const chatEl = document.getElementById("chat");
  const composer = document.getElementById("composer");
  const textInput = document.getElementById("textInput");
  const micBtn = document.getElementById("micBtn");
  const statusPill = document.getElementById("statusPill");
  const listeningBanner = document.getElementById("listeningBanner");
  const interimText = document.getElementById("interimText");
  const supportNote = document.getElementById("supportNote");
  const langSwitcher = document.getElementById("langSwitcher");
  const outputModeBtn = document.getElementById("outputModeBtn");
  const brandTitle = document.getElementById("brandTitle");

  const history = []; // {role, content}
  let busy = false;

  // ---------------- Language switcher ----------------
  // Backend already auto-detects the reply language from whatever the user
  // types/says (see README "Language support"), so this only controls the
  // AI's first written greeting, the input placeholder, and (as a bonus)
  // which language the mic listens for.
  const GREETINGS = {
    hy: "Բարև ձեզ։ Ես ձեր ձայնային օգնականն եմ և կարող եմ պատասխանել հայերեն, ռուսերեն կամ անգլերեն։ Կարող եք գրել կամ սեղմել մայկը՝ ինձ հետ խոսելու համար։",
    ru: "Привет! Я ваш голосовой помощник и могу отвечать на армянском, русском или английском. Напишите сообщение или нажмите на микрофон, чтобы поговорить со мной.",
    en: "Hi there! I'm your voice assistant and can reply in Armenian, Russian, or English. Type a message or press the mic to talk to me.",
  };
  const PLACEHOLDERS = {
    hy: "Գրեք հայերեն, ռուսերեն կամ անգլերեն, կամ սեղմեք մայկը՝ խոսելու համար…",
    ru: "Напишите на армянском, русском или английском, или нажмите на микрофон…",
    en: "Type in Armenian, Russian, or English, or press the mic to talk…",
  };
  const MIC_LANG_CODES = { hy: "hy-AM", ru: "ru-RU", en: "en-US" };
  const BRAND_NAMES = { hy: "Ձայնային Օգնական", ru: "Голосовой помощник", en: "Voice Assistant" };

  let currentLang = "hy";

  function setLanguage(lang) {
    if (!GREETINGS[lang]) return;
    currentLang = lang;
    stopSpeaking();

    langSwitcher.querySelectorAll(".lang-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.lang === lang);
    });

    history.length = 0;
    chatEl.innerHTML = "";
    addMessage("assistant", GREETINGS[lang]);

    textInput.placeholder = PLACEHOLDERS[lang];
    if (recognition) recognition.lang = MIC_LANG_CODES[lang];

    brandTitle.textContent = BRAND_NAMES[lang];
    document.title = `${BRAND_NAMES[lang]} · Voice Assistant`;
  }

  langSwitcher.addEventListener("click", (e) => {
    const btn = e.target.closest(".lang-btn");
    if (btn) setLanguage(btn.dataset.lang);
  });

  // ---------------- Voice / text reply toggle ----------------
  // Text-only was the deliberate default (see README "Audio output"), but
  // this lets you opt into hearing replies instead of just reading them.
  // Armenian speech comes from this app's own backend (POST /api/speak,
  // Meta MMS-TTS) since that's already wired up and warmed up on startup.
  // Russian/English use the browser's built-in speechSynthesis instead of
  // a backend model - there's no Piper (or other) voice wired in for those
  // two languages yet, so this is a pragmatic stopgap, not the final plan.
  let outputMode = "text"; // "text" | "voice"
  let currentAudio = null;

  function stopSpeaking() {
    if (currentAudio) {
      currentAudio.pause();
      currentAudio = null;
    }
    if (window.speechSynthesis) window.speechSynthesis.cancel();
  }

  function setOutputMode(mode) {
    outputMode = mode;
    const voice = mode === "voice";
    outputModeBtn.dataset.mode = mode;
    outputModeBtn.setAttribute("aria-pressed", String(voice));
    outputModeBtn.textContent = voice ? "🔊 Voice" : "💬 Text";
    outputModeBtn.title = voice ? "Replying with voice — click for text" : "Replying as text — click for voice";
    if (!voice) stopSpeaking();
  }

  outputModeBtn.addEventListener("click", () => {
    setOutputMode(outputMode === "voice" ? "text" : "voice");
  });

  async function speakReply(text, lang) {
    stopSpeaking();
    if (lang === "hy") {
      try {
        const res = await fetch("/api/speak", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
        if (!res.ok) throw new Error(res.statusText);
        const blob = await res.blob();
        currentAudio = new Audio(URL.createObjectURL(blob));
        currentAudio.play();
      } catch (e) {
        addMessage("system", `Voice synthesis error: ${e.message}`);
      }
      return;
    }
    if (!window.speechSynthesis) {
      addMessage("system", "Voice replies aren't supported in this browser.");
      return;
    }
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = MIC_LANG_CODES[lang];
    window.speechSynthesis.speak(utterance);
  }

  // ---------------- Chat rendering ----------------
  function addMessage(role, content, historyIndex) {
    const div = document.createElement("div");
    div.className = `msg ${role}`;
    const textNode = document.createElement("span");
    textNode.className = "msg-text";
    textNode.textContent = content;
    div.appendChild(textNode);

    // Edit-and-resend, like ChatGPT/Gemini: fix a typo or a misheard mic
    // transcription without retyping the whole message, then regenerate
    // the reply from that point - everything after it (including the old
    // reply) is discarded since it was based on the wrong message.
    if (role === "user" && historyIndex !== undefined) {
      div.dataset.historyIndex = String(historyIndex);
      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "edit-btn";
      editBtn.setAttribute("aria-label", "Edit message");
      editBtn.title = "Edit and resend";
      editBtn.textContent = "✏️";
      editBtn.addEventListener("click", () => enterEditMode(div, historyIndex, content));
      div.appendChild(editBtn);
    }

    chatEl.appendChild(div);
    chatEl.scrollTop = chatEl.scrollHeight;
    return div;
  }

  function enterEditMode(div, historyIndex, originalText) {
    if (busy) return;
    div.innerHTML = "";
    div.classList.add("editing");

    const textarea = document.createElement("textarea");
    textarea.className = "edit-textarea";
    textarea.value = originalText;

    const actions = document.createElement("div");
    actions.className = "edit-actions";
    const resendBtn = document.createElement("button");
    resendBtn.type = "button";
    resendBtn.textContent = "Resend";
    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.textContent = "Cancel";
    actions.append(resendBtn, cancelBtn);

    div.append(textarea, actions);
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);

    const cancel = () => {
      div.classList.remove("editing");
      div.innerHTML = "";
      const textNode = document.createElement("span");
      textNode.className = "msg-text";
      textNode.textContent = originalText;
      div.appendChild(textNode);
      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "edit-btn";
      editBtn.setAttribute("aria-label", "Edit message");
      editBtn.title = "Edit and resend";
      editBtn.textContent = "✏️";
      editBtn.addEventListener("click", () => enterEditMode(div, historyIndex, originalText));
      div.appendChild(editBtn);
    };

    const resend = () => {
      const newText = textarea.value.trim();
      if (!newText) return;
      resendFrom(historyIndex, newText);
    };

    resendBtn.addEventListener("click", resend);
    cancelBtn.addEventListener("click", cancel);
    textarea.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        resend();
      } else if (e.key === "Escape") {
        cancel();
      }
    });
  }

  function resendFrom(historyIndex, newText) {
    stopSpeaking();
    // Drop this message and everything after it - the old reply (and any
    // later turns) were responses to the un-edited text, so they no longer
    // apply once it's changed.
    history.length = historyIndex;
    const nodes = Array.from(chatEl.children);
    const cutoffNode = nodes.find((n) => n.dataset.historyIndex === String(historyIndex));
    if (cutoffNode) {
      let node = cutoffNode;
      while (node) {
        const next = node.nextSibling;
        node.remove();
        node = next;
      }
    }
    sendMessage(newText);
  }

  function addTypingIndicator() {
    const div = document.createElement("div");
    div.className = "msg assistant";
    div.id = "typingIndicator";
    div.innerHTML = '<span class="typing-dots"><span></span><span></span><span></span></span>';
    chatEl.appendChild(div);
    chatEl.scrollTop = chatEl.scrollHeight;
  }

  function removeTypingIndicator() {
    const el = document.getElementById("typingIndicator");
    if (el) el.remove();
  }

  function setStatus(kind, label) {
    statusPill.className = `status-pill status-${kind}`;
    statusPill.textContent = label;
  }

  // ---------------- Backend calls ----------------
  async function loadHealth() {
    try {
      const res = await fetch("/api/health");
      if (!res.ok) throw new Error("bad status");
      const data = await res.json();
      if (data.ollama) {
        setStatus("ok", "Connected");
      } else {
        setStatus("bad", "Unreachable");
      }
    } catch (e) {
      setStatus("bad", "Backend unreachable");
    }
  }

  async function sendMessage(text) {
    if (busy || !text.trim()) return;
    busy = true;
    micBtn.disabled = true;
    textInput.value = "";

    addMessage("user", text, history.length);
    history.push({ role: "user", content: text });
    addTypingIndicator();

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          history: history.slice(0, -1),
        }),
      });
      removeTypingIndicator();

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        addMessage("system", `Error: ${err.detail || res.statusText}`);
        return;
      }

      const data = await res.json();
      history.push({ role: "assistant", content: data.reply });
      addMessage("assistant", data.reply);
      // reply_lang is what script the reply actually came back in - not
      // always the same as currentLang, since the model can occasionally
      // answer in the wrong language despite the backend's retries (e.g.
      // an English question about Armenia drifting into an Armenian
      // answer). Speaking with the wrong voice would be worse than not
      // matching the UI's selected language, so trust the reply itself.
      if (outputMode === "voice") speakReply(data.reply, data.reply_lang || currentLang);
    } catch (e) {
      removeTypingIndicator();
      addMessage("system", `Network error: ${e.message}`);
    } finally {
      busy = false;
      micBtn.disabled = !micAvailable;
    }
  }

  composer.addEventListener("submit", (e) => {
    e.preventDefault();
    sendMessage(textInput.value);
  });

  // ---------------- Speech recognition (mic input) ----------------
  // Safari exposes `webkitSpeechRecognition` in the DOM but it doesn't
  // actually work there (start() is a silent no-op) — so feature detection
  // alone isn't enough. Only trust it in real Chromium browsers, and let
  // Safari fall through to the MediaRecorder + backend Whisper path below.
  const isChromiumBrowser = !!window.chrome || /Edg\//.test(navigator.userAgent) || /CriOS/.test(navigator.userAgent);
  const SpeechRecognitionImpl = window.SpeechRecognition || window.webkitSpeechRecognition;
  const recognitionSupported = !!SpeechRecognitionImpl && isChromiumBrowser;
  const mediaRecorderSupported =
    !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia) && !!window.MediaRecorder;
  const micAvailable = recognitionSupported || mediaRecorderSupported;
  let recognition = null;
  let listening = false;

  function showListening(label) {
    micBtn.classList.add("listening");
    listeningBanner.classList.remove("hidden");
    interimText.textContent = label;
  }

  function hideListening() {
    micBtn.classList.remove("listening");
    listeningBanner.classList.add("hidden");
  }

  if (recognitionSupported) {
    // Preferred path: native browser speech recognition (Chrome, Edge).
    recognition = new SpeechRecognitionImpl();
    recognition.lang = MIC_LANG_CODES[currentLang];
    recognition.continuous = false;
    recognition.interimResults = true;

    recognition.onstart = () => {
      listening = true;
      showListening("Listening…");
    };

    recognition.onresult = (event) => {
      let finalTranscript = "";
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) finalTranscript += transcript;
        else interim += transcript;
      }
      if (interim) interimText.textContent = interim;
      if (finalTranscript) {
        textInput.value = finalTranscript;
      }
    };

    recognition.onerror = (event) => {
      interimText.textContent = `Mic error: ${event.error}`;
    };

    recognition.onend = () => {
      listening = false;
      hideListening();
      const finalText = textInput.value.trim();
      if (finalText) sendMessage(finalText);
    };

    micBtn.addEventListener("click", () => {
      if (listening) {
        recognition.stop();
      } else {
        textInput.value = "";
        try {
          recognition.start();
        } catch (e) {
          // already started; ignore
        }
      }
    });
  } else if (mediaRecorderSupported) {
    // Fallback path: record audio and transcribe it on the backend (Whisper).
    // Needed for Safari/Firefox, which don't implement SpeechRecognition.
    let mediaRecorder = null;
    let chunks = [];
    let stream = null;

    function pickMimeType() {
      const candidates = ["audio/mp4", "audio/webm", "audio/ogg"];
      return candidates.find((t) => window.MediaRecorder.isTypeSupported(t)) || "";
    }

    async function startRecording() {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (e) {
        interimText.textContent = "Microphone permission denied.";
        listeningBanner.classList.remove("hidden");
        setTimeout(() => listeningBanner.classList.add("hidden"), 2500);
        return;
      }
      const mimeType = pickMimeType();
      chunks = [];
      mediaRecorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data);
      };
      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        hideListening();
        if (!chunks.length) return;

        showListening("Transcribing…");
        const blob = new Blob(chunks, { type: mediaRecorder.mimeType || "audio/webm" });
        const form = new FormData();
        const ext = blob.type.includes("mp4") ? "m4a" : blob.type.includes("ogg") ? "ogg" : "webm";
        form.append("audio", blob, `speech.${ext}`);
        // Tell Whisper which language to expect (matches the active ՀԱՅ/РУС/ENG
        // button) instead of leaving it to auto-detect - Armenian is
        // low-resource enough for Whisper that auto-detect alone can
        // misidentify short/ambiguous speech and garble the transcription.
        form.append("language", currentLang);

        try {
          const res = await fetch("/api/transcribe", { method: "POST", body: form });
          hideListening();
          if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            addMessage("system", `Transcription error: ${err.detail || res.statusText}`);
            return;
          }
          const data = await res.json();
          const text = (data.text || "").trim();
          if (text) {
            textInput.value = text;
            sendMessage(text);
          } else {
            addMessage("system", "Didn't catch that — please try again or type your message.");
          }
        } catch (e) {
          hideListening();
          addMessage("system", `Transcription network error: ${e.message}`);
        }
      };
      mediaRecorder.start();
      listening = true;
      showListening("Listening…");
    }

    function stopRecording() {
      listening = false;
      if (mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
    }

    micBtn.addEventListener("click", () => {
      if (listening) {
        stopRecording();
      } else {
        startRecording();
      }
    });
  }

  if (!micAvailable) {
    micBtn.disabled = true;
    supportNote.textContent =
      "Voice input isn't supported in this browser — try Chrome, Edge, or Safari. You can still type in Armenian, Russian, or English below.";
  }

  // ---------------- Init ----------------
  setLanguage(currentLang);
  loadHealth();
})();
