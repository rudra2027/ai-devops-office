# support-bot (Aria)

Streaming support chat on the shared kit.

- `POST /api/chat` server-sent events: `meta`, `token`, `tool_start`, `tool_end`, `ui`, `done`, `error`
- `POST /api/stt` audio -> text with Gemini 3.5 Flash through OpenRouter (the browser converts recordings to 16 kHz WAV)
- `GET/DELETE /api/conversations[/{id}]` history, private to the signed-in user
- Replies may append `<ui>{...}</ui>`; the frontend renders cards, steps, tables, charts, stats, code, checklists and quick
  replies, and shifts the background with the reply's mood. Text-to-speech uses the browser's voices.
- Tools: order lookup (Supabase `orders` or the local fallback), open a ticket, current time.

```bash
python -m uvicorn app.main:app --port 8000      # from this folder; secrets come from multiagent/.env
python -m pytest tests
```
`_legacy/` holds the previous implementation (OpenAI-compatible proxy, server-side TTS). Delete it when you are happy.
