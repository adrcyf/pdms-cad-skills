"""Python entry to native AutoCAD COM reads; never launches, activates or sends keys."""
import argparse
import base64
import json
import math
import os
from pathlib import Path
import subprocess
import sys

_session_process = None


def read_active(action='status', **arguments):
    request = {'action': action, **arguments}
    payload = base64.b64encode(json.dumps(request).encode('utf-8')).decode('ascii')
    exe = Path(os.environ['WINDIR'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    command = [str(exe), '-NoProfile', '-File', str(Path(__file__).with_name('read-active-cad.ps1'))]
    if os.environ.get('CJ_CAD_SESSION') == '1':
        global _session_process
        if _session_process is None or _session_process.poll() is not None:
            _session_process = subprocess.Popen(command + ['-Session'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        _session_process.stdin.write((payload+'\n').encode('ascii'))
        _session_process.stdin.flush()
        line = _session_process.stdout.readline()
        if not line:
            raise RuntimeError('Native CAD session read channel disconnected')
        result = json.loads(line.decode('utf-8-sig'))
        result['native_session_pid'] = _session_process.pid
    else:
        run = subprocess.run(command + ['-RequestBase64', payload], capture_output=True, timeout=60,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if run.returncode:
            raise RuntimeError(run.stderr.decode('utf-8', errors='replace')[-1500:])
        result = json.loads(run.stdout.decode('utf-8-sig'))
    for entity in result.get('entities', []):
        if entity.get('type') == 'DIMENSION' and 'Angular' in entity.get('native_type', ''):
            entity['measurement_native_units'] = 'radians'
            if isinstance(entity.get('measurement'), (int, float)):
                entity['measurement_degrees'] = math.degrees(entity['measurement'])
        elif entity.get('type') == 'DIMENSION':
            entity['measurement_native_units'] = 'drawing_units'
    return result


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['status', 'query'], default='status', nargs='?')
    parser.add_argument('--expected-path')
    parser.add_argument('--types', nargs='+')
    parser.add_argument('--limit', type=int, default=20)
    args = parser.parse_args()
    print(json.dumps(read_active(**vars(args)), ensure_ascii=False, indent=2))
