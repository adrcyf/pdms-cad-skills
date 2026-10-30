"""Archive useful results, then plan explicit completed-request cleanup. No Python deletion."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET


def plan_cleanup(root, force=False, session_end=False):
    from bridge_client import Bridge
    root = Path(root).resolve()
    responses = sorted((p for p in root.glob('*.response') if re.fullmatch(r'[a-f0-9]{32}', p.stem)),
                       key=lambda p: p.stat().st_mtime)
    if not responses:
        return None
    archive_path = root.parent / 'history.json'
    archive = json.loads(archive_path.read_text(encoding='utf-8')) if archive_path.exists() else {'summaries': [], 'recent': []}
    summaries = {r['request_id']: r for r in archive['summaries']}
    recent = {r['request_id']: r for r in archive['recent']}
    completed = []
    for path in responses:
        try:
            result = Bridge(root).result(path.stem)
            stamp = path.stat().st_mtime
            result['recorded_unix'] = stamp
            recent[path.stem] = result
            summaries[path.stem] = {'request_id': path.stem, 'session': result.get('session'), 'ok': result.get('ok'),
                'recorded_unix': stamp, 'elapsed_ms': result.get('elapsed_ms'), 'commands_count': len(result.get('results', [])),
                'result_sha256': hashlib.sha256(json.dumps(result, sort_keys=True).encode('utf-8')).hexdigest()}
            completed.append(path)
        except (OSError, ValueError, KeyError):
            continue  # Unknown or damaged records are preserved.
    ordered = sorted(recent.values(), key=lambda r: r['recorded_unix'])
    successes = [r for r in ordered if r.get('ok')][-5:]
    failures = [r for r in ordered if not r.get('ok')][-5:]
    kept = sorted(successes + failures, key=lambda r: r['recorded_unix'])
    # Bounded diagnostic archive. Long-term engineering evidence belongs in project deliverables.
    while len(kept) > 1 and len(json.dumps(kept).encode('utf-8')) > 1024 * 1024:
        kept.pop(0)
    archive = {'summaries': sorted(summaries.values(), key=lambda r: r['recorded_unix'])[-100:], 'recent': kept}
    if session_end:
        archive['recent'] = []
    archive_path.write_text(json.dumps(archive, ensure_ascii=False, indent=2), encoding='utf-8')
    candidates = set()

    def add(path):
        path = Path(path).resolve()
        if path.parent == root and path.is_file():
            candidates.add(str(path))

    # Results have already been archived: remove completed scratch bundles immediately.
    # Pending, ambiguous, user-owned, abnormal and important records remain untouched.
    for response in completed:
        from process_lifecycle import process_alive
        archived_result = recent[response.stem]
        if response.with_suffix('.client.json').exists() and not (archived_result.get('capture_closed') or archived_result.get('console_cleared')) and process_alive(archived_result.get('pid')):
            continue  # A native log might still be open; retain its ownership/recovery evidence.
        add(response)
        add(response.with_suffix('.running'))
        meta_path = response.with_suffix('.client.json')
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding='utf-8'))
                add(meta_path)
                for key in ('log', 'status'):
                    if re.fullmatch(r'[a-f0-9]{32}\.capture\.(log|status)', Path(meta[key]).name):
                        add(meta[key])
                if re.fullmatch(r'[a-f0-9]{32}', meta['token']):
                    add(root / (meta['token'] + '.capture.mac'))
            except (OSError, ValueError, KeyError):
                candidates.discard(str(response))
                candidates.discard(str(response.with_suffix('.running')))
                continue
        running = response.with_suffix('.running')
        if running.exists():
            try:
                for node in ET.parse(running).getroot().findall('command'):
                    match = re.fullmatch(r'\$M /(.+)', node.text or '', re.I)
                    if match and re.fullmatch(r'[a-f0-9]{32}\.recover\.mac', Path(match[1]).name):
                        add(match[1])
                        add(Path(match[1]).with_suffix('.status'))
            except (OSError, ET.ParseError):
                continue
    manifest = root / 'maintenance-plan.json'
    manifest.write_text(json.dumps({'root': str(root), 'archive': str(archive_path), 'files': sorted(candidates)}, indent=2), encoding='utf-8')
    return manifest


def maintain(root, force=False, session_end=False):
    manifest = plan_cleanup(root, force, session_end=session_end)
    if manifest is None:
        return {'ran': False}
    script_root = Path(__file__).parent
    powershell = str(Path(os.environ['WINDIR']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
    approved = Path(root) / 'maintenance-approved.json'
    for script, args in (
        ('inspect-cleanup.ps1', ['-Manifest', str(manifest), '-Approved', str(approved)]),
        ('remove-cleanup.ps1', ['-Approved', str(approved)]),
    ):
        result = subprocess.run([powershell, '-NoProfile', '-File', str(script_root / script)] + args,
                                capture_output=True, timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            return {'ran': True, 'ok': False, 'error': (result.stderr + result.stdout).decode('utf-8', errors='replace')[-2000:]}
    return {'ran': True, 'ok': True, 'archive': str(Path(root).parent / 'history.json')}


if __name__ == '__main__':
    from bridge_client import DEFAULT_ROOT, transport_lock
    with transport_lock(DEFAULT_ROOT):
        if '--apply' in sys.argv:
            result = maintain(DEFAULT_ROOT, force=True)
        else:
            result = {'manifest': str(plan_cleanup(DEFAULT_ROOT, force=True))}
    print(json.dumps(result))
