# AI Self-Healing Web Scraper — Phase 1

## Implemented in this version
- FastAPI health endpoint, SQLite persistence and website registration
- Playwright Chromium page capture
- Page title, requested/final URL, HTTP status and load-time metadata
- HTML cleaning and bounded preview
- Unique screenshot folder per capture, served under `/artifacts`
- Persistent capture history in SQLite
- Dashboard action to capture a registered website and inspect results
- Basic public-host validation, including blocking private/reserved IP resolutions

## Not implemented yet
Groq onboarding/config generation, product extraction, ground-truth validation, change detection, AI healing, human review, scheduling and reports are future phases. Dashboard placeholders do not mean these features are implemented.

## Backend (PowerShell)
```powershell
cd backend
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
Copy-Item .env.example .env
uvicorn app.main:app --reload --port 8000
```

## Frontend (another PowerShell terminal)
```powershell
cd frontend
npm install
$env:NODE_OPTIONS="--use-system-ca"
npm run dev
```
Open `http://localhost:5173`. API docs: `http://127.0.0.1:8000/docs`.

## Phase 1 API
- `GET /api/health`
- `POST /api/capture` with `{"url":"https://books.toscrape.com","site_id":1}` (`site_id` optional)
- `GET /api/capture/history`
- `GET /api/capture/history?site_id=1`
- `GET /api/capture/{capture_id}`
- Screenshot URL is returned as `screenshot_url` and served under `/artifacts/`.

Capture is for public websites you are authorized to access. It does not bypass login, CAPTCHA, paywalls or access controls. Keep `.env` files and API keys private.
