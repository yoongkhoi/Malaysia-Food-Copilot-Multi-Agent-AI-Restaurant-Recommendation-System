# Malaysia Food Copilot frontend

Vue 3 interface for the FastAPI app. The browser sends one sentence and shows the cards returned by the API. Region, cuisine, budget, and halal rules stay in Python.

## Run

From `malaysia-food-copilot/frontend`, with the portable Node on PATH:

```powershell
$env:PATH = "d:\project1\malaysia-food-copilot\.node-src\node-v22.21.0-win-x64;" + $env:PATH
npm install
npm run dev
```

The dev server is http://127.0.0.1:5173 . Vite proxies `/api` and `/health` to http://127.0.0.1:8767 .

Start the API with `scripts/demo.ps1` from the project root. That process loads the 5,797 canonical restaurants, BM25, LangGraph, and Bing search. It does not load a demo dataset and it does not call the LLM.

`VITE_API_BASE_URL` stays empty in development. Set it only when the built site is served from another origin. Do not put database URLs or API keys in Vite variables.

## Check

```powershell
npm test
npm run build
```

`npm test` runs Vitest against the query builder and API client. `npm run build` typechecks and creates `dist/`.

## Pages

| Route | What it does |
|---|---|
| `/` | Explore. One text box and an Old Klang Road or Kuala Lumpur choice. Calls `POST /api/discover`. |
| `/copilot` | Conversation. Calls `POST /api/chat` with a 60 second timeout. |
| `/status` | API health, retrieval, LangGraph, web search, record counts, and memory configuration. Database quota is shown as unavailable when the API cannot read it. |
| `/preferences`, `/evidence` | Redirect to `/`. The old screens are not in the navigation. |

Restaurant cards show the name, cuisine, a map link, and a photo only when a confirmed photo URL exists. A missing price is left blank.
