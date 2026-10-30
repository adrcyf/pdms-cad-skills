import os
from pathlib import Path
import subprocess
import sys
import time
import unittest


class LifecycleTests(unittest.TestCase):
    def test_native_logout_releases_bridge_without_terminating_software_host(self):
        from process_lifecycle import process_alive
        import datetime, json, tempfile
        owner = subprocess.Popen([sys.executable,'-c','import sys;sys.stdin.readline()'],stdin=subprocess.PIPE,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        server = None
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state = {'session':'native-session-test','pid':owner.pid,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'stopped':False}
                (root/'session.json').write_text(json.dumps(state))
                server = subprocess.Popen([sys.executable,str(Path(__file__).with_name('mcp_server.py')),
                    '--owner-pid',str(owner.pid),'--runtime-root',str(root)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
                request = {'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'cad_active_read','arguments':{'action':'status'}}}
                server.stdin.write((json.dumps(request)+'\n').encode());server.stdin.flush()
                reply = json.loads(server.stdout.readline())
                result = json.loads(reply['result']['content'][0]['text'])
                state['stopped']=True
                (root/'session.json').write_text(json.dumps(state))
                server.wait(timeout=5)
                self.assertEqual(server.returncode,0)
                self.assertIsNone(owner.poll())
                for _ in range(100):
                    if not process_alive(result['worker_pid']) and not process_alive(result['native_session_pid']): break
                    time.sleep(0.02)
                self.assertFalse(process_alive(result['worker_pid']))
                self.assertFalse(process_alive(result['native_session_pid']))
        finally:
            for process in (server,owner):
                if process is None: continue
                if process.poll() is None: process.terminate(); process.wait(timeout=5)
                for pipe in (process.stdin,process.stdout,process.stderr):
                    if pipe is not None and not pipe.closed: pipe.close()

    def test_mcp_and_cached_read_helpers_exit_when_software_owner_exits(self):
        from process_lifecycle import process_alive
        import json
        owner = subprocess.Popen([sys.executable,'-c','import sys;sys.stdin.readline()'], stdin=subprocess.PIPE,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        server = subprocess.Popen([sys.executable,str(Path(__file__).with_name('mcp_server.py')),'--owner-pid',str(owner.pid)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            def call(ident, method, params):
                server.stdin.write((json.dumps({'jsonrpc':'2.0','id':ident,'method':method,'params':params})+'\n').encode())
                server.stdin.flush()
                return json.loads(server.stdout.readline())
            call(1,'initialize',{'protocolVersion':'2025-06-18'})
            reply = call(2,'tools/call',{'name':'cad_active_read','arguments':{'action':'status'}})
            result = json.loads(reply['result']['content'][0]['text'])
            worker, native = result['worker_pid'], result['native_session_pid']
            self.assertTrue(process_alive(worker))
            self.assertTrue(process_alive(native))
            owner.stdin.close(); owner.wait(timeout=5)
            server.wait(timeout=5)
            self.assertEqual(server.returncode,0)
            for _ in range(100):
                if not process_alive(worker) and not process_alive(native):
                    break
                time.sleep(0.02)
            self.assertFalse(process_alive(worker))
            self.assertFalse(process_alive(native))
        finally:
            for process in (server,owner):
                if process.poll() is None:
                    process.terminate(); process.wait(timeout=5)
                for pipe in (process.stdin,process.stdout,process.stderr):
                    if pipe is not None and not pipe.closed:
                        pipe.close()

    def test_session_worker_is_reused_between_commands(self):
        from process_lifecycle import CadSessionWorker, process_alive
        session = CadSessionWorker()
        try:
            first = session.request('cad_active_read', {'action': 'status'}, timeout=15)
            second = session.request('cad_active_read', {'action': 'status'}, timeout=15)
            self.assertEqual(first['worker_pid'], second['worker_pid'])
            self.assertEqual(first['native_session_pid'], second['native_session_pid'])
            self.assertTrue(second['worker_reused'])
            self.assertTrue(process_alive(first['worker_pid']))
        finally:
            session.close()
        self.assertFalse(process_alive(first['worker_pid']))

    def test_disabling_mcp_preserves_other_client_settings(self):
        from configure_mcp import set_server_enabled
        import tomllib
        original = 'sandbox_mode="workspace-write"\n[mcp_servers.pdms_bridge]\ncommand="python.exe"\nargs=["server.py"]\n[mcp_servers.pdms_bridge.env]\nKEEP="yes"\n[mcp_servers.other]\nenabled=true\ncommand="other.exe"\n'
        updated = set_server_enabled(original, 'python.exe', 'server.py', False)
        expected = tomllib.loads(original)
        expected['mcp_servers']['pdms_bridge']['enabled'] = False
        self.assertEqual(tomllib.loads(updated), expected)
        self.assertEqual(set_server_enabled(updated, 'python.exe', 'server.py', False), updated)

    def test_owned_job_also_releases_its_disposable_descendant(self):
        from process_lifecycle import OwnedJob, process_alive
        code = "import sys,subprocess,time;sys.stdin.readline();p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);print(p.pid,flush=True);time.sleep(30)"
        parent = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        job = OwnedJob(parent)
        try:
            parent.stdin.write(b'go\n'); parent.stdin.flush()
            descendant = int(parent.stdout.readline())
            self.assertTrue(process_alive(descendant))
            job.close()
            parent.wait(timeout=5)
            for _ in range(50):
                if not process_alive(descendant):
                    break
                time.sleep(0.02)
            self.assertFalse(process_alive(descendant))
        finally:
            job.close()
            parent.wait(timeout=5)
            parent.stdin.close(); parent.stdout.close()

    def test_cad_read_worker_returns_data_and_exits(self):
        from process_lifecycle import run_cad_worker
        result = run_cad_worker('cad_active_read', {'action': 'status'}, timeout=15)
        self.assertTrue(result['worker_released'])
        self.assertTrue('error' in result or result.get('connected'))

    def test_no_worker_is_left_when_bound_process_is_already_gone(self):
        from process_lifecycle import run_cad_worker
        with self.assertRaisesRegex(RuntimeError, 'Design process exited'):
            run_cad_worker('cad_active_read', {'action': 'status'}, design_pid=2147483647, timeout=5)

    def test_process_presence_is_read_only(self):
        from process_lifecycle import process_alive
        self.assertTrue(process_alive(os.getpid()))
        self.assertFalse(process_alive(0))

    @unittest.skipUnless(os.name == 'nt', 'Windows process job test')
    def test_closing_owned_job_releases_only_owned_worker(self):
        from process_lifecycle import OwnedJob
        child = subprocess.Popen([sys.executable, '-c', 'import sys,time;sys.stdin.readline();time.sleep(30)'],
                                 stdin=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            job = OwnedJob(child)
            child.stdin.write(b'go\n')
            child.stdin.flush()
            job.close()
            child.wait(timeout=5)
            self.assertIsNotNone(child.returncode)
        finally:
            child.stdin.close()
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
