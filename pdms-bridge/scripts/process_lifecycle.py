"""Read process lifetime and own disposable workers. Never controls windows or user applications."""
import ctypes
from ctypes import wintypes as w
import os
from pathlib import Path
import subprocess
import sys
import json
import time
import threading
import queue


class ProcessEntry(ctypes.Structure):
    _fields_ = [('size',w.DWORD),('usage',w.DWORD),('pid',w.DWORD),('heap',ctypes.c_size_t),
                ('module',w.DWORD),('threads',w.DWORD),('parent',w.DWORD),('priority',w.LONG),
                ('flags',w.DWORD),('executable',w.WCHAR*260)]


def software_pids():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [w.DWORD,w.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    kernel.Process32FirstW.argtypes = [w.HANDLE,ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes = [w.HANDLE,ctypes.POINTER(ProcessEntry)]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2,0)
    result = {'design': [], 'cad': []}
    if snapshot == ctypes.c_void_p(-1).value:
        return result
    try:
        entry = ProcessEntry(); entry.size = ctypes.sizeof(entry)
        valid = kernel.Process32FirstW(snapshot,ctypes.byref(entry))
        while valid:
            kind = {'des.exe':'design','acad.exe':'cad'}.get(entry.executable.casefold())
            if kind:
                result[kind].append(int(entry.pid))
            valid = kernel.Process32NextW(snapshot,ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return result


class SoftwareSession:
    def __init__(self, owner_pid=None):
        self.owners = [owner_pid] if owner_pid else []
        self.forced = owner_pid is not None
        self.kind = 'explicit' if owner_pid else None

    def ended(self):
        if self.kind == 'cad' and not self.forced:
            design = software_pids()['design']
            if design:
                self.kind, self.owners = 'design', design
        if self.owners:
            return not any(process_alive(pid) for pid in self.owners)
        available = software_pids()
        for kind in ('design','cad'):
            if available[kind]:
                self.kind, self.owners = kind, available[kind]
                return False
        return False  # Initial handshake can precede the user opening their software.


def process_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE only; no terminate permission.
    if not handle:
        return False
    try:
        return kernel.WaitForSingleObject(handle, 0) == 258
    finally:
        kernel.CloseHandle(handle)


class BasicLimits(ctypes.Structure):
    _fields_ = [('per_process', ctypes.c_longlong), ('per_job', ctypes.c_longlong), ('flags', w.DWORD),
                ('minimum_working_set', ctypes.c_size_t), ('maximum_working_set', ctypes.c_size_t),
                ('active_processes', w.DWORD), ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]


class IOCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [('basic', BasicLimits), ('io', IOCounters), ('process_memory', ctypes.c_size_t),
                ('job_memory', ctypes.c_size_t), ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]


class OwnedJob:
    """KILL_ON_JOB_CLOSE applies only to the newly created worker and its descendants."""
    def __init__(self, process):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [w.LPVOID, w.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = w.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())
        if not self.kernel.AssignProcessToJobObject(self.handle, w.HANDLE(int(process._handle))):
            self.close()
            process.terminate()  # This is our newly created, still idle worker only.
            process.wait(timeout=5)
            raise RuntimeError('Cannot bind owned worker lifetime; no unguarded CAD request was started')

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class CadSessionWorker:
    def __init__(self):
        self.child = None
        self.job = None
        self.responses = None
        self.calls = 0
        self.lock = threading.RLock()

    def _start(self):
        self.child = subprocess.Popen([sys.executable, str(Path(__file__).with_name('cad_worker.py'))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.job = OwnedJob(self.child)
        self.responses = queue.Queue()
        child, responses = self.child, self.responses
        def read_responses():
            try:
                for line in child.stdout:
                    responses.put(line)
            except (OSError, ValueError):
                pass
            finally:
                responses.put(None)
        threading.Thread(target=read_responses, daemon=True).start()
        self.calls = 0

    def request(self, name, arguments, timeout=120, design_pid=None):
        with self.lock:
            if design_pid is not None and not process_alive(design_pid):
                self.close()
                raise RuntimeError('Bound Design process exited')
            if self.child is None or self.child.poll() is not None:
                self.close()
                self._start()
            child, responses = self.child, self.responses
            self.calls += 1
            child.stdin.write((json.dumps({'name':name,'arguments':arguments})+'\n').encode('utf-8'))
            child.stdin.flush()
            deadline = time.monotonic()+timeout
            while True:
                if design_pid is not None and not process_alive(design_pid):
                    self.close()
                    raise RuntimeError('Bound Design process exited; session worker released')
                if time.monotonic() > deadline:
                    self.close()
                    raise RuntimeError('CAD read timed out; session worker released')
                try:
                    line = responses.get(timeout=0.25)
                except queue.Empty:
                    continue
                if line is None:
                    raise RuntimeError('CAD session worker disconnected; no write was retried')
                result = json.loads(line)
                result.update(worker_pid=child.pid, worker_reused=self.calls>1, worker_released=False)
                return result

    def close(self):
        # Closing the job can interrupt an outstanding read without touching the user application.
        job, child = self.job, self.child
        self.job = self.child = None
        if job is not None:
            job.close()
        if child is not None:
            child.wait(timeout=5)
            for pipe in (child.stdin,child.stdout):
                if pipe is not None and not pipe.closed:
                    pipe.close()


def run_cad_worker(name, arguments, design_pid=None, timeout=120):
    # Child waits for stdin; attach ownership before allowing any CAD work or descendants.
    child = subprocess.Popen([sys.executable, str(Path(__file__).with_name('cad_worker.py'))],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    job = None
    try:
        job = OwnedJob(child)
        deadline = time.monotonic() + timeout
        payload = (json.dumps({'name': name, 'arguments': arguments}) + '\n').encode('utf-8')
        while True:
            if design_pid is not None and not process_alive(design_pid):
                raise RuntimeError('Bound Design process exited; owned read worker was released')
            if time.monotonic() > deadline:
                raise RuntimeError('CAD read timeout; owned worker and conversion descendants were released')
            try:
                out, err = child.communicate(input=payload, timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                payload = None  # communicate resumes the same request; never sends it twice.
        if child.returncode:
            raise RuntimeError(err.decode('utf-8', errors='replace')[-1500:] or 'CAD worker failed')
        result = json.loads(out.decode('utf-8-sig'))
        result['worker_released'] = True
        return result
    finally:
        if job is not None:
            job.close()
        elif child.poll() is None:
            child.terminate()
        child.wait(timeout=5)
        for pipe in (child.stdin, child.stdout, child.stderr):
            if pipe is not None and not pipe.closed:
                pipe.close()

