"""Build a shareable skill bundle; excludes local bootstrap paths, data, caches and private keys."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output')
    args = parser.parse_args()
    base = Path(__file__).resolve().parents[2]
    folders = [base / name for name in ('pdms-bridge', 'pdms-cad-modeling', 'pdms-piping')]
    excluded = {'CJPDMSBridge.dll', 'bootstrap.mac', 'load-command.txt', 'live_test.py', 'cad_live_test.py', 'package-manifest.json'}
    files = []
    for folder in folders:
        text = (folder / 'SKILL.md').read_text(encoding='utf-8')
        assert text.startswith('---\n') and re.search(r'^name: [a-z0-9-]+$', text, re.M)
        assert re.search(r'^description: .+', text, re.M)
        for target in re.findall(r'\]\((references/[^)]+)\)', text):
            assert (folder / target).is_file(), target
        for path in folder.rglob('*'):
            if not path.is_file() or '__pycache__' in path.parts or path.name in excluded:
                continue
            if path.suffix not in ('.py', '.ps1', '.cmd', '.dll', '.cs', '.md', '.yaml'):
                continue
            files.append(path)
    records = [{'path': str(path.relative_to(base)).replace('\\','/'), 'bytes': path.stat().st_size,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in sorted(files)]
    manifest = {'package': 'pdms-cad-piping-skills', 'version': '0.4.0', 'date': datetime.datetime.now().strftime('%Y-%m-%d'),
                'pdms_compatibility': '12.1 SP4 / des.exe 12.1.4.0 / x86 .NET 2 adapter',
                'python': '3.11+; normally supplied by Codex desktop',
                'cad': 'Live COM: registered AutoCAD on Windows. Optional file fallback: ezdxf; previews: matplotlib.',
                'entry': 'pdms-bridge/pdms.cmd (prepare, then manually run the printed PDMS macro once)',
                'files': records}
    path = folders[0] / 'package-manifest.json'
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise SystemExit('Refusing to overwrite an existing share bundle: '+str(output))
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for record in records:
            archive.write(base / record['path'], record['path'])
        archive.write(path, 'pdms-bridge/package-manifest.json')
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        for record in records:
            assert hashlib.sha256(archive.read(record['path'])).hexdigest() == record['sha256']
        assert 'pdms-bridge/scripts/CJPDMSBridgeV2.dll' in archive.namelist()
    print(json.dumps({'bundle': str(output), 'files': len(records)+1, 'bytes': output.stat().st_size}))


if __name__ == '__main__':
    main()
