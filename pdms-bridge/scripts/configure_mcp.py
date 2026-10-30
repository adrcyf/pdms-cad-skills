"""Register only this local stdio server; preserve all unrelated Codex settings."""
from pathlib import Path
import argparse
import datetime
import json
import shutil
import sys
import tomllib
import re


def set_server_enabled(original, executable, server, enabled=False):
    parsed = tomllib.loads(original)
    existing = parsed.get('mcp_servers', {}).get('pdms_bridge')
    definition = {'command': executable, 'args': [str(server)], 'enabled': enabled}
    if existing is not None:
        if existing.get('command') != executable or existing.get('args') != [str(server)]:
            raise ValueError('pdms_bridge points elsewhere; preserve it and inspect manually')
        if existing.get('enabled', True) == enabled:
            return original
        match = re.search(r'^\[mcp_servers\.pdms_bridge\][^\n]*(?:\n|$)', original, re.M)
        if not match:
            raise ValueError('Nonstandard MCP table format; inspect manually')
        following = re.search(r'^\[', original[match.end():], re.M)
        end = match.end() + following.start() if following else len(original)
        body = original[match.end():end]
        value = 'enabled = ' + ('true' if enabled else 'false')
        if re.search(r'^enabled\s*=', body, re.M):
            body = re.sub(r'^enabled\s*=.*$', value, body, flags=re.M)
        else:
            body = value + '\n' + body
        updated = original[:match.end()] + body + original[end:]
    else:
        updated = original + '\n\n[mcp_servers.pdms_bridge]\ncommand = ' + json.dumps(executable) + '\nargs = ' + json.dumps([str(server)]) + '\nenabled = ' + ('true' if enabled else 'false') + '\n'
    assert tomllib.loads(updated)['mcp_servers']['pdms_bridge']['enabled'] == enabled
    return updated


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--enable', action='store_true')
    group.add_argument('--disable', action='store_true')
    args = parser.parse_args()
    root = Path.home() / '.codex'
    config = root / 'config.toml'
    original = config.read_text(encoding='utf-8-sig') if config.exists() else ''
    server = Path(__file__).with_name('mcp_server.py').resolve()
    enabled = not args.disable
    updated = set_server_enabled(original, sys.executable, server, enabled=enabled)
    if updated == original:
        print('MCP state already matches: ' + ('enabled, software-session lifetime' if enabled else 'disabled; Python CLI stays available'))
        return
    backups = root / 'context/pdms-bridge/backups'
    backups.mkdir(parents=True, exist_ok=True)
    if config.exists():
        shutil.copy2(config, backups / ('codex-config-' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.toml'))
    config.write_text(updated, encoding='utf-8')
    print('Saved pdms_bridge state: ' + ('enabled, software-session lifetime' if enabled else 'disabled; use on-demand Python CLI'))


if __name__ == '__main__':
    main()
