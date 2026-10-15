# ==============================================================================
# Veratum Installer for Windows PowerShell
# https://github.com/yadavmandeep/Veratum
# ==============================================================================
param(
    [string]$TargetDir = (Get-Location).Path,
    [string]$Ide = ""
)

Write-Host @"
 __     __               _                 
 \ \   / /__ _ __  __ _ | |_ _  _ _ __ ___ 
  \ \ / / _ \ '__|/ _` || __| || | '_ ` _ \
   \ V /  __/ |  | (_| || |_| || | | | | | |
    \_/ \___|_|   \__,_| \__|\_,_|_| |_| |_|
"@ -ForegroundColor Cyan

Write-Host "Universal AI Engineering Harness, Skill & MCP Runtime" -ForegroundColor White
Write-Host "https://github.com/yadavmandeep/Veratum`n" -ForegroundColor DarkCyan

# 1. Detect Python 3.8+
Write-Host "[1/4] Checking Python environment..." -ForegroundColor White
$pythonCmd = $null
foreach ($cmd in @("python", "py", "python3")) {
    $exists = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($exists) {
        $verCheck = & $cmd -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $pythonCmd = $cmd
            break
        }
    }
}

if (-not $pythonCmd) {
    Write-Host "X Python 3.8+ is required but not found in PATH." -ForegroundColor Red
    Write-Host "Please install Python from https://www.python.org and re-run."
    exit 1
}

$pyVer = & $pythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
Write-Host "  [OK] Found Python $pyVer ($pythonCmd)" -ForegroundColor Green

# 2. Check Node / npx
Write-Host "`n[2/4] Checking Node.js runtime..." -ForegroundColor White
$npxExists = Get-Command "npx" -ErrorAction SilentlyContinue
if ($npxExists) {
    Write-Host "  [OK] Found npx & Node.js" -ForegroundColor Green
    $useNpx = $true
} else {
    Write-Host "  [!] npx not found. Running Python engine directly." -ForegroundColor Yellow
    $useNpx = $false
}

# 3. Install
Write-Host "`n[3/4] Installing Veratum into: $TargetDir" -ForegroundColor White
if ($useNpx) {
    if ($Ide) {
        & npx veratum init --ide $Ide --dir $TargetDir
    } else {
        & npx veratum init --dir $TargetDir
    }
} else {
    & $pythonCmd "$TargetDir\.veratum\engine\veratum_cli.py" init --root $TargetDir
}

# 4. Diagnostics
Write-Host "`n[4/4] Verifying installation health..." -ForegroundColor White
$enginePath = Join-Path $TargetDir ".veratum\engine\veratum_cli.py"
if (Test-Path $enginePath) {
    & $pythonCmd $enginePath doctor --root $TargetDir
} else {
    Write-Host "  [OK] Skill ready." -ForegroundColor Green
}

Write-Host "`nVeratum setup completed successfully!" -ForegroundColor Green
Write-Host "Quickstart: Tell your agent 'Use Veratum to work on this repo.'" -ForegroundColor Cyan
