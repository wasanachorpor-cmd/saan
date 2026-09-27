# S.A.A.N.

Smart Accessibility Assistance Network. A reader uploads a photo of a page, hears it read aloud, and can send a paragraph to a volunteer when the words sound wrong. Volunteers compare the photo with the extracted text, correct it, and earn impact points.

## Run locally

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Or double-click `start.bat`. Then open http://127.0.0.1:8000

Demo accounts (password `demo1234`):

- Reader: `reader@saan.local`
- Volunteer: `volunteer@saan.local`

A welcome page is already in the reader library, with two paragraphs waiting in mission control. Set `SAAN_SEED_DEMO=false` to skip them. Copy `.env.example` to `.env` and change `SAAN_SECRET_KEY` before exposing the server.

## Reading a page

OCR tries engines in this order:

1. **Gemini**, only when `SAAN_GEMINI_API_KEY` is set. The photo is sent to Google.
2. **Tesseract**, after an OpenCV cleanup (grayscale, upscale, denoise, adaptive threshold). Install [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) and the Thai plus English language packs. The app looks for `C:\Program Files\Tesseract-OCR\tesseract.exe`, or use `SAAN_TESSERACT_CMD`.

Photos stay on this machine unless a Gemini key is configured.

## Accessibility

The interface is designed against WCAG 2.2 AAA: keyboard access, visible focus, skip link, named controls, live status, a high-contrast theme, four text sizes, browser zoom, reduced motion, and language marks on each paragraph. High contrast removes the glass blur. This is a design commitment, not a third-party certificate. Details are on `/accessibility`.

Speech uses the browser Web Speech API. Voices depend on the operating system. Download the transcript if the browser has no speech.

## Tests

```bat
pytest
```
