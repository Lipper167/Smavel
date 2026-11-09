# Smavel Multi-AI (Class 12, SDG 11)

## Setup (Windows)
1. Extract this ZIP into a new folder.
2. Copy `.env.example` and rename the copy to `.env`. Paste private API keys into `.env`. Do not upload/share `.env`.
3. Open Command Prompt in this folder (File Explorer address bar -> `cmd`).
4. Run `python -m pip install -r requirements.txt`.
5. Run `python -m uvicorn main:app --reload` (or just double-click `run.bat`).
6. Visit `http://127.0.0.1:8000` (not the HTML file directly).

### Providers
- Groq: https://console.groq.com/keys (free developer limits; model availability can change)
- OpenRouter: https://openrouter.ai/settings/keys (`openrouter/free` route; subject to free availability and limits)
- Gemini: https://aistudio.google.com/api-keys (free tier may be busy or restricted)

At least one key is required. For genuine multi-AI consensus, configure 2 or 3. Providers are queried concurrently. Only successful responses are averaged; missing responses are not assigned zero. Each criterion is averaged across responding models, then the original category weights are applied. Report prose comes from the first successful provider, while highlights and tips combine unique responses.

### Test
`/health` shows configured providers (not live availability). `/api/models` shows configured model names. The site calls `/api/analyze`. No AI provider is guaranteed to work free forever. Do not expose keys in browser JavaScript or commit `.env`.

### Important
AI opinions are not live verified advisories. Visa readiness checker is a document checklist, not approval probability.

### Troubleshooting
- The coloured chips under the form show which keys were detected. Each result card shows why a provider failed (e.g. "Invalid API key", "Rate limit / quota reached").
- Restart uvicorn after editing `.env`. Do not put quotes or spaces around keys.
- Models auto-fall back if one is retired (Groq, Gemini and OpenRouter).

### VS Code
1. File > Open Folder... and choose this `smavel` folder (or open `Smavel.code-workspace`).
2. Install the recommended Python extension when prompted.
3. Copy `.env.example` to `.env` and paste your key(s).
4. Terminal > Run Task > "Install requirements", then press **F5** (debug) or run the task "Run Smavel".
5. Open http://127.0.0.1:8000
