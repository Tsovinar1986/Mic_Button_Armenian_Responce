(() => {
  const chatEl = document.getElementById("chat");
  const composer = document.getElementById("composer");
  const textInput = document.getElementById("textInput");
  const micBtn = document.getElementById("micBtn");
  const modelSelect = document.getElementById("modelSelect");
  const statusPill = document.getElementById("statusPill");
  const listeningBanner = document.getElementById("listeningBanner");
  const interimText = document.getElementById("interimText");
  const supportNote = document.getElementById("supportNote");
  const ttsAudio = document.getElementById("ttsAudio");

  const history = []; // {role, content}
  let busy = false;

  // ---------------- Chat rendering ----------------
  function addMessage(role, content) {
    const div = document.createElement("div");
    div.className = `msg ${role}`;
    const textNode = document.createElement("span");
    textNode.textContent = content;
    div.appendChild(textNode);

    if (role === "assistant") {
      const btn = document.createElement("button");
      btn.className = "speaker-btn";
      btn.type = "button";
      btn.innerHTML = "🔊 Listen";
      btn.addEventListener("click", () => speak(content, btn));
      div.appendChild(btn);
    }

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
  async function loadHealthAndModels() {
    try {
      const res = await fetch("/api/models");
      if (!res.ok) throw new Error("bad status");
      const data = await res.json();
      modelSelect.innerHTML = "";
      data.models.forEach((name) => {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        if (name === data.default_model) opt.selected = true;
        modelSelect.appendChild(opt);
      });
      if (!data.models.length) {
        const opt = document.createElement("option");
        opt.textContent = "no models pulled";
        modelSelect.appendChild(opt);
      }
      setStatus("ok", `Ollama connected · ${data.models.length} model(s)`);
    } catch (e) {
      setStatus("bad", "Ollama unreachable");
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
          model: modelSelect.value || undefined,
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
      const bubble = addMessage("assistant", data.reply);
      const speakerBtn = bubble.querySelector(".speaker-btn");
      speak(data.reply, speakerBtn);
    } catch (e) {
      removeTypingIndicator();
      addMessage("system", `Network error: ${e.message}`);
    } finally {
      busy = false;
      micBtn.disabled = !recognitionSupported;
    }
  }

  composer.addEventListener("submit", (e) => {
    e.preventDefault();
    sendMessage(textInput.value);
  });

  // ---------------- Text-to-speech ----------------
  async function speak(text, btn) {
    if (btn) btn.classList.add("speaking");

    // 1) Try backend Armenian TTS (Meta MMS-TTS)
    try {
      const res = await fetch("/api/speak", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (res.ok) {
        const blob = await res.blob();
        ttsAudio.src = URL.createObjectURL(blob);
        await ttsAudio.play();
        ttsAudio.onended = () => btn && btn.classList.remove("speaking");
        return;
      }
    } catch (e) {
      // fall through to browser TTS
    }

    // 2) Fallback: browser speech synthesis
    if ("speechSynthesis" in window) {
      const utter = new SpeechSynthesisUtterance(text);
      utter.lang = "hyw"; // Western Armenian, matching the backend MMS-TTS voice
      const voices = window.speechSynthesis.getVoices();
      const hyVoice = voices.find((v) => v.lang && v.lang.toLowerCase().startsWith("hy"));
      if (hyVoice) utter.voice = hyVoice;
      utter.onend = () => btn && btn.classList.remove("speaking");
      window.speechSynthesis.speak(utter);
    } else if (btn) {
      btn.classList.remove("speaking");
    }
  }

  // ---------------- Speech recognition (mic input) ----------------
  const SpeechRecognitionImpl = window.SpeechRecognition || window.webkitSpeechRecognition;
  const recognitionSupported = !!SpeechRecognitionImpl;
  let recognition = null;
  let listening = false;

  if (recognitionSupported) {
    recognition = new SpeechRecognitionImpl();
    recognition.lang = "hy-AM";
    recognition.continuous = false;
    recognition.interimResults = true;

    recognition.onstart = () => {
      listening = true;
      micBtn.classList.add("listening");
      listeningBanner.classList.remove("hidden");
      interimText.textContent = "Listening…";
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
      micBtn.classList.remove("listening");
      listeningBanner.classList.add("hidden");
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
  } else {
    micBtn.disabled = true;
    supportNote.textContent =
      "Voice input isn't supported in this browser — try Chrome. You can still type in Armenian below.";
  }

  // ---------------- Init ----------------
  addMessage(
    "assistant",
    "Բարև ձեզ։ Ես ձեր հայալեզու ձայնային օգնականն եմ։ Կարող եք գրել կամ սեղմել մայկը՝ ինձ հետ խոսելու համար։"
  );
  loadHealthAndModels();
  if (window.speechSynthesis) {
    // Some browsers load voices asynchronously.
    window.speechSynthesis.onvoiceschanged = () => window.speechSynthesis.getVoices();
  }
})();
