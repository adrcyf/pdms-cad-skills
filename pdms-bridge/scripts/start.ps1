param(
    [string]$PdmsRoot = 'C:\AVEVA\Plant\PDMS12.1.SP4',
    [switch]$StatusOnly,
    [switch]$NoPause
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = (Get-Command python.exe -ErrorAction Stop).Source
}
if ($StatusOnly) {
    & $python (Join-Path $PSScriptRoot 'bridge_client.py') status
    exit $LASTEXITCODE
}
& (Join-Path $PSScriptRoot 'deploy.ps1') -PdmsRoot $PdmsRoot -AutoLoad
$running = @(Get-Process des -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq (Join-Path $PdmsRoot 'des.exe') })
if ($running.Count -eq 0) {
    # Open the normal login UI. No passwords are stored or passed on the command line.
    $vendorBat = Join-Path $PdmsRoot 'pdms.bat'
    Start-Process -FilePath $env:ComSpec -ArgumentList @('/c', ('""{0}" Design"' -f $vendorBat)) -WorkingDirectory $PdmsRoot -WindowStyle Hidden
    Write-Host 'PDMS started. Log in normally; the bridge loads with Design.'
} else {
    Write-Host 'Existing PDMS retained. Startup registration takes effect on the next normal Design startup.'
}
Write-Host 'Checking the bridge (up to 15 seconds)...'
$connected = $false
for ($i=0; $i -lt 15; $i++) {
    $state = (& $python (Join-Path $PSScriptRoot 'bridge_client.py') status | ConvertFrom-Json)
    if ($state.connected) { $connected=$true; $state | ConvertTo-Json; break }
    Start-Sleep -Seconds 1
}
if (-not $connected) {
    Write-Host 'Not connected yet. An already-open session needs this one-time command:'
    & (Join-Path $PSScriptRoot 'show-load-command.ps1')
    Write-Host 'Alternatively, save your work and restart Design normally; the registered addin will load.'
}
Write-Host 'MCP stdio is launched by the configured MCP client; no separate server window is required.'
if (-not $NoPause) { Read-Host 'Press Enter to close' | Out-Null }
