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
let chunks = [];
let busy = false;
let config = {
  stt_provider: "browser",
  stt_language: "de",
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
    const stt = config.stt_provider === "browser" && browserSpeechSupported() ? "Live-STT im Browser" : "MLX-Whisper";
    statusEl.textContent = `${ollama} · Modell: ${model} · ${stt}`;
  } catch (error) {
    statusEl.textContent = "Server erreichbar, Konfiguration konnte nicht geladen werden";
  }
}

function browserSpeechSupported() {
  return Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
}

function startBrowserSpeechRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechRecognition();
  recognition.lang = normalizeSpeechLanguage(config.stt_language);
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  let finalText = "";
  let interimText = "";
  liveTranscriptEl = addMessage("system", "Hoere zu...");
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
    const message = event.error ? `Browser-STT Fehler: ${event.error}` : "Browser-STT Fehler";
    cleanupBrowserSpeech();
    liveTranscriptEl?.remove();
    addMessage("system", `${message}. Fallback: Audioaufnahme verwenden.`);
    await startRecording();
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
