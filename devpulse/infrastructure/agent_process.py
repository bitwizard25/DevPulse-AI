"""Operating-system lifetime controls for model-requested child processes."""

import ctypes


class WindowsProcessJob:
    """A Windows job object kills every attached child when the tool returns."""

    def __init__(self, process):
        from ctypes import wintypes

        class IoCounters(ctypes.Structure):
            _fields_ = [('value', ctypes.c_uint64 * 6)]

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ('process_time', ctypes.c_int64),
                ('job_time', ctypes.c_int64),
                ('flags', wintypes.DWORD),
                ('min_working_set', ctypes.c_size_t),
                ('max_working_set', ctypes.c_size_t),
                ('active_processes', wintypes.DWORD),
                ('affinity', ctypes.c_size_t),
                ('priority', wintypes.DWORD),
                ('scheduling_class', wintypes.DWORD),
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ('basic', BasicLimits),
                ('io', IoCounters),
                ('process_memory', ctypes.c_size_t),
                ('job_memory', ctypes.c_size_t),
                ('peak_process_memory', ctypes.c_size_t),
                ('peak_job_memory', ctypes.c_size_t),
            ]

        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self._close = kernel.CloseHandle
        self._close.argtypes = [wintypes.HANDLE]
        kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.INT,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        configured = kernel.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        )
        assigned = configured and kernel.AssignProcessToJobObject(
            self.handle, wintypes.HANDLE(process._handle)
        )
        if not assigned:
            code = ctypes.get_last_error()
            self.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            raise OSError(code, 'Could not contain command child processes in a Windows job.')

    def close(self):
        if self.handle:
            self._close(self.handle)
            self.handle = None
