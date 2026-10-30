param([string]$PdmsRoot = 'C:\AVEVA\Plant\PDMS12.1.SP4')
$ErrorActionPreference = 'Stop'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v2.0.50727\csc.exe'
$destination = Join-Path $PSScriptRoot 'CJPDMSBridgeV2.dll'
& $compiler /nologo /target:library /platform:x86 "/out:$destination" "/reference:$PdmsRoot\PMLNet.dll" "/reference:$PdmsRoot\Aveva.Pdms.Utilities.dll" "/reference:$PdmsRoot\Aveva.ApplicationFramework.dll" /reference:System.Windows.Forms.dll /reference:System.Xml.dll (Join-Path $PSScriptRoot 'CJPDMSBridge.cs')
if ($LASTEXITCODE -ne 0) { throw 'Bridge compilation failed' }
Get-Item -LiteralPath $destination | Select-Object FullName,Length,LastWriteTime
