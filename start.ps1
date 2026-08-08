# Starts the Armenian voice assistant: FastAPI backend (:8191) + Vite dev server (:5178).
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$ollamaUp = $false
try {
    Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 2 | Out-Null
    $ollamaUp = $true
} catch {
    $ollamaUp = $false
}
if (-not $ollamaUp) {
    Write-Host "Ollama doesn't seem to be running. Starting 'ollama serve' in the background..."
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 2
}

$venvPython = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
$backend = Start-Process -FilePath $venvPython `
    -ArgumentList "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", "8191", "--reload" `
    -PassThru -NoNewWindow

try {
    Set-Location -Path (Join-Path $PSScriptRoot "frontend")
    if (-not (Test-Path "node_modules")) {
        npm install
    }
    npm run dev
} finally {
    Write-Host "Stopping backend (PID $($backend.Id))..."
    Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
}
