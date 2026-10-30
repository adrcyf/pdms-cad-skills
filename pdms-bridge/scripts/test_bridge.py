import importlib.util
import pathlib
import tempfile
import unittest


class BridgeTests(unittest.TestCase):
    def test_normal_execution_retains_session_history_without_cleanup(self):
        from bridge_client import Bridge
        from unittest.mock import patch
        import datetime, json, os
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)/'runtime'; root.mkdir()
            (root/'session.json').write_text(json.dumps({'session':'s','pid':os.getpid(),
                'utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}))
            bridge = Bridge(root)
            with patch.object(bridge,'_execute_raw',return_value={'ok':True,'results':[]}), patch('maintenance.maintain') as cleanup:
                bridge.execute(['Q NAME'])
                cleanup.assert_not_called()
            macros=list(root.glob('*.capture.mac'))
            self.assertEqual(len(macros),1)
            self.assertIn('alpha requests clear',macros[0].read_text(encoding='gbk'))

    def test_session_end_drops_routine_details_but_preserves_important_records(self):
        from maintenance import plan_cleanup
        import json
        with tempfile.TemporaryDirectory() as directory:
            parent=pathlib.Path(directory);root=parent/'runtime';root.mkdir()
            important=parent/'important-records.json';important.write_text('[{"important":true}]')
            key='a'*32
            (root/(key+'.response')).write_text(json.dumps({'request_id':key,'ok':True,'results':[]}))
            (root/(key+'.running')).write_text('<request/>')
            plan=plan_cleanup(root,force=True,session_end=True)
            self.assertEqual(json.loads((parent/'history.json').read_text())['recent'],[])
            self.assertNotIn(str(important),json.loads(plan.read_text())['files'])
            self.assertEqual(important.read_text(),'[{"important":true}]')

    def test_cleanup_preserves_unresolved_and_unknown_files(self):
        from maintenance import plan_cleanup
        import json
        with tempfile.TemporaryDirectory() as root:
            base = pathlib.Path(root) / 'runtime'
            base.mkdir()
            for i in range(6):
                key = format(i, '032x')
                (base / (key + '.response')).write_text(json.dumps({'request_id': key, 'ok': True, 'results': []}))
                (base / (key + '.running')).write_text('<request/>')
            pending = base / ('f' * 32 + '.running')
            pending.write_text('<request/>')
            unknown = base / 'my-drawing.dwg'
            unknown.write_text('preserve')
            manifest = json.loads(plan_cleanup(base, force=True).read_text())
            self.assertNotIn(str(pending), manifest['files'])
            self.assertNotIn(str(unknown), manifest['files'])
            self.assertEqual(len(manifest['files']), 12)

    def test_macro_is_quiet_but_preserves_query_capture(self):
        from bridge_client import build_capture_macro
        text = build_capture_macro(['Q NAME'], 't', 'C:/safe/log', 'C:/safe/status')
        self.assertTrue(text.startswith('$R0\n'))
        self.assertIn('alpha log /C:/safe/log over', text)
        self.assertNotIn('over requests', text)
        self.assertIn('alpha requests clear', text)

    def test_capture_clears_both_console_channels_after_log_close(self):
        from bridge_client import build_capture_macro
        text = build_capture_macro(['Q NAME'], 't', 'C:/safe/log', 'C:/safe/status', clear_console=True)
        self.assertEqual(text.lower().count('alpha requests clear'), 2)
        self.assertEqual(text.lower().count('alpha commands clear'), 2)
        self.assertGreater(text.lower().rfind('alpha requests clear'), text.lower().rfind('alpha log end'))

    def test_orphan_recovery_accepts_only_proven_current_session_log(self):
        from bridge_client import owns_capture
        import xml.etree.ElementTree as ET
        with tempfile.TemporaryDirectory() as root:
            base = pathlib.Path(root)
            log = base / ('b' * 32 + '.capture.log')
            request = ET.Element('request', session='s')
            ET.SubElement(request, 'command').text = 'ALPHA LOG /' + log.as_posix() + ' OVER'
            (base / ('a' * 32 + '.running')).write_bytes(ET.tostring(request))
            self.assertTrue(owns_capture(base, str(log), 's'))
            self.assertFalse(owns_capture(base, str(log), 'other'))
            self.assertFalse(owns_capture(base, str(base.parent / 'unknown.log'), 's'))

    def test_late_result_keeps_native_error_and_does_not_claim_skipped_command(self):
        from bridge_client import Bridge
        import json
        with tempfile.TemporaryDirectory() as root:
            base = pathlib.Path(root)
            request_id = 'a' * 32
            (base / (request_id + '.response')).write_text(json.dumps({'ok': True, 'results': []}))
            (base / 'capture.status').write_text('ERROR:0\nUnknown attribute\n', encoding='utf-8')
            (base / 'capture.log').write_text('CJBR_t_0\n失败\n', encoding='utf-8-sig')
            (base / (request_id + '.client.json')).write_text(json.dumps({
                'token': 't', 'commands': ['Q BAD', 'Q TYPE'],
                'status': str(base / 'capture.status'), 'log': str(base / 'capture.log')}))
            result = Bridge(root).result(request_id)
            self.assertFalse(result['ok'])
            self.assertEqual(len(result['results']), 1)
            self.assertEqual(result['results'][0]['error'], 'Unknown attribute')
            self.assertEqual(result['results'][0]['output'], '失败')

    def test_pending_request_blocks_a_second_batch(self):
        from bridge_client import Bridge, BridgeError
        import datetime, json, os
        with tempfile.TemporaryDirectory() as root:
            session = {'session': 's', 'pid': os.getpid(),
                       'utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
            pathlib.Path(root, 'session.json').write_text(json.dumps(session))
            pathlib.Path(root, 'a' * 32 + '.running').write_text('<request session="s"/>')
            with self.assertRaisesRegex(BridgeError, 'unresolved'):
                Bridge(root).execute(['Q NAME'])
            self.assertFalse(list(pathlib.Path(root).glob('*.request')))

    def test_macro_handles_errors_before_closing_owned_log(self):
        from bridge_client import build_capture_macro
        text = build_capture_macro(['Q NAME', 'Q TYPE'], 'abc', 'C:/safe/log', 'C:/safe/status')
        self.assertGreaterEqual(text.lower().count('handle any'), 3)
        self.assertIn("ERROR:0", text)
        self.assertIn("CAPTURE_START_FAILED", text)
        self.assertIn('alpha log end\n', text.lower())
        self.assertIn('alpha requests clear', text.lower())

    def test_capture_maps_output_without_command_echo(self):
        from bridge_client import parse_capture
        text = '\nCJBR_abc_0\n\nName /TEST_EQUIPMENT\n\nCJBR_abc_1\nPosition E 1000mm N 0mm U 0mm\n'
        self.assertEqual(parse_capture(text, 'abc', 2), ['Name /TEST_EQUIPMENT', 'Position E 1000mm N 0mm U 0mm'])

    def test_disconnected_does_not_enqueue(self):
        from bridge_client import Bridge, BridgeError
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(BridgeError):
                Bridge(root).execute(['Q NAME'])
            self.assertFalse(list(pathlib.Path(root).glob('*.request')))

    def test_commands_reject_multiline_and_empty(self):
        from bridge_client import validate_commands, BridgeError
        for commands in ([], [''], ['Q NAME\nDELETE CE']):
            with self.assertRaises(BridgeError):
                validate_commands(commands)

    def test_uncertain_timeout_has_request_id(self):
        from bridge_client import Bridge, BridgeError
        import datetime, json, os
        with tempfile.TemporaryDirectory() as root:
            session = {'session': 'test-session', 'pid': os.getpid(),
                       'utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
            pathlib.Path(root, 'session.json').write_text(json.dumps(session))
            with self.assertRaises(BridgeError) as error:
                Bridge(root).execute(['Q NAME'], timeout=0.05)
            self.assertIn('request_id=', str(error.exception))
            self.assertEqual(len(list(pathlib.Path(root).glob('*.request'))), 1)


if __name__ == '__main__':
    unittest.main()
