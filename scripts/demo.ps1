# Local portfolio server. This process does not load demo restaurants and does not edit .env.
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Python = "d:\project1\final-project\.python\python.exe"
Set-Location $Root
$env:PYTHONUTF8 = "1"
$env:DEMO_DATASET = "false"
$env:ENABLE_LLM_AGENT = "false"
$env:ENABLE_LANGGRAPH = "true"
$env:ENABLE_BM25 = "true"
$env:ENABLE_WEB_SEARCH = "true"
$env:ENABLE_AGENT_WORKFLOW = "true"
Write-Host "API on http://127.0.0.1:8767"
Write-Host "Dataset: data/processed/restaurants.json"
Write-Host "Retrieval: BM25. Web search: Bing HTML. Multi-agent workflow: on. MCP stdio: started with the API."
Write-Host "In another terminal: cd frontend; npm run dev"
& $Python -c "import sys; sys.path[:0]=[r'd:\project1\malaysia-food-copilot', r'd:\project1\malaysia-food-copilot\src']; import uvicorn; uvicorn.run('app:app', host='127.0.0.1', port=8767)"
