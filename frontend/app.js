(() => {
  const chatEl = document.getElementById("chat");
  const composer = document.getElementById("composer");
  const textInput = document.getElementById("textInput");
  const micBtn = document.getElementById("micBtn");
  const statusPill = document.getElementById("statusPill");
  const listeningBanner = document.getElementById("listeningBanner");
  const interimText = document.getElementById("interimText");
  const supportNote = document.getElementById("supportNote");

  const history = []; // {role, content}
  let busy = false;

  // ---------------- Chat rendering ----------------
  function addMessage(role, content) {
    const div = document.createElement("div");
    div.className = `msg ${role}`;
    const textNode = document.createElement("span");
    textNode.textContent = content;
    div.appendChild(textNode);

    chatEl.appendChild(div);
    chatEl.scrollTop = chatEl.scrollHeight;
    return div;
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

    addMessage("user", text);
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
    recognition.lang = "hy-AM";
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
      "Voice input isn't supported in this browser — try Chrome, Edge, or Safari. You can still type in Armenian below.";
  }

  // ---------------- Init ----------------
  addMessage(
    "assistant",
    "Բարև ձեզ։ Ես ձեր հայալեզու ձայնային օգնականն եմ։ Կարող եք գրել կամ սեղմել մայկը՝ ինձ հետ խոսելու համար։"
  );
  loadHealth();
})();
