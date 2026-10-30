# Regenerate the bootstrap for this user and this skill location. No UI, no PDMS launch.
$ErrorActionPreference = 'Stop'
$runtime = Join-Path $env:USERPROFILE '.codex\context\pdms-bridge\runtime'
if ($runtime.Contains("'")) { throw 'USERPROFILE contains an unsupported quote; select and validate another runtime path.' }
$macro = @"
IMPORT 'CJPDMSBridgeV2'
USING NAMESPACE 'CJ.PDMS'
!!cjbridge = object LocalBridge()
!!cjbridgesession = !!cjbridge.Start('$($runtime.Replace('\','/'))')
q var !!cjbridgesession
"@
$bootstrap = Join-Path $PSScriptRoot 'bootstrap.mac'
$encoding = [Text.Encoding]::GetEncoding(936, [Text.EncoderFallback]::ExceptionFallback, [Text.DecoderFallback]::ExceptionFallback)
[IO.File]::WriteAllText($bootstrap, ($macro -replace "`r?`n", "`r`n") + "`r`n", $encoding)
$command = '$m /' + $bootstrap.Replace('\','/')
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'load-command.txt'), $command + "`r`n", (New-Object Text.UTF8Encoding($false)))
Write-Output $command
if ($bootstrap.Contains(' ')) {
    Write-Warning 'This path contains spaces. PDMS macro filename parsing must be validated before using the printed command; do not assume it is portable.'
}
