const messagesEl = document.querySelector("#messages");
const statusEl = document.querySelector("#status");
const textForm = document.querySelector("#textForm");
const textInput = document.querySelector("#textInput");
const sendBtn = document.querySelector("#sendBtn");
const recordBtn = document.querySelector("#recordBtn");
const recordLabel = document.querySelector("#recordLabel");
const resetBtn = document.querySelector("#resetBtn");

let recorder = null;
let recognition = null;
let appleLiveSource = null;
let appleLiveTranscript = "";
let chunks = [];
let busy = false;
let config = {
  stt_provider: "browser",
  stt_language: "de",
  browser_stt_local: true,
};
let liveTranscriptEl = null;

showEmptyState();
loadConfig();

resetBtn.addEventListener("click", () => {
  messagesEl.innerHTML = "";
  showEmptyState();
});

textForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = textInput.value.trim();
  if (!message || busy) return;
  textInput.value = "";
  await sendText(message);
});

recordBtn.addEventListener("click", async () => {
  if (busy) return;
  if (appleLiveSource) {
    await stopAppleLiveRecognition();
    return;
  }
  if (recognition) {
    recognition.stop();
    return;
  }
  if (recorder?.state === "recording") {
    recorder.stop();
    return;
  }
  if (config.stt_provider === "browser" && browserSpeechSupported()) {
    startBrowserSpeechRecognition();
  } else if (config.stt_provider === "apple") {
    await startAppleLiveRecognition();
  } else {
    await startRecording();
  }
});

async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    config = { ...config, ...(await res.json()) };
    const model = config.ollama_model || "unbekannt";
    const ollama = config.ollama_ok ? "Ollama verbunden" : "Ollama nicht erreichbar";
    const stt = sttStatusText();
    statusEl.textContent = `${ollama} · Modell: ${model} · ${stt}`;
  } catch (error) {
    statusEl.textContent = "Server erreichbar, Konfiguration konnte nicht geladen werden";
  }
}

function browserSpeechSupported() {
  return Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
}

function sttStatusText() {
  if (config.stt_provider === "apple") return "Apple Live On-Device STT";
  if (config.stt_provider === "browser" && browserSpeechSupported()) {
    return config.browser_stt_local ? "Lokale Browser-STT bevorzugt" : "Live-STT im Browser";
  }
  return "MLX-Whisper";
}

async function startAppleLiveRecognition() {
  try {
    const res = await fetch("/api/apple-live/start", { method: "POST" });
    await readJson(res);
  } catch (error) {
    addMessage("system", `Apple Live-STT konnte nicht starten: ${error.message}`);
    return;
  }

  appleLiveTranscript = "";
  liveTranscriptEl = addMessage("system", "Hoere lokal zu...");
  recordBtn.classList.add("recording");
  recordLabel.textContent = "Stoppen";

  appleLiveSource = new EventSource("/api/apple-live/events");
  appleLiveSource.addEventListener("message", (event) => {
    let data = null;
    try {
      data = JSON.parse(event.data);
    } catch (error) {
      liveTranscriptEl.textContent = event.data || "Hoere lokal zu...";
      return;
    }

    if (data.type === "ready") {
      liveTranscriptEl.textContent = "Hoere lokal zu...";
    } else if (data.type === "partial" || data.type === "final") {
      appleLiveTranscript = (data.text || "").trim();
      liveTranscriptEl.textContent = appleLiveTranscript || "Hoere lokal zu...";
    } else if (data.type === "error") {
      liveTranscriptEl.textContent = `Apple Live-STT Fehler: ${data.text}`;
    }
  });

  appleLiveSource.addEventListener("error", () => {
    if (appleLiveSource) {
      addMessage("system", "Apple Live-STT Verbindung wurde beendet.");
    }
  });
}

async function stopAppleLiveRecognition() {
  const transcript = appleLiveTranscript.trim();
  cleanupAppleLiveRecognition();
  try {
    await fetch("/api/apple-live/stop", { method: "POST" });
  } catch (error) {
    addMessage("system", `Apple Live-STT konnte nicht gestoppt werden: ${error.message}`);
  }

  liveTranscriptEl?.remove();
  liveTranscriptEl = null;

  if (transcript) {
    await sendText(transcript);
  } else {
    addMessage("system", "Keine Sprache erkannt.");
  }
}

function cleanupAppleLiveRecognition() {
  appleLiveSource?.close();
  appleLiveSource = null;
  appleLiveTranscript = "";
  recordBtn.classList.remove("recording");
  recordLabel.textContent = "Gedrückt starten";
}

function startBrowserSpeechRecognition() {
  startBrowserSpeechRecognitionWithMode(Boolean(config.browser_stt_local));
}

