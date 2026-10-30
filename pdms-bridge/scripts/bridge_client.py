"""Local file transport. No UI automation and no automatic command retries."""
import argparse
import datetime as dt
import json
import os
import re
import contextlib
from pathlib import Path
import time
import sys
import uuid
import xml.etree.ElementTree as ET

DEFAULT_ROOT = Path.home() / '.codex/context/pdms-bridge/runtime'


class BridgeError(RuntimeError):
    pass


def validate_commands(commands):
    if not isinstance(commands, list) or not 1 <= len(commands) <= 2000:
        raise BridgeError('Expected 1..2000 native command lines')
    if any(not isinstance(c, str) or not c.strip() or '\n' in c or '\r' in c or '\0' in c for c in commands):
        raise BridgeError('Each item must contain one nonempty native command line')


def parse_capture(text, token, count):
    outputs = [''] * count
    active = None
    chunks = []
    marker = re.compile(r'^CJBR_' + re.escape(token) + r'_(\d+)$')
    for line in text.splitlines():
        match = marker.fullmatch(line.strip())
        if match:
            if active is not None and active < count:
                outputs[active] = '\n'.join(chunks).strip()
            active, chunks = int(match[1]), []
        elif active is not None:
            chunks.append(line)
    if active is not None and active < count:
        outputs[active] = '\n'.join(chunks).strip()
    return outputs


def build_capture_macro(commands, token, log, status, clear_console=True):
    if any("'" in path or '\n' in path for path in (log, status)):
        raise BridgeError('Unsupported capture path')
    should_clear = clear_console
    def clear_console_lines(indent=''):
        if not should_clear:
            return []
        result = []
        for channel in ('REQUESTS', 'COMMANDS'):
            result += [indent + 'alpha ' + channel.lower() + ' clear', indent + 'handle any',
                       indent + "  !cjstatus.append('CLEAR_" + channel + "_FAILED')",
                       indent + 'elsehandle none',
                       indent + "  !cjstatus.append('CLEAR_" + channel + "_OK')", indent + 'endhandle']
        result += [indent + "!cjfile.writefile('OVERWRITE', !cjstatus)"]
        return result

    # Disable macro/debug trace; use the log grammar verified on PDMS 12.1 SP4.
    lines = ['$R0', "!cjstatus = object ARRAY()", "!cjfile = object FILE('" + status + "')",
             'alpha log /' + log + ' over', 'handle any',
             "  !cjstatus.append('CAPTURE_START_FAILED')", '  !cjstatus.append(!!error.text)',
             "  !cjfile.writefile('OVERWRITE', !cjstatus)", '  return', 'endhandle']
    for index, command in enumerate(commands):
        lines += ['$P CJBR_' + token + '_' + str(index), command, 'handle any',
                  "  !cjstatus.append('ERROR:" + str(index) + "')", '  !cjstatus.append(!!error.text)',
                  "  !cjfile.writefile('OVERWRITE', !cjstatus)", '  alpha log end']
        lines += ["  !cjstatus.append('CAPTURE_CLOSED')", "  !cjfile.writefile('OVERWRITE', !cjstatus)"]
        lines += clear_console_lines('  ') + ['  return', 'endhandle']
    lines += ["!cjstatus.append('OK')", "!cjfile.writefile('OVERWRITE', !cjstatus)", 'alpha log end']
    lines += ["!cjstatus.append('CAPTURE_CLOSED')", "!cjfile.writefile('OVERWRITE', !cjstatus)"]
    lines += clear_console_lines()
    return '\n'.join(lines) + '\n'


def read_pdms_text(path):
    data = Path(path).read_bytes()
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError:
        return data.decode('gbk', errors='replace')


