# ESpeech API


---

## Quickstart

```bash
# 1) Python 3.10+ recommended
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # (use your lockfile if you have one)

# 2) Put voice folders into ./voices (see “Voices layout” below)

# 3) Run the API
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 4) Open the demo
# http://localhost:8000
```

### Useful env vars (optional)

* `ESPEECH_VOICES_DIR` (default: `voices/`)
* `ESPEECH_OUTPUT_DIR` (default: `outputs/`)
* `ESPEECH_API_BASE` (default: `/api`)
* `ESPEECH_MODEL_REPO`, `ESPEECH_MODEL_FILE`, `ESPEECH_VOCAB_FILE`
* `ESPEECH_VOCODER_REPO` (default: `charactr/vocos-mel-24khz`)
* `ESPEECH_MAX_WORKERS` (default: `1`)
* `ESPEECH_KEEP_MODEL` (`1` keeps model resident on GPU/CPU)

---

## Voices layout

```
voices/
  MyVoice/
    ref_text.txt           # reference transcript (ru)
    reference.wav          # any of: .wav .flac .mp3 .ogg .m4a
    meta.json              # optional: {"name": "Readable Display Name"}
```

---

## API Overview (base path: `/api`)

* `GET /voices` → list available voices.
* `GET /voices/{voice_id}/reference-audio` → stream the reference clip.
* `POST /synthesize` → enqueue a job, returns `job_id`.
* `GET /jobs/{job_id}` → poll job status; when `done`, includes `audio_url`.
* `GET /jobs/{job_id}/audio` (and `HEAD`) → download/probe the audio file.
* `GET /jobs/{job_id}/events` → Server-Sent Events (status updates).
* `POST /synthesize/stream` → **synchronous** synth; returns audio bytes.

Webhook (optional): pass `callback_url` in the synth request. When the job finishes or fails, the server POSTs:

```json
{
  "job_id": "abc123",
  "status": "done",
  "error": null,
  "filename": "Miki_xxx.mp3",
  "mime_type": "audio/mpeg"
}
```

---

## OpenAPI (JSON)

> This describes the public endpoints above. The live docs are also available at `/docs` when running.

```json
{
  "openapi": "3.0.3",
  "info": { "title": "ESpeech TTS API", "version": "1.2.2" },
  "servers": [{ "url": "/" }],
  "paths": {
    "/api/voices": {
      "get": {
        "summary": "List voices",
        "responses": {
          "200": {
            "description": "OK",
            "content": {
              "application/json": {
                "schema": { "$ref": "#/components/schemas/ListVoicesResponse" }
              }
            }
          }
        }
      }
    },
    "/api/voices/{voice_id}/reference-audio": {
      "get": {
        "summary": "Get reference audio",
        "parameters": [
          { "name": "voice_id", "in": "path", "required": true, "schema": { "type": "string" } }
        ],
        "responses": {
          "200": {
            "description": "Audio",
            "content": {
              "audio/mpeg": {},
              "audio/wav": {},
              "application/octet-stream": {}
            }
          },
          "404": { "description": "Not found" }
        }
      }
    },
    "/api/synthesize": {
      "post": {
        "summary": "Create synthesis job",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": { "schema": { "$ref": "#/components/schemas/SynthesisRequest" } }
          }
        },
        "responses": {
          "200": {
            "description": "Queued",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "job_id": { "type": "string" },
                    "status": { "type": "string", "example": "queued" }
                  },
                  "required": ["job_id", "status"]
                }
              }
            }
          },
          "404": { "description": "Unknown voice" }
        }
      }
    },
    "/api/jobs/{job_id}": {
      "get": {
        "summary": "Get job status",
        "parameters": [
          { "name": "job_id", "in": "path", "required": true, "schema": { "type": "string" } }
        ],
        "responses": {
          "200": {
            "description": "OK",
            "content": {
              "application/json": { "schema": { "$ref": "#/components/schemas/JobStatus" } }
            }
          },
          "404": { "description": "Not found" }
        }
      }
    },
    "/api/jobs/{job_id}/audio": {
      "get": {
        "summary": "Download job audio",
        "parameters": [
          { "name": "job_id", "in": "path", "required": true, "schema": { "type": "string" } }
        ],
        "responses": {
          "200": {
            "description": "Audio file",
            "content": { "audio/mpeg": {}, "audio/wav": {}, "application/octet-stream": {} }
          },
          "409": { "description": "Not completed yet" },
          "410": { "description": "Expired" }
        }
      },
      "head": {
        "summary": "Probe audio existence/expiry",
        "parameters": [
          { "name": "job_id", "in": "path", "required": true, "schema": { "type": "string" } }
        ],
        "responses": {
          "200": { "description": "Available" },
          "409": { "description": "Not completed yet" },
          "410": { "description": "Expired" }
        }
      }
    },
    "/api/jobs/{job_id}/events": {
      "get": {
        "summary": "SSE stream of status updates",
        "parameters": [
          { "name": "job_id", "in": "path", "required": true, "schema": { "type": "string" } }
        ],
        "responses": {
          "200": { "description": "text/event-stream", "content": { "text/event-stream": {} } }
        }
      }
    },
    "/api/synthesize/stream": {
      "post": {
        "summary": "Synchronous synth (streams audio)",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": { "schema": { "$ref": "#/components/schemas/SynthesisRequest" } }
          }
        },
        "responses": {
          "200": { "description": "Audio stream", "content": { "audio/mpeg": {}, "audio/wav": {} } },
          "404": { "description": "Unknown voice" }
        }
      }
    }
  },
  "components": {
    "schemas": {
      "VoiceInfo": {
        "type": "object",
        "properties": {
          "id": { "type": "string" },
          "name": { "type": "string" },
          "ref_text_file": { "type": "string" },
          "ref_audio_file": { "type": "string" }
        },
        "required": ["id", "name", "ref_text_file", "ref_audio_file"]
      },
      "ListVoicesResponse": {
        "type": "object",
        "properties": {
          "voices": { "type": "array", "items": { "$ref": "#/components/schemas/VoiceInfo" } }
        },
        "required": ["voices"]
      },
      "SynthesisRequest": {
        "type": "object",
        "properties": {
          "voice_id": { "type": "string" },
          "text": { "type": "string", "description": "Russian text" },
          "speed": { "type": "number", "minimum": 0.5, "maximum": 2.0, "default": 1.0 },
          "nfe_step": { "type": "integer", "minimum": 8, "maximum": 128, "default": 71 },
          "seed": { "type": "integer", "default": -1, "description": "-1 for random" },
          "format": { "type": "string", "enum": ["wav", "mp3"], "default": "mp3" },
          "callback_url": { "type": "string", "format": "uri", "nullable": true }
        },
        "required": ["voice_id", "text"]
      },
      "JobStatus": {
        "type": "object",
        "properties": {
          "job_id": { "type": "string" },
          "status": { "type": "string", "enum": ["queued", "running", "done", "error"] },
          "error": { "type": "string", "nullable": true },
          "audio_url": { "type": "string", "nullable": true },
          "filename": { "type": "string", "nullable": true },
          "mime_type": { "type": "string", "nullable": true }
        },
        "required": ["job_id", "status"]
      }
    }
  }
}
```

