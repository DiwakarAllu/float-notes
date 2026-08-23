$ErrorActionPreference = "Stop"

$OllamaRoot = "D:\MyOllama"
$InstallDir = Join-Path $OllamaRoot "App"
$ModelsDir = Join-Path $OllamaRoot "Models"
$Installer = Join-Path $OllamaRoot "OllamaSetup.exe"

New-Item -ItemType Directory -Force -Path $InstallDir, $ModelsDir | Out-Null
[Environment]::SetEnvironmentVariable("OLLAMA_INSTALL_DIR", $InstallDir, "User")
[Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $ModelsDir, "User")
[Environment]::SetEnvironmentVariable("OLLAMA_HOST", "http://127.0.0.1:11434", "User")

Write-Host "OLLAMA_INSTALL_DIR = $InstallDir"
Write-Host "OLLAMA_MODELS      = $ModelsDir"
Write-Host "OLLAMA_HOST        = http://127.0.0.1:11434"

if (-not (Test-Path $Installer)) {
    throw "Ollama installer not found at $Installer"
}

Write-Host "Starting the Ollama installer..."
$process = Start-Process -FilePath $Installer -Wait -PassThru
if ($process.ExitCode -ne 0) {
    throw "Ollama installer exited with code $($process.ExitCode)"
}

Write-Host "Installation finished. Open a new terminal, then run: ollama pull llama3.2:1b"