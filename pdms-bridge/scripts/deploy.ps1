param([string]$PdmsRoot = 'C:\AVEVA\Plant\PDMS12.1.SP4', [switch]$AutoLoad, [switch]$ManualOnly)
$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'CJPDMSBridgeV2.dll'
$target = Join-Path $PdmsRoot 'CJPDMSBridgeV2.dll'
if (Test-Path -LiteralPath $target) {
    if ((Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath $target).Hash) {
        throw 'A different adapter already exists. Do not overwrite a loaded DLL; stop and version the assembly.'
    }
} else {
    Copy-Item -LiteralPath $source -Destination $target -ErrorAction Stop
}
$runtime = Join-Path $env:USERPROFILE '.codex\context\pdms-bridge\runtime'
New-Item -ItemType Directory -Path $runtime -ErrorAction Stop -Force | Out-Null
$macro = @"
IMPORT 'CJPDMSBridgeV2'
USING NAMESPACE 'CJ.PDMS'
!!cjbridge = object LocalBridge()
!!cjbridgesession = !!cjbridge.Start('$($runtime.Replace('\','/'))')
q var !!cjbridgesession
"@
$bootstrap = Join-Path $PSScriptRoot 'bootstrap.mac'
[IO.File]::WriteAllText($bootstrap, ($macro -replace "`r?`n", "`r`n") + "`r`n", [Text.Encoding]::GetEncoding(936))
Get-Item -LiteralPath $target,$bootstrap | Select-Object FullName,Length
& (Join-Path $PSScriptRoot 'show-load-command.ps1')
if ($AutoLoad) {
    $config = Join-Path $PdmsRoot 'DesignAddins.xml'
    $document = New-Object System.Xml.XmlDocument
    $document.PreserveWhitespace = $true
    $document.Load($config)
    $already = @($document.ArrayOfString.string) -contains 'CJPDMSBridgeV2'
    if (-not $already) {
        $backupDir = Join-Path $env:USERPROFILE '.codex\context\pdms-bridge\backups'
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
        $backup = Join-Path $backupDir ('DesignAddins_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff') + '.xml')
        Copy-Item -LiteralPath $config -Destination $backup -ErrorAction Stop
        $entry = $document.CreateElement('string')
        $entry.InnerText = 'CJPDMSBridgeV2'
        [void]$document.DocumentElement.AppendChild($entry)
        $document.Save($config)
        Write-Output "Registered startup addin. Backup: $backup"
    }
}
if ($ManualOnly) {
    $config = Join-Path $PdmsRoot 'DesignAddins.xml'
    $document = New-Object System.Xml.XmlDocument
    $document.PreserveWhitespace = $true
    $document.Load($config)
    $entries = @($document.SelectNodes('/ArrayOfString/string') | Where-Object { $_.InnerText -eq 'CJPDMSBridgeV2' })
    if ($entries.Count -gt 0) {
        $backupDir = Join-Path $env:USERPROFILE '.codex\context\pdms-bridge\backups'
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
        $backup = Join-Path $backupDir ('DesignAddins_manual_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff') + '.xml')
        Copy-Item -LiteralPath $config -Destination $backup -ErrorAction Stop
        foreach ($entry in $entries) { [void]$entry.ParentNode.RemoveChild($entry) }
        $document.Save($config)
        Write-Output 'Bridge autoload removed; load the one-time macro only when modeling is needed.'
    }
}
