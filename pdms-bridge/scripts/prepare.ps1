param([string]$PdmsRoot, [switch]$InspectOnly, [switch]$NoPause, [switch]$AutoLoad, [switch]$Mcp, [switch]$ManualOnly, [switch]$NoMcp)
$ErrorActionPreference='Stop'
if (-not $PdmsRoot) {
    $roots=@(Get-Process des -ErrorAction SilentlyContinue | ForEach-Object { if ($_.Path) {Split-Path -Parent $_.Path} } | Select-Object -Unique)
    if ($roots.Count -eq 1) { $PdmsRoot=$roots[0] }
    elseif ($roots.Count -gt 1) { throw 'More than one PDMS installation is running; specify the intended PdmsRoot.' }
    elseif (Test-Path -LiteralPath 'C:\AVEVA\Plant\PDMS12.1.SP4\des.exe') { $PdmsRoot='C:\AVEVA\Plant\PDMS12.1.SP4' }
    else { throw 'Open the intended PDMS first so its installation can be detected. No UI automation is used.' }
}
$version=(Get-Item -LiteralPath (Join-Path $PdmsRoot 'des.exe')).VersionInfo.FileVersion
if ($version -ne '12.1.4.0') { throw "Bundled adapter is verified for PDMS 12.1 SP4 (12.1.4.0), found $version. Adapt before installing." }
$python=Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python=(Get-Command python.exe -ErrorAction Stop).Source }
if ($InspectOnly) {
    [pscustomobject]@{pdms_root=$PdmsRoot; pdms_version=$version; python=$python; adapter=(Join-Path $PSScriptRoot 'CJPDMSBridgeV2.dll'); changes=$false} | ConvertTo-Json
    exit 0
}
$loadAtLogin = -not $ManualOnly
& (Join-Path $PSScriptRoot 'deploy.ps1') -PdmsRoot $PdmsRoot -AutoLoad:$loadAtLogin -ManualOnly:$ManualOnly
# Register only this MCP server; deployment above controls this adapter autoload.
if ($NoMcp) { & $python (Join-Path $PSScriptRoot 'configure_mcp.py') --disable }
else { & $python (Join-Path $PSScriptRoot 'configure_mcp.py') --enable }
if ($LASTEXITCODE -ne 0) { throw 'MCP client registration failed; inspect before retrying.' }
Write-Host 'Prepared. Execute the printed one-time macro in PDMS if this session is not yet connected.'
Write-Host 'No desktop shortcut, app launch, mouse input or focus change is required.'
Write-Host 'Default: one bridge connection and reusable CAD cache for the software session; closing Design releases the session.'
if (-not $NoPause) { Read-Host 'Press Enter to close' | Out-Null }
