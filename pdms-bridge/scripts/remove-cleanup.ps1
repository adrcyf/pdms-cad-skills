param([Parameter(Mandatory=$true)][string]$Approved)
$ErrorActionPreference = 'Stop'
$approvedList = Get-Content -LiteralPath $Approved -Raw | ConvertFrom-Json
$removed = 0
$failed = @()
foreach ($file in $approvedList.files) {
    if ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($file.path)) -ne $approvedList.root) { throw 'Path outside inspected runtime' }
    try {
        Remove-Item -LiteralPath $file.path -ErrorAction Stop
        $removed++
    } catch {
        $failed += [PSCustomObject]@{path=$file.path; error=$_.Exception.Message}
    }
}
[PSCustomObject]@{removed=$removed; failed=$failed; skipped=$approvedList.skipped} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $approvedList.root 'maintenance-result.json') -Encoding UTF8
Write-Output ("Removed {0} files; failed {1}." -f $removed,$failed.Count)
if ($failed.Count -gt 0) { exit 1 }
