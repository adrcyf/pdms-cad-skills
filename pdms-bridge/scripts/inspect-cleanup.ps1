param([Parameter(Mandatory=$true)][string]$Manifest, [Parameter(Mandatory=$true)][string]$Approved)
$ErrorActionPreference = 'Stop'
$plan = Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json
$root = [IO.Path]::GetFullPath($plan.root).TrimEnd('\')
$accepted = @()
$skipped = @()
foreach ($path in $plan.files) {
    $absolute = [IO.Path]::GetFullPath($path)
    if ([IO.Path]::GetDirectoryName($absolute) -ne $root) { throw "Unexpected path: $absolute" }
    if (-not (Test-Path -LiteralPath $absolute -PathType Leaf)) { continue }
    $item = Get-Item -LiteralPath $absolute -Force
    $bad = [IO.FileAttributes]::Hidden -bor [IO.FileAttributes]::ReadOnly -bor [IO.FileAttributes]::ReparsePoint -bor [IO.FileAttributes]::System
    if (($item.Attributes -band $bad) -ne 0) { $skipped += $absolute; continue }
    $accepted += [PSCustomObject]@{path=$absolute; bytes=$item.Length; attributes=[string]$item.Attributes}
}
[PSCustomObject]@{root=$root; files=$accepted; skipped=$skipped} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $Approved -Encoding UTF8
Write-Output ("Inspected {0} explicit files; skipped {1}." -f $accepted.Count,$skipped.Count)