---

## Client examples

### 1) cURL

List voices:

```bash
curl -s http://localhost:8000/api/voices | jq
```

Create a job:

```bash
curl -s -X POST http://localhost:8000/api/synthesize \
  -H 'Content-Type: application/json' \
  -d '{
    "voice_id": "Miki",
    "text": "Привет! Это тест синтеза речи.",
    "format": "mp3",
    "nfe_step": 71,
    "speed": 1.0,
    "seed": -1
  }'
# → {"job_id":"<id>","status":"queued"}
```

Poll and download when ready:

```bash
JOB=<paste_id_here>
curl -s http://localhost:8000/api/jobs/$JOB | jq
curl -fSL http://localhost:8000/api/jobs/$JOB/audio -o output.mp3
```

SSE updates (live status):

```bash
curl -N http://localhost:8000/api/jobs/$JOB/events
```

Synchronous stream (writes audio to file):

```bash
curl -X POST http://localhost:8000/api/synthesize/stream \
  -H 'Content-Type: application/json' \
  -d '{"voice_id":"Miki","text":"Привет!","format":"mp3"}' \
  -o out.mp3
```

### 2) Python (`requests`)

```python
import time, requests

BASE = "http://localhost:8000/api"

# 1) pick a voice
voices = requests.get(f"{BASE}/voices").json()["voices"]
voice_id = voices[0]["id"]

# 2) submit
req = {
    "voice_id": voice_id,
    "text": "Здравствуйте! Это пример синтеза.",
    "format": "mp3",
    "nfe_step": 71,
    "speed": 1.0,
    "seed": -1,
}
job = requests.post(f"{BASE}/synthesize", json=req).json()
job_id = job["job_id"]

# 3) poll
while True:
    st = requests.get(f"{BASE}/jobs/{job_id}").json()
    print(st["status"])
    if st["status"] in ("done", "error"):
        break
    time.sleep(1.5)

# 4) download
if st["status"] == "done" and st.get("audio_url"):
    audio = requests.get(f"http://localhost:8000{st['audio_url']}").content
    with open("result.mp3", "wb") as f:
        f.write(audio)
```

### 3) JavaScript (Node 18+/Browser fetch)

Submit & poll:

```js
const BASE = "http://localhost:8000/api";

async function synth(text, voiceId) {
  const res = await fetch(`${BASE}/synthesize`, {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({
      voice_id: voiceId, text, format: "mp3", nfe_step: 71, speed: 1.0, seed: -1
    })
  });
  const { job_id } = await res.json();

  // poll
  for (;;) {
    const st = await (await fetch(`${BASE}/jobs/${job_id}`)).json();
    if (st.status === "done" && st.audio_url) {
      return `http://localhost:8000${st.audio_url}`;
    }
    if (st.status === "error") throw new Error(st.error || "synthesis failed");
    await new Promise(r => setTimeout(r, 1500));
  }
}

(async () => {
  const voices = await (await fetch(`${BASE}/voices`)).json();
  const voiceId = voices.voices[0].id;
  const url = await synth("Привет, мир!", voiceId);
  console.log("Audio ready at:", url);
})();
```

SSE status (browser):

```js
const ev = new EventSource(`/api/jobs/${jobId}/events`);
ev.addEventListener("status", (e) => {
  const data = JSON.parse(e.data);
  console.log("status:", data.status);
  if (data.status === "done" || data.status === "error") ev.close();
});
```

---

## Notes

* First run may download models/vocoder; subsequent runs are faster.
* Outputs are auto-deleted after inactivity (default TTL: 1h).
* Concurrency is intentionally low by default (`ESPEECH_MAX_WORKERS=1`) to be GPU-friendly. Adjust with care.
