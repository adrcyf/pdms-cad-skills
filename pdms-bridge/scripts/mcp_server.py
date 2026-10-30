"""Dependency-free MCP stdio server for the local PDMS adapter."""
import json
import sys
import argparse
import os
import threading
import time
from bridge_client import Bridge, BridgeError
from process_lifecycle import CadSessionWorker, SoftwareSession

CAD_SESSION = CadSessionWorker()
IN_FLIGHT = threading.Event()

TOOLS = [
    {'name':'pdms_clear_history','description':'Explicitly clear the PDMS command display and completed temporary history only when the user asks; important records and unresolved requests are preserved.',
     'inputSchema':{'type':'object','properties':{'expected_session':{'type':'string'}},'required':['expected_session'],'additionalProperties':False}},
    {'name': 'cad_active_read', 'description': 'Read an already-running AutoCAD active document through native COM. No launch, focus, keyboard, console typing or source changes. Prefer this for open drawings.',
     'inputSchema': {'type': 'object', 'properties': {'action': {'type': 'string', 'enum': ['status', 'query']},
         'expected_path': {'type': 'string'}, 'types': {'type': 'array', 'items': {'type': 'string'}},
         'handles': {'type': 'array', 'items': {'type': 'string'}}, 'text_contains': {'type': 'string'},
         'offset': {'type': 'integer', 'minimum': 0}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200}},
         'additionalProperties': False}},
    {'name': 'cad_summary', 'description': 'Read a saved DWG/DXF without GUI. DWG uses AutoCAD Core Console on a copy; returns units, entity counts and provenance, not unsaved editor state.',
     'inputSchema': {'type': 'object', 'properties': {'path': {'type': 'string'}, 'core_console': {'type': 'string'}},
                     'required': ['path'], 'additionalProperties': False}},
    {'name': 'cad_query', 'description': 'Read filtered native CAD geometry, text, dimensions and block transforms; geometry measurements and text overrides are separate. Read-only, bounded output.',
     'inputSchema': {'type': 'object', 'properties': {'path': {'type': 'string'}, 'core_console': {'type': 'string'},
         'types': {'type': 'array', 'items': {'type': 'string'}}, 'text_contains': {'type': 'string'},
         'layers': {'type': 'array', 'items': {'type': 'string'}}, 'handles': {'type': 'array', 'items': {'type': 'string'}},
         'bbox': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 4, 'maxItems': 4},
         'layout': {'type': 'string', 'default': 'Model'}, 'include_blocks': {'type': 'boolean', 'default': True},
         'offset': {'type': 'integer', 'minimum': 0}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200}},
         'required': ['path'], 'additionalProperties': False}},
    {'name': 'cad_preview', 'description': 'Render a saved CAD drawing or crop to a PNG without touching application windows. Image assists interpretation; coordinates come from cad_query.',
     'inputSchema': {'type': 'object', 'properties': {'path': {'type': 'string'}, 'core_console': {'type': 'string'},
         'bbox': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 4, 'maxItems': 4}, 'layout': {'type': 'string'}},
         'required': ['path'], 'additionalProperties': False}},
    {'name': 'pdms_record', 'description': 'Preserve an important project decision or verified endpoint with source results outside rolling temporary cleanup. Use at significant milestones; do not record every routine query.',
     'inputSchema': {'type': 'object', 'properties': {'project': {'type': 'string'}, 'note': {'type': 'string'},
                     'request_ids': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 10}},
                     'required': ['project', 'note', 'request_ids'], 'additionalProperties': False}},
    {'name': 'pdms_status', 'description': 'Read current PDMS bridge session and heartbeat. No UI.',
     'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
    {'name': 'pdms_execute', 'description': 'Execute ordered native PDMS command lines in the loaded session; stop on first error. Changes are real; follow the user scope. Never automatically retry after timeout.',
     'inputSchema': {'type': 'object', 'properties': {
         'commands': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 999},
         'expected_session': {'type': 'string'},
         'timeout': {'type': 'number', 'exclusiveMinimum': 0, 'maximum': 120, 'default': 30}},
         'required': ['commands', 'expected_session'], 'additionalProperties': False}},
    {'name': 'pdms_result', 'description': 'Read a previous request result without executing it again. Null means outcome still unresolved.',
     'inputSchema': {'type': 'object', 'properties': {'request_id': {'type': 'string'}},
                     'required': ['request_id'], 'additionalProperties': False}},
]


