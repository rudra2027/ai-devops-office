"""Speech to text with Gemini 3.5 Flash through OpenRouter. The browser records; text-to-speech stays in the browser."""

import asyncio
import base64
import time

import httpx
from fastapi import HTTPException

from agentkit.llm import estimate_cost
from agentkit.settings import get_settings
from agentkit.telemetry import record_call

PROMPT = "Transcribe this audio exactly as spoken. Output only the transcript text, nothing else. If there is no speech, output an empty string."
FORMATS = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav", "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/ogg": "ogg", "audio/flac": "flac", "audio/aac": "aac", "audio/mp4": "m4a", "audio/webm": "webm"}


async def transcribe(audio: bytes, content_type: str) -> str:
    s = get_settings()
    if s.llm_mode == "stub":
        await asyncio.sleep(s.stub_latency_ms / 1000)
        return "(stub transcript)"
    if not s.openrouter_api_key:
        raise HTTPException(503, "Speech-to-text is not configured")
    fmt = FORMATS.get((content_type or "").split(";")[0].strip().lower(), "wav")
    body = {
        "model": s.stt_model, "temperature": 0, "max_tokens": 400,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "input_audio", "input_audio": {"data": base64.b64encode(audio).decode(), "format": fmt}},
        ]}],
    }
    t0 = time.perf_counter()
    status, err, usage, text = "ok", None, {}, ""
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{s.openrouter_base_url}/chat/completions", json=body,
                             headers={"Authorization": f"Bearer {s.openrouter_api_key}", "X-Title": "Agent Office / stt"})
        j = r.json()
        if r.status_code != 200:
            raise HTTPException(502, f"Transcription failed: {(j.get('error') or {}).get('message', r.status_code)}")
        text = (j["choices"][0]["message"].get("content") or "").strip()
        usage = j.get("usage") or {}
    except HTTPException as exc:
        status, err = "error", str(exc.detail)
        raise
    except httpx.HTTPError as exc:
        status, err = "error", type(exc).__name__
        raise HTTPException(502, "Transcription service unreachable")
    finally:
        it, ot = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        record_call({"agent": "support", "model": s.stt_model, "status": status, "error": err, "latency_ms": int((time.perf_counter() - t0) * 1000),
                     "input_tokens": it, "output_tokens": ot, "cost_usd": float(usage.get("cost") or estimate_cost(s.stt_model, it, ot)), "meta": {"kind": "stt"}})
    return text
