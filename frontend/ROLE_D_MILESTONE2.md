# Person D – Milestone 2 Frontend

Implemented in this frontend:
- Ticket drawer AI Resolution panel: four RAG trace steps/timings, retrieved article relevance, generated answer, sources, confidence status, human-review banner, Regenerate and Copy Reply.
- Knowledge Base page with article list, category filter, search, and article viewer.
- RAG metrics page with article count, generated responses, average confidence, review percentage, and average response time.
- Loading, empty, and error feedback for the new pages.
- Mock data mode for frontend-first development.

## Mock mode
`USE_MOCKS` is currently set to `true` in `src/App.jsx`. This lets the UI run without FastAPI. Set it to `false` after the backend endpoints are available.

## Run
```bash
cd frontend
npm install
npm run dev
```

Open the localhost URL printed by Vite.