def dispatch(message, bridge):
    method = message.get('method')
    if method == 'initialize':
        version = message.get('params', {}).get('protocolVersion', '2024-11-05')
        if version not in ('2024-11-05', '2025-03-26', '2025-06-18'):
            version = '2025-06-18'
        return {'protocolVersion': version, 'capabilities': {'tools': {}},
                'serverInfo': {'name': 'pdms-bridge', 'version': '0.4.0'}}
    if method == 'ping':
        return {}
    if method == 'tools/list':
        return {'tools': TOOLS}
    if method == 'tools/call':
        params = message.get('params', {})
        name, args = params.get('name'), params.get('arguments', {})
        try:
            if name in ('cad_active_read', 'cad_summary', 'cad_query', 'cad_preview'):
                state = bridge.status()
                design_pid = state.get('pid') if state.get('process_running') else None
                result = CAD_SESSION.request(name, args, design_pid=design_pid)
            elif name == 'pdms_status':
                result = bridge.status()
            elif name == 'pdms_clear_history':
                result = bridge.clear_history(args['expected_session'])
            elif name == 'pdms_record':
                result = bridge.record(args['project'], args['note'], args['request_ids'])
            elif name == 'pdms_result':
                result = bridge.result(args['request_id'])
            elif name == 'pdms_execute':
                if not args.get('expected_session'):
                    raise BridgeError('Read pdms_status and pass expected_session first')
                result = bridge.execute(args['commands'], args.get('timeout', 30), args['expected_session'])
            else:
                raise BridgeError('Unknown tool: ' + str(name))
            return {'content': [{'type': 'text', 'text': json.dumps(result, ensure_ascii=False, separators=(',', ':'))}],
                    'isError': isinstance(result, dict) and result.get('ok') is False}
        except (BridgeError, KeyError, TypeError, ValueError, OSError, RuntimeError) as exc:
            return {'content': [{'type': 'text', 'text': str(exc)}], 'isError': True}
    raise ValueError('Method not found: ' + str(method))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--owner-pid', type=int)
    parser.add_argument('--wait-for-software', type=float, default=10)
    parser.add_argument('--runtime-root')
    args = parser.parse_args()
    bridge = Bridge(args.runtime_root) if args.runtime_root else Bridge()
    state = bridge.status()
    owner = SoftwareSession(args.owner_pid or (state.get('pid') if state.get('process_running') else None))
    stopped = threading.Event()
    def watch_software():
        deadline = time.monotonic() + args.wait_for_software
        native_session = None
        while not stopped.wait(0.25):
            current = bridge.status()
            if current.get('connected') and native_session is None:
                native_session = current.get('session')
            logged_out = native_session is not None and (
                current.get('session') != native_session or current.get('stopped',False))
            ended = owner.ended()
            never_opened = not owner.owners and not IN_FLIGHT.is_set() and time.monotonic() > deadline
            if ended or never_opened or logged_out:
                try:
                    CAD_SESSION.close()
                finally:
                    try:
                        from maintenance import maintain
                        from bridge_client import transport_lock
                        with transport_lock(bridge.root):
                            maintain(bridge.root,force=True,session_end=True)
                    except Exception:
                        pass  # Preserve cleanup state/files rather than keep a dead session alive.
                    finally:
                        os._exit(0)
    threading.Thread(target=watch_software, daemon=True).start()
    try:
        for raw in sys.stdin.buffer:
            try:
                message = json.loads(raw)
                if 'id' not in message:
                    continue
                IN_FLIGHT.set()
                try:
                    result = dispatch(message, bridge)
                    reply = {'jsonrpc': '2.0', 'id': message['id'], 'result': result}
                except ValueError as exc:
                    reply = {'jsonrpc': '2.0', 'id': message['id'], 'error': {'code': -32601, 'message': str(exc)}}
            except Exception as exc:
                reply = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': str(exc)}}
            finally:
                IN_FLIGHT.clear()
            sys.stdout.buffer.write((json.dumps(reply, ensure_ascii=False) + '\n').encode('utf-8'))
            sys.stdout.buffer.flush()
    finally:
        stopped.set()
        CAD_SESSION.close()


if __name__ == '__main__':
    main()
