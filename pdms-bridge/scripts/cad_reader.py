"""Read saved DWG/DXF without GUI input. DWG is exported by Core Console on a copy."""
import argparse
from collections import Counter
import functools
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import ezdxf
from ezdxf import bbox as dxf_bbox

CACHE = Path.home() / '.codex/context/pdms-bridge/cad-cache'


class CadError(RuntimeError):
    pass


def find_core_console(explicit=None):
    candidates = [explicit, os.environ.get('AUTOCAD_CORE_CONSOLE')]
    if os.name == 'nt':
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, r'SOFTWARE\Autodesk\AutoCAD') as top:
                    for i in range(winreg.QueryInfoKey(top)[0]):
                        version = winreg.EnumKey(top, i)
                        with winreg.OpenKey(top, version) as branch:
                            for j in range(winreg.QueryInfoKey(branch)[0]):
                                try:
                                    with winreg.OpenKey(branch, winreg.EnumKey(branch, j)) as product:
                                        folder = winreg.QueryValueEx(product, 'AcadLocation')[0]
                                        candidates.append(str(Path(folder) / 'accoreconsole.exe'))
                                except OSError:
                                    pass
            except OSError:
                pass
    for base in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)')):
        if base:
            candidates += [str(p) for p in Path(base).glob('Autodesk/AutoCAD */accoreconsole.exe')]
    # Verified local installation hint; not a requirement on another machine.
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and Path(candidate).name.lower() == 'accoreconsole.exe':
            return Path(candidate).resolve()
    raise CadError('AutoCAD Core Console not found. Supply core_console or use a verified DXF export.')


