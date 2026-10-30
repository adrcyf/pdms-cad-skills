param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
try {
 $target=(Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
 if ([IO.Path]::GetExtension($target) -notin @('.dwg','.dxf')) { throw 'Expected DWG or DXF' }
 $app=$null; $created=$false
 $key=[Microsoft.Win32.Registry]::ClassesRoot.OpenSubKey('AutoCAD.Application\CurVer')
 $ids=@(); if($key){$ids+=[string]$key.GetValue('');$key.Close()};$ids+=@('AutoCAD.Application.25','AutoCAD.Application.24.3')
 foreach($id in ($ids | Select-Object -Unique)){try{$app=[Runtime.InteropServices.Marshal]::GetActiveObject($id);break}catch{}}
 if($null -eq $app){
  if(Get-Process -Name acad -ErrorAction SilentlyContinue){throw 'AutoCAD process exists but COM is not ready; wait and retry status, do not launch another instance'}
  $type=$null
  foreach($id in ($ids | Select-Object -Unique)){$type=[type]::GetTypeFromProgID($id);if($type){break}}
  if(-not $type){throw 'No registered AutoCAD COM application'}
  $app=[Activator]::CreateInstance($type);$created=$true
  $app.Visible=$false
 }
 if(-not $app.GetAcadState().IsQuiescent){throw 'AutoCAD busy; no activation or input attempted'}
 $doc=$null
 foreach($item in $app.Documents){if([string]::Equals($item.FullName,$target,[StringComparison]::OrdinalIgnoreCase)){$doc=$item;break}}
 $opened=$false
 if($null -eq $doc){$doc=$app.Documents.Open($target,$true);$opened=$true}
 $deadline=[DateTime]::UtcNow.AddSeconds(30)
 while(-not [string]::Equals([string]$doc.FullName,$target,[StringComparison]::OrdinalIgnoreCase)){
  if([DateTime]::UtcNow -ge $deadline){throw 'Drawing opened but full path not ready; verify status before reading'}
  Start-Sleep -Milliseconds 250
  foreach($item in $app.Documents){if([string]::Equals($item.FullName,$target,[StringComparison]::OrdinalIgnoreCase)){$doc=$item;break}}
 }
 [ordered]@{ok=$true;document=$doc.FullName;readonly=$doc.ReadOnly;application_created=$created;document_opened=$opened;visible=$app.Visible;version=$app.Version;note='Native COM only; no Activate, focus, keyboard, mouse, Save or Quit. New application stays hidden.'}|ConvertTo-Json -Compress
}catch{[ordered]@{ok=$false;error=$_.Exception.Message}|ConvertTo-Json -Compress;exit 1}