def owns_capture(root, log, session):
    root, log = Path(root).resolve(), Path(log).resolve()
    if log.parent != root or not re.fullmatch(r'[0-9a-f]{32}\.capture\.log', log.name):
        return False
    for path in root.glob('*.running'):
        try:
            request = ET.parse(path).getroot()
            if request.get('session') != session:
                continue
            for command in request.findall('command'):
                match = re.fullmatch(r'ALPHA LOG /(.+) OVER(?: REQUESTS)?', command.text or '', re.I)
                if match and Path(match[1]).resolve() == log:
                    return True
            meta = path.with_suffix('.client.json')
            if meta.exists() and Path(json.loads(meta.read_text(encoding='utf-8'))['log']).resolve() == log:
                return True
        except (OSError, ValueError, KeyError, ET.ParseError):
            continue
    return False


@contextlib.contextmanager
def transport_lock(root):
    import msvcrt
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'client.lock').open('a+b') as lock:
        if lock.tell() == 0:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise BridgeError('Another bridge client owns the output capture; wait for its result') from exc
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


class Bridge:
    def __init__(self, root=DEFAULT_ROOT):
        self.root = Path(root)

    def status(self):
        try:
            session = json.loads((self.root / 'session.json').read_text(encoding='utf-8-sig'))
            stamp = dt.datetime.fromisoformat(session['utc'].replace('Z', '+00:00'))
            age = (dt.datetime.now(dt.timezone.utc) - stamp).total_seconds()
            session['heartbeat_age_s'] = round(age, 3)
            from process_lifecycle import process_alive
            session['process_running'] = process_alive(session.get('pid'))
            session['connected'] = session['process_running'] and 0 <= age < 8 and not session.get('stopped', False)
            session['unresolved_requests'] = self.unresolved(session.get('session'))
            session['ready'] = session['connected'] and not session['unresolved_requests']
            return session
        except (OSError, ValueError, KeyError) as exc:
            return {'connected': False, 'detail': str(exc)}

    def unresolved(self, session):
        pending = set()
        for pattern in ('*.request', '*.running'):
            for path in self.root.glob(pattern):
                if path.with_suffix('.response').exists():
                    continue
                try:
                    if ET.parse(path).getroot().get('session') == session:
                        pending.add(path.stem)
                except (OSError, ET.ParseError):
                    pending.add(path.stem)
        return sorted(pending)

    def stop(self):
        state = self.status()
        if not state.get('connected'):
            return {'ok': True, 'already_stopped': True, 'process_running': state.get('process_running', False)}
        if state.get('unresolved_requests'):
            raise BridgeError('Cannot stop while requests are unresolved; inspect their results first')
        result = self._execute_raw(['!!cjbridge.Stop()'], 5, state['session'])
        if result.get('ok'):
            from maintenance import maintain
            result['maintenance'] = maintain(self.root)
        return result

    def execute(self, commands, timeout=30, expected_session=None, clear_console=True):
        validate_commands(commands)
        if len(commands) > 999:
            raise BridgeError('Captured batches support at most 999 command lines')
        if any(re.match(r'^\s*ALP(?:HA)?\s+LOG\b', command, re.I) for command in commands):
            raise BridgeError('ALPHA LOG is managed by the bridge; do not nest a log capture')
        with transport_lock(self.root):
            state = self.status()
            if state.get('unresolved_requests'):
                raise BridgeError('Session has unresolved requests; do not enqueue another batch: ' +
                                  ','.join(state['unresolved_requests']))
            if not state.get('connected'):
                raise BridgeError('PDMS bridge is not connected; do not attempt window automation')
            recovery = None
            for attempt in range(2):
                token = uuid.uuid4().hex
                log = self.root / (token + '.capture.log')
                status = self.root / (token + '.capture.status')
                macro = self.root / (token + '.capture.mac')
                text = build_capture_macro(commands, token, log.as_posix(), status.as_posix(), clear_console=clear_console)
                macro.write_bytes(text.replace('\n', '\r\n').encode('gbk'))
                metadata = {'token': token, 'commands': commands, 'log': str(log), 'status': str(status)}
                response = self._execute_raw(['$M /' + macro.as_posix()], timeout, expected_session, metadata)
                status_lines = response.get('capture_status', [])
                match = re.search(r'\(61,275\).*?log file\s*-\s*(.+)', '\n'.join(status_lines), re.I)
                if attempt == 0 and status_lines[:1] == ['CAPTURE_START_FAILED'] and not response['results'] and match:
                    owned = match.group(1).strip()
                    if owns_capture(self.root, owned, state['session']):
                        recovery = self._close_owned_log(owned, state['session'])
                        if recovery['ok']:
                            # No user command ran: capture failed before the command loop.
                            continue
                if recovery is not None:
                    response['recovery'] = recovery
                # Keep command history and capture files for this software session.
                # Cleanup happens only on an explicit request or software-session exit.
                return response

    def clear_history(self, expected_session):
        result = self.execute(['ALPHA REQUESTS CLEAR','ALPHA COMMANDS CLEAR'], expected_session=expected_session,
                              clear_console=True)
        if result.get('ok'):
            from maintenance import maintain
            with transport_lock(self.root):
                result['maintenance'] = maintain(self.root, force=True)
        return result

    def _close_owned_log(self, log, session):
        if not owns_capture(self.root, log, session):
            raise BridgeError('Refusing to close an unowned native log')
        token = uuid.uuid4().hex
        macro = self.root / (token + '.recover.mac')
        status = self.root / (token + '.recover.status')
        text = "!cjfile = object FILE('" + status.as_posix() + "')\n!cjstatus = object ARRAY()\n"
        text += "alpha log end\nhandle any\n  !cjstatus.append('FAILED')\n  !cjstatus.append(!!error.text)\n"
        text += "  !cjfile.writefile('OVERWRITE', !cjstatus)\n  return\nendhandle\n"
        text += "!cjstatus.append('OK')\n!cjfile.writefile('OVERWRITE', !cjstatus)\n"
        macro.write_bytes(text.replace('\n', '\r\n').encode('gbk'))
        raw = self._execute_raw(['$M /' + macro.as_posix()], 5, session)
        passed = status.exists() and read_pdms_text(status).strip() == 'OK'
        return {'ok': bool(raw['ok'] and passed), 'request_id': raw['request_id'], 'closed_log': log}

    def _execute_raw(self, commands, timeout=30, expected_session=None, metadata=None):
        validate_commands(commands)
        if not 0 < timeout <= 120:
            raise BridgeError('Timeout must be >0 and <=120 seconds')
        session = self.status()
        if not session['connected']:
            raise BridgeError('PDMS bridge is not connected; load the bootstrap macro once')
        if expected_session and session['session'] != expected_session:
            raise BridgeError('PDMS session changed; recheck the target before sending commands')
        request_id = uuid.uuid4().hex
        if metadata is not None:
            (self.root / (request_id + '.client.json')).write_text(json.dumps(metadata), encoding='utf-8')
        request = ET.Element('request', id=request_id, session=session['session'],
                             expires= str(time.time() + timeout))
        for command in commands:
            ET.SubElement(request, 'command').text = command
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / (request_id + '.tmp')
        temporary.write_bytes(ET.tostring(request, encoding='utf-8', xml_declaration=True))
        temporary.rename(self.root / (request_id + '.request'))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.result(request_id)
            if result is not None:
                return result
            time.sleep(0.05)
        raise BridgeError('Execution outcome uncertain; do not resend. Inspect request_id=' + request_id)

    def result(self, request_id):
        if len(request_id) != 32 or any(c not in '0123456789abcdef' for c in request_id):
            raise BridgeError('Invalid request id')
        path = self.root / (request_id + '.response')
        if not path.exists():
            archive_path = self.root.parent / 'history.json'
            if archive_path.exists():
                archive = json.loads(archive_path.read_text(encoding='utf-8'))
                for record in archive.get('recent', []):
                    if record['request_id'] == request_id:
                        return record
                for summary in archive.get('summaries', []):
                    if summary['request_id'] == request_id:
                        return {'request_id': request_id, 'ok': summary.get('ok'),
                                'details_expired': True, 'summary': summary}
            return None
        response = json.loads(path.read_text(encoding='utf-8-sig'))
        meta_path = self.root / (request_id + '.client.json')
        if not meta_path.exists():
            return response
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        status = read_pdms_text(meta['status']).splitlines() if Path(meta['status']).exists() else []
        log = read_pdms_text(meta['log']) if Path(meta['log']).exists() else ''
        outputs = parse_capture(log, meta['token'], len(meta['commands']))
        failed_at = None
        if status and status[0].startswith('ERROR:'):
            failed_at = int(status[0].split(':')[1])
        passed = status and status[0] == 'OK'
        response['ok'] = bool(response['ok'] and passed)
        response['capture_log'] = meta['log']
        response['capture_status'] = status
        response['capture_closed'] = 'CAPTURE_CLOSED' in status
        response['console_cleared'] = all('CLEAR_' + channel + '_OK' in status for channel in ('REQUESTS', 'COMMANDS'))
        response['results'] = []
        for i, command in enumerate(meta['commands']):
            if not passed and (failed_at is None or i > failed_at):
                break
            response['results'].append({'command': command, 'ok': i != failed_at, 'output': outputs[i],
                                        'error': '\n'.join(s for s in status[1:] if not s.startswith('CLEAR_') and s != 'CAPTURE_CLOSED') if i == failed_at else None})
        if not passed:
            response['error'] = '\n'.join(s for s in status if not s.startswith('CLEAR_') and s != 'CAPTURE_CLOSED') or response.get('error') or 'No native completion status; outcome unresolved'
        return response

    def record(self, project, note, request_ids):
        if not isinstance(project, str) or not project.strip() or not isinstance(note, str) or not note.strip():
            raise BridgeError('An important record needs a project name and a meaningful note')
        if not isinstance(request_ids, list) or len(request_ids) > 10:
            raise BridgeError('Use at most 10 source request ids')
        with transport_lock(self.root):
            sources = []
            for request_id in request_ids:
                result = self.result(request_id)
                if result is None or result.get('details_expired'):
                    raise BridgeError('Source result unavailable; do not invent evidence: ' + request_id)
                sources.append(result)
            path = self.root.parent / 'important-records.json'
            records = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
            entry = {'record_id': uuid.uuid4().hex, 'utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                     'project': project.strip(), 'note': note.strip(), 'sources': sources}
            records.append(entry)
            path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
            return {'record_id': entry['record_id'], 'file': str(path), 'source_count': len(sources)}


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default=str(DEFAULT_ROOT))
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('status')
    sub.add_parser('stop')
    clear = sub.add_parser('clear')
    clear.add_argument('--session', required=True)
    execute = sub.add_parser('exec')
    execute.add_argument('commands', nargs='+')
    execute.add_argument('--timeout', type=float, default=30)
    execute.add_argument('--session')
    result = sub.add_parser('result')
    result.add_argument('request_id')
    record = sub.add_parser('record')
    record.add_argument('--project', required=True)
    record.add_argument('--note', required=True)
    record.add_argument('--request-id', action='append', default=[])
    args = parser.parse_args()
    bridge = Bridge(args.root)
    try:
        if args.action == 'status':
            output = bridge.status()
        elif args.action == 'stop':
            output = bridge.stop()
        elif args.action == 'clear':
            output = bridge.clear_history(args.session)
        elif args.action == 'result':
            output = bridge.result(args.request_id)
        elif args.action == 'record':
            output = bridge.record(args.project, args.note, args.request_id)
        else:
            output = bridge.execute(args.commands, args.timeout, args.session)
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except BridgeError as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