def saved_dxf(source, core_console=None):
    source = Path(source).resolve(strict=True)
    if source.suffix.lower() == '.dxf':
        return source, {'mode': 'saved_dxf', 'original_unchanged': True}
    if source.suffix.lower() != '.dwg':
        raise CadError('Only saved DWG and DXF are supported by this reader')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    key = hashlib.sha256((str(source) + digest).encode('utf-8')).hexdigest()[:24]
    folder = CACHE / key
    output = folder / 'drawing.dxf'
    if output.exists() and (folder / 'source.json').exists():
        metadata = json.loads((folder / 'source.json').read_text(encoding='utf-8'))
        if metadata.get('sha256') == digest:
            metadata['cache_hit'] = True
            return output, metadata
    core = find_core_console(core_console)
    folder.mkdir(parents=True, exist_ok=True)
    copy = folder / 'input.dwg'
    shutil.copyfile(source, copy)
    script = '\n'.join(['(setvar "FILEDIA" 0)', '(setvar "CMDDIA" 0)', '(setvar "CMDECHO" 0)',
                        '(command "_.DXFOUT" "' + output.as_posix() + '" "16")',
                        '(command "_.QUIT" "_N")', ''])
    script_path = folder / 'export.scr'
    script_path.write_text(script, encoding='utf-8')
    started = time.monotonic()
    try:
        result = subprocess.run([str(core), '/i', str(copy), '/s', str(script_path), '/l', 'en-US'],
                                cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=90, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired as exc:
        raise CadError('Owned Core Console conversion timed out; no GUI fallback was attempted') from exc
    (folder / 'console.log').write_bytes(result.stdout)
    unchanged = hashlib.sha256(source.read_bytes()).hexdigest() == digest
    if not unchanged or not output.exists() or output.stat().st_size == 0:
        raise CadError('DWG conversion did not produce a validated DXF or source changed during the read')
    # The source is never saved. QUIT may report cancelled in console output; a valid DXF is required.
    ezdxf.readfile(output)
    metadata = {'mode': 'core_console_copy', 'source': str(source), 'sha256': digest,
                'original_unchanged': unchanged, 'core_console': str(core),
                'conversion_seconds': round(time.monotonic() - started, 3), 'cache_hit': False}
    (folder / 'source.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    return output, metadata


def vector(value):
    return [float(v) for v in value]


def polyline_length(points, bulges, closed):
    total = 0.0
    for i in range(len(points) if closed else max(0, len(points) - 1)):
        a, b = points[i], points[(i + 1) % len(points)]
        chord = math.dist(a, b)
        bulge = bulges[i]
        total += chord if abs(bulge) < 1e-12 else chord * (1 + bulge * bulge) / (4 * abs(bulge)) * abs(4 * math.atan(bulge))
    return total


class CadReader:
    def __init__(self, path, core_console=None):
        self.source = Path(path).resolve(strict=True)
        self.dxf, self.conversion = saved_dxf(self.source, core_console)
        self.doc = ezdxf.readfile(self.dxf)
        self.model = self.doc.modelspace()
        self.warnings = []

    def summary(self):
        return {'source': str(self.source), 'dxf': str(self.dxf), 'mode': self.conversion,
                'saved_file_only': True, 'dxf_version': self.doc.dxfversion,
                'insunits': self.doc.header.get('$INSUNITS', 0), 'measurement_system': self.doc.header.get('$MEASUREMENT'),
                'units_note': 'INSUNITS=4 is millimetres; validate a known dimension before treating geometry as 1:1.',
                'modelspace_types': dict(Counter(e.dxftype() for e in self.model)),
                'layers': [layer.dxf.name for layer in self.doc.layers],
                'paper_layouts': [layout.name for layout in self.doc.layouts if layout.name != 'Model']}

    def walk(self, include_blocks=True, layout='Model'):
        def visit(entity, source_handle, ancestry, depth):
            yield entity, source_handle, ancestry
            if include_blocks and entity.dxftype() == 'INSERT':
                if depth >= 12:
                    self.warnings.append('Nested block depth limit: ' + source_handle)
                    return
                for attribute in entity.attribs:
                    yield attribute, source_handle, ancestry + [entity.dxf.name]
                try:
                    for child in entity.virtual_entities():
                        yield from visit(child, source_handle, ancestry + [entity.dxf.name], depth + 1)
                except (ValueError, ezdxf.DXFError) as exc:
                    self.warnings.append('Block not fully expanded: ' + source_handle + ': ' + str(exc))
        space = self.doc.layouts.get(layout)
        for entity in space:
            yield from visit(entity, entity.dxf.handle or '', [], 0)

    def entity_record(self, entity, source_handle, ancestry):
        kind = entity.dxftype()
        data = {'type': kind, 'handle': entity.dxf.get('handle'), 'source_handle': source_handle,
                'layer': entity.dxf.get('layer', '0'), 'virtual': bool(ancestry), 'block_path': ancestry,
                'coordinate_system': 'WCS for geometric points; DXF definition points explicitly labelled'}
        if kind == 'LINE':
            data.update(start=vector(entity.dxf.start), end=vector(entity.dxf.end), length=entity.dxf.start.distance(entity.dxf.end))
        elif kind in ('CIRCLE', 'ARC'):
            data.update(center=vector(entity.ocs().to_wcs(entity.dxf.center)), radius=float(entity.dxf.radius),
                        diameter=float(entity.dxf.radius * 2), extrusion=vector(entity.dxf.extrusion))
            if kind == 'ARC':
                data.update(start_angle=entity.dxf.start_angle, end_angle=entity.dxf.end_angle,
                            start=vector(entity.start_point), end=vector(entity.end_point))
        elif kind == 'LWPOLYLINE':
            points = [vector(v) for v in entity.vertices_in_wcs()]
            bulges = [float(v[0]) for v in entity.get_points('b')]
            data.update(vertices=points, bulges=bulges, closed=entity.closed,
                        length=polyline_length(points, bulges, entity.closed))
        elif kind in ('TEXT', 'ATTRIB', 'ATTDEF'):
            data.update(text=entity.dxf.text, insert=vector(entity.ocs().to_wcs(entity.dxf.insert)),
                        rotation=entity.dxf.get('rotation', 0), height=entity.dxf.height)
            if kind != 'TEXT':
                data['tag'] = entity.dxf.tag
        elif kind == 'MTEXT':
            data.update(text=entity.plain_text(), raw_text=entity.text, insert=vector(entity.dxf.insert))
        elif kind == 'DIMENSION':
            measurement = entity.get_measurement()
            if hasattr(measurement, 'x'):
                measurement = vector(measurement)
            data.update(dimension_type=int(entity.dxf.dimtype) & 7,
                        geometry_measurement=measurement, stored_measurement=entity.dxf.get('actual_measurement'),
                        text_override=entity.dxf.get('text', ''), dimstyle=entity.dxf.dimstyle,
                        measurement_units='degrees' if (int(entity.dxf.dimtype) & 7) in (2, 5) else 'drawing_units')
            data['definition_points_dxf'] = {name: vector(entity.dxf.get(name)) for name in
                ('defpoint', 'defpoint2', 'defpoint3', 'defpoint4', 'defpoint5') if entity.dxf.hasattr(name)}
            style = self.doc.dimstyles.get(entity.dxf.dimstyle)
            data['style'] = {name: style.dxf.get(name) for name in ('dimlfac', 'dimscale', 'dimdec', 'dimrnd', 'dimpost')}
            override = entity.override()
            data['effective_style'] = {name: override.get(name, default) for name, default in
                (('dimlfac', 1.0), ('dimscale', 1.0), ('dimdec', 2), ('dimrnd', 0.0), ('dimpost', ''))}
            data['override_note'] = 'Geometry, stored measurement and displayed override are separate; block scale and DIMLFAC must be checked.'
        elif kind == 'INSERT':
            data.update(name=entity.dxf.name, insert=vector(entity.dxf.insert), rotation=entity.dxf.rotation,
                        scale=[entity.dxf.xscale, entity.dxf.yscale, entity.dxf.zscale])
        elif kind == 'ELLIPSE':
            data.update(center=vector(entity.dxf.center), major_axis=vector(entity.dxf.major_axis), ratio=entity.dxf.ratio,
                        start_param=entity.dxf.start_param, end_param=entity.dxf.end_param)
        elif kind == 'SPLINE':
            data.update(degree=entity.dxf.degree, control_points=[vector(v) for v in entity.control_points],
                        fit_points=[vector(v) for v in entity.fit_points], knots=list(entity.knots), weights=list(entity.weights))
        else:
            data['note'] = 'Type retained; detailed extraction not implemented. Do not infer missing geometry.'
        return data

    def query(self, types=None, text_contains=None, layers=None, handles=None, bbox=None,
              include_blocks=True, layout='Model', offset=0, limit=50):
        if not 1 <= limit <= 200 or offset < 0:
            raise CadError('limit must be 1..200; offset must be nonnegative')
        if bbox is not None and (len(bbox) != 4 or bbox[0] > bbox[2] or bbox[1] > bbox[3]):
            raise CadError('bbox must be [xmin,ymin,xmax,ymax]')
        types = {value.upper() for value in types} if types else None
        matches, selected = 0, []
        self.warnings = []
        for entity, source_handle, ancestry in self.walk(include_blocks, layout):
            if types and entity.dxftype() not in types:
                continue
            if layers and entity.dxf.layer not in layers:
                continue
            if handles and source_handle not in handles and entity.dxf.get('handle') not in handles:
                continue
            if bbox:
                bounds = dxf_bbox.extents([entity], fast=True)
                if not bounds.has_data or bounds.extmax.x < bbox[0] or bounds.extmin.x > bbox[2] or bounds.extmax.y < bbox[1] or bounds.extmin.y > bbox[3]:
                    continue
            try:
                record = self.entity_record(entity, source_handle, ancestry)
            except (ValueError, TypeError, ezdxf.DXFError, AttributeError) as exc:
                self.warnings.append(source_handle + ': ' + str(exc))
                continue
            if text_contains and text_contains.casefold() not in (record.get('text', '') + record.get('text_override', '')).casefold():
                continue
            if offset <= matches < offset + limit:
                selected.append(record)
            matches += 1
        return {'source': str(self.source), 'saved_file_only': True, 'insunits': self.doc.header.get('$INSUNITS', 0),
                'matched': matches, 'offset': offset, 'returned': len(selected), 'more': matches > offset + len(selected),
                'entities': selected, 'warnings': list(dict.fromkeys(self.warnings))[:30]}

    def preview(self, bbox=None, layout='Model'):
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from ezdxf.addons.drawing import RenderContext, Frontend
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
        if bbox is not None and (len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]):
            raise CadError('Preview bbox must be [xmin,ymin,xmax,ymax] with positive area')
        key = hashlib.sha256((str(self.source) + str(self.source.stat().st_mtime_ns) + str(bbox) + layout).encode()).hexdigest()[:24]
        directory = CACHE / 'previews'
        directory.mkdir(parents=True, exist_ok=True)
        output = directory / (key + '.png')
        if not output.exists():
            figure = plt.figure(figsize=(9, 9))
            axis = figure.add_axes([0, 0, 1, 1])
            try:
                Frontend(RenderContext(self.doc), MatplotlibBackend(axis)).draw_layout(self.doc.layouts.get(layout), finalize=True)
                if bbox is not None:
                    axis.set_xlim(bbox[0], bbox[2])
                    axis.set_ylim(bbox[1], bbox[3])
                axis.set_aspect('equal')
                figure.savefig(output, dpi=160, facecolor=axis.get_facecolor())
            finally:
                plt.close(figure)
        return {'path': str(output), 'source': str(self.source), 'bbox': bbox,
                'note': 'Offline rendering, not a native screenshot; fonts/proxy entities may differ. Measure from entities, not pixels.'}


@functools.lru_cache(maxsize=3)
def _cached_reader(path, mtime, size, core_console):
    return CadReader(path, core_console)


def reader_for(path, core_console=None):
    source = Path(path).resolve(strict=True)
    stat = source.stat()
    return _cached_reader(str(source), stat.st_mtime_ns, stat.st_size, core_console)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('path')
    parser.add_argument('--core-console')
    parser.add_argument('--types', nargs='+')
    parser.add_argument('--text')
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--offset', type=int, default=0)
    args = parser.parse_args()
    try:
        reader = reader_for(args.path, args.core_console)
        output = reader.query(types=args.types, text_contains=args.text, limit=args.limit, offset=args.offset) if args.types or args.text else reader.summary()
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
