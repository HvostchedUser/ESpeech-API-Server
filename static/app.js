// static/app.js
const API_BASE = "/api";

const elVoices = document.getElementById("voices");
const elVoicesEmpty = document.getElementById("voices-empty");
const elText = document.getElementById("text");
const elSpeed = document.getElementById("speed");
const elSpeedValue = document.getElementById("speedValue");
const elNfe = document.getElementById("nfe");
const elSeed = document.getElementById("seed");
const elFormat = document.getElementById("format");
const elSynthBtn = document.getElementById("synthesizeBtn");
const elStatus = document.getElementById("status");
const elPlayer = document.getElementById("player");
const elDownload = document.getElementById("downloadLink");

let voices = [];
let selectedVoiceId = null;

elSpeed.addEventListener("input", () => {
  elSpeedValue.textContent = parseFloat(elSpeed.value).toFixed(2);
});

function status(msg, cls = "") {
  elStatus.innerHTML = `<span class="${cls}">${msg}</span>`;
}

async function fetchVoices() {
  const res = await fetch(`${API_BASE}/voices`);
  if (!res.ok) throw new Error("Failed to fetch voices.");
  const data = await res.json();
  return data.voices || [];
}

function renderVoices(items) {
  elVoices.innerHTML = "";
  if (!items.length) {
    elVoicesEmpty.classList.remove("hidden");
    return;
  }
  elVoicesEmpty.classList.add("hidden");

  items.forEach((v, idx) => {
    const card = document.createElement("div");
    card.className = "voice-card";

    const head = document.createElement("div");
    head.className = "voice-head";

    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "voice";
    radio.value = v.id;
    if (idx === 0) {
      radio.checked = true;
      selectedVoiceId = v.id;
    }
    radio.addEventListener("change", () => {
      selectedVoiceId = v.id;
    });

    const name = document.createElement("div");
    name.className = "voice-name";
    name.textContent = v.name;

    head.appendChild(radio);
    head.appendChild(name);
    card.appendChild(head);

    const audio = document.createElement("audio");
    audio.controls = true;
    audio.preload = "none";
    audio.src = `${API_BASE}/voices/${encodeURIComponent(v.id)}/reference-audio`;
    card.appendChild(audio);

    const meta = document.createElement("div");
    meta.className = "info";
    meta.innerHTML = `<small>${v.ref_text_file} • ${v.ref_audio_file}</small>`;
    card.appendChild(meta);

    elVoices.appendChild(card);
  });
}

async function startSynthesis() {
  if (!selectedVoiceId) {
    status("Please select a voice.", "warn");
    return;
  }
  const text = elText.value.trim();
  if (!text) {
    status("Please enter some text to synthesize.", "warn");
    return;
  }

  elSynthBtn.disabled = true;
  status("Submitting job… This may take a while on the first run.", "info");
  elPlayer.removeAttribute("src");
  elPlayer.load();
  elDownload.classList.add("hidden");

  try {
    const res = await fetch(`${API_BASE}/synthesize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        voice_id: selectedVoiceId,
        text,
        speed: parseFloat(elSpeed.value),
        nfe_step: parseInt(elNfe.value, 10),
        seed: parseInt(elSeed.value, 10),
        format: elFormat.value,
      }),
    });
    if (!res.ok) throw new Error(await res.text());
    const { job_id } = await res.json();
    await pollJob(job_id);
  } catch (err) {
    console.error(err);
    status("Failed to start synthesis: " + err, "err");
  } finally {
    elSynthBtn.disabled = false;
  }
}

async function pollJob(jobId) {
  status("Queued… waiting for a free slot.", "info");
  let tries = 0;
  while (true) {
    const res = await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}`);
    const data = await res.json();

    if (data.status === "running") {
      status("Synthesizing… this can take tens of seconds or minutes.", "info");
    } else if (data.status === "done") {
      if (!data.audio_url) {
        status("Done, but the output expired. Please synthesize again.", "warn");
        break;
      }
      status("Done ✔", "ok");
      const audioUrl = `${data.audio_url}?t=${Date.now()}`;
      elPlayer.src = audioUrl;
      elPlayer.load();
      elDownload.href = audioUrl;
      elDownload.download = data.filename || "audio";
      elDownload.classList.remove("hidden");
      break;
    } else if (data.status === "error") {
      status("Error: " + (data.error || "Unknown error"), "err");
      break;
    } else {
      status("Queued…", "info");
    }

    await new Promise((r) => setTimeout(r, Math.min(1500 + tries * 250, 5000)));
    tries += 1;
  }
}

// In case user clicks download and the file expired server-side:
elDownload.addEventListener("click", async (e) => {
  if (!elDownload.href) return;
  try {
    const res = await fetch(elDownload.href, { method: "HEAD" });
    if (res.status === 410) {
      e.preventDefault();
      status("This audio has expired. Please synthesize again.", "warn");
    }
  } catch (_) {}
});

document.getElementById("synthesizeBtn").addEventListener("click", startSynthesis);

(async function init() {
  try {
    voices = await fetchVoices();
    renderVoices(voices);
  } catch (err) {
    console.error(err);
    status("Failed to load voices: " + err, "err");
  }
})();
