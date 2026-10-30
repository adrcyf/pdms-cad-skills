param([string]$RequestBase64, [switch]$Session)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
function Invoke-CadRead([object]$request) {
$selection = $null
try {
    $progids = @()
    $current = [Microsoft.Win32.Registry]::ClassesRoot.OpenSubKey('AutoCAD.Application\CurVer')
    if ($null -ne $current) { $progids += [string]$current.GetValue(''); $current.Close() }
    $progids += @('AutoCAD.Application.25','AutoCAD.Application.25.0','AutoCAD.Application.24.3','AutoCAD.Application.24.2')
    $app = $null
    foreach ($progid in ($progids | Select-Object -Unique)) {
        try { $app = [Runtime.InteropServices.Marshal]::GetActiveObject($progid); break } catch {}
    }
    if ($null -eq $app) { throw 'No running AutoCAD COM session. No application was launched or activated.' }
    if (-not $app.GetAcadState().IsQuiescent) { throw 'AutoCAD is busy with another command; no drawing read or GUI fallback was attempted.' }
    $doc = $app.ActiveDocument
    if ($request.expected_path) {
        $target=[IO.Path]::GetFullPath($request.expected_path)
        $doc=$null
        foreach ($candidate in $app.Documents) {
            if ([string]::Equals($candidate.FullName,$target,[StringComparison]::OrdinalIgnoreCase)) { $doc=$candidate; break }
        }
        if ($null -eq $doc) { throw ('Expected drawing is not open: ' + $target) }
    }
    $context = [ordered]@{connected=$true; mode='active_COM_readonly'; document=$doc.FullName;
        version=$app.Version; saved=$doc.Saved; readonly=$doc.ReadOnly;
        insunits=$doc.GetVariable('INSUNITS'); modelspace_count=$doc.ModelSpace.Count;
        note='Live active document, including unsaved state. No activation, interactive selection, console input or geometry writes.'}
    if ($request.action -eq 'status') { $context | ConvertTo-Json -Depth 6 -Compress; return }
    $entities = @(); $matched = 0
    $limit = if ($request.limit) {[int]$request.limit} else {20}
    $offset = if ($request.offset) {[int]$request.offset} else {0}
    if ($limit -lt 1 -or $limit -gt 200 -or $offset -lt 0) { throw 'Invalid offset or limit' }
    if ($request.handles) {
        $sourceEntities = @($request.handles | ForEach-Object { $doc.HandleToObject($_) })
    } else {
        # Native database filter, not an interactive/pickfirst selection; never Highlight.
        $selection = $doc.SelectionSets.Add('CJB_READ_' + [Guid]::NewGuid().ToString('N'))
        $codes = [int16[]]@(67)
        $values = [object[]]@(0)
        if ($request.types) { $codes=[int16[]]@(0,67); $values=[object[]]@(($request.types -join ','),0) }
        $selection.Select(5,[Type]::Missing,[Type]::Missing,$codes,$values)
        $sourceEntities = $selection
    }
    foreach ($entity in $sourceEntities) {
        $native = [string]$entity.ObjectName
        $kind = switch -Regex ($native) {
            'Dimension$' {'DIMENSION'; break}
            'BlockReference$' {'INSERT'; break}
            'Polyline$' {'LWPOLYLINE'; break}
            default {$native.Replace('AcDb','').ToUpperInvariant()}
        }
        if ($request.types -and $kind -notin $request.types) { continue }
        if ($request.handles -and $entity.Handle -notin $request.handles) { continue }
        $row = [ordered]@{type=$kind; native_type=$native; handle=$entity.Handle; layer=$entity.Layer}
        $properties = switch ($kind) {
            'LINE' {@{StartPoint='start'; EndPoint='end'; Length='length'}}
            'CIRCLE' {@{Center='center'; Radius='radius'; Diameter='diameter'; Normal='normal'}}
            'ARC' {@{Center='center'; Radius='radius'; StartPoint='start'; EndPoint='end'; StartAngle='start_angle_radians'; EndAngle='end_angle_radians'}}
            'DIMENSION' {@{Measurement='measurement'; TextOverride='text_override'; StyleName='dimstyle'; UnitsFormat='units_format'; LinearScaleFactor='linear_scale_factor'}}
            'TEXT' {@{TextString='text'; InsertionPoint='insert'; Rotation='rotation_radians'; Height='height'}}
            'MTEXT' {@{TextString='raw_text'; InsertionPoint='insert'; Height='height'}}
            'INSERT' {@{Name='name'; EffectiveName='effective_name'; InsertionPoint='insert'; Rotation='rotation_radians'; XScaleFactor='xscale'; YScaleFactor='yscale'; ZScaleFactor='zscale'}}
            'LWPOLYLINE' {@{Coordinates='vertices_ocs_flat'; Elevation='elevation'; Normal='normal'; Length='length'; Closed='closed'}}
            default {@{}}
        }
        foreach ($name in $properties.Keys) {
            try { $row[$properties[$name]] = $entity.$name } catch {}
        }
        if ($kind -eq 'DIMENSION') { $row['measurement_note']='Native Measurement is separate from TextOverride; angular dimensions and scale factors need interpretation.' }
        if ($kind -eq 'INSERT') { $row['note']='Block insert and scale only; no destructive Explode is used. Nested geometry needs a coordinate transform.' }
        if ($request.text_contains) {
            $text = [string]$row['text'] + [string]$row['raw_text'] + [string]$row['text_override']
            if ($text.IndexOf([string]$request.text_contains,[StringComparison]::OrdinalIgnoreCase) -lt 0) { continue }
        }
        if ($matched -ge $offset -and $entities.Count -lt $limit) { $entities += [pscustomobject]$row }
        $matched++
    }
    $context['matched']=$matched; $context['returned']=$entities.Count; $context['offset']=$offset
    $context['more']=($matched -gt ($offset+$entities.Count)); $context['entities']=$entities
    $context | ConvertTo-Json -Depth 12 -Compress
} catch {
    [ordered]@{ok=$false; error=$_.Exception.Message} | ConvertTo-Json -Compress
} finally {
    if ($null -ne $selection) { try { $selection.Delete() } catch {} }
}
}
if ($Session) {
    while ($null -ne ($line=[Console]::ReadLine())) {
        $request=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($line)) | ConvertFrom-Json
        Invoke-CadRead $request
    }
} else {
    $request=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($RequestBase64)) | ConvertFrom-Json
    Invoke-CadRead $request
}