function startBrowserSpeechRecognitionWithMode(processLocally) {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechRecognition();
  recognition.lang = normalizeSpeechLanguage(config.stt_language);
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;
  if ("processLocally" in recognition) {
    recognition.processLocally = processLocally;
  } else if (processLocally) {
    addMessage("system", "Lokale Browser-STT wird von diesem Browser nicht angeboten. Nutze Browser-STT.");
  }

  let finalText = "";
  let interimText = "";
  liveTranscriptEl = addMessage("system", processLocally ? "Hoere lokal zu..." : "Hoere zu...");
  recordBtn.classList.add("recording");
  recordLabel.textContent = "Stoppen";

  recognition.addEventListener("result", (event) => {
    interimText = "";
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const result = event.results[i];
      const text = result[0]?.transcript || "";
      if (result.isFinal) {
        finalText += `${text} `;
      } else {
        interimText += text;
      }
    }
    liveTranscriptEl.textContent = (finalText + interimText).trim() || "Hoere zu...";
  });

  recognition.addEventListener("error", async (event) => {
    const error = event.error || "";
    const message = error ? `Browser-STT Fehler: ${error}` : "Browser-STT Fehler";
    cleanupBrowserSpeech();
    liveTranscriptEl?.remove();
    liveTranscriptEl = null;
    if (processLocally) {
      addMessage("system", `${message}. Lokale STT nicht verfuegbar, versuche Browser-STT.`);
      startBrowserSpeechRecognitionWithMode(false);
    } else {
      addMessage("system", `${message}. Fallback: Audioaufnahme verwenden.`);
      await startRecording();
    }
  });

  recognition.addEventListener("end", async () => {
    const transcript = (finalText + interimText).trim();
    cleanupBrowserSpeech();
    liveTranscriptEl?.remove();
    liveTranscriptEl = null;
    if (transcript) {
      await sendText(transcript);
    } else {
      addMessage("system", "Keine Sprache erkannt.");
    }
  });

  recognition.start();
}

function cleanupBrowserSpeech() {
  recognition = null;
  recordBtn.classList.remove("recording");
  recordLabel.textContent = "Gedrückt starten";
}

function normalizeSpeechLanguage(language) {
  if (!language) return "de-DE";
  if (language === "de") return "de-DE";
  if (language === "en") return "en-US";
  return language;
}

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    chunks = [];
    recorder = new MediaRecorder(stream, { mimeType: pickMimeType() });

    recorder.addEventListener("dataavailable", (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    });

    recorder.addEventListener("stop", async () => {
      stream.getTracks().forEach((track) => track.stop());
      recordBtn.classList.remove("recording");
      recordLabel.textContent = "Gedrückt starten";
      const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      await sendAudio(blob);
    });

    recorder.start();
    recordBtn.classList.add("recording");
    recordLabel.textContent = "Stoppen";
  } catch (error) {
    addMessage("system", `Mikrofon nicht verfügbar: ${error.message}`);
  }
}

function pickMimeType() {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

async function sendText(message) {
  setBusy(true);
  addMessage("user", message);
  const thinkingEl = addMessage("system", "Generiere Antwort...");
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const data = await readJson(res);
    thinkingEl.remove();
    addMessage("assistant", data.response);
    playAudio(data);
  } catch (error) {
    thinkingEl.remove();
    addMessage("system", error.message);
  } finally {
    setBusy(false);
  }
}

async function sendAudio(blob) {
  setBusy(true);
  addMessage("system", "Transkribiere...");
  try {
    const form = new FormData();
    form.append("audio", blob, "recording.webm");
    const res = await fetch("/api/voice", { method: "POST", body: form });
    const data = await readJson(res);
    removeLastSystemTranscribing();
    addMessage("user", data.transcript);
    addMessage("assistant", data.response);
    playAudio(data);
  } catch (error) {
    removeLastSystemTranscribing();
    addMessage("system", error.message);
  } finally {
    setBusy(false);
  }
}

async function readJson(res) {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Request failed with ${res.status}`);
  }
  return data;
}

function playAudio(data) {
  if (!data.audio_base64 || !data.audio_mime) return;
  const audio = new Audio(`data:${data.audio_mime};base64,${data.audio_base64}`);
  audio.play().catch(() => {});
}

function addMessage(role, text) {
  removeEmptyState();
  const el = document.createElement("div");
  el.className = `message ${role}`;
  el.textContent = text;
  messagesEl.append(el);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return el;
}

function showEmptyState() {
  const el = document.createElement("div");
  el.className = "empty-state";
  el.textContent = "Starte mit Sprache oder Text. Alles läuft lokal: Browser, Server, Ollama und macOS-Sprachausgabe.";
  messagesEl.append(el);
}

function removeEmptyState() {
  messagesEl.querySelector(".empty-state")?.remove();
}

function removeLastSystemTranscribing() {
  const items = [...messagesEl.querySelectorAll(".message.system")];
  const last = items.at(-1);
  if (last?.textContent === "Transkribiere...") last.remove();
}

function setBusy(value) {
  busy = value;
  sendBtn.disabled = value;
  recordBtn.disabled = value;
  textInput.disabled = value;
}
