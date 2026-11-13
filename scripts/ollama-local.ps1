$ErrorActionPreference = 'Stop'

$ollama = Join-Path $env:LOCALAPPDATA 'Programs/Ollama/ollama.exe'
if (-not (Test-Path -LiteralPath $ollama)) {
    $ollama = (Get-Command ollama.exe -ErrorAction Stop).Source
}

$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_NUM_PARALLEL = '3'
$env:OLLAMA_CONTEXT_LENGTH = '4096'
$env:OLLAMA_MAX_LOADED_MODELS = '1'
$env:OLLAMA_VULKAN = '1'
$env:OLLAMA_IGPU_ENABLE = '1'
$env:OLLAMA_NO_CLOUD = '1'

& $ollama serve
exit $LASTEXITCODE
