"""How much a build may run at once on this machine."""
import os
from pathlib import Path
import time


def free_memory_gb():
    """Available physical memory in GB, or a large number where it cannot be read."""
    try:
        import psutil
        return psutil.virtual_memory().available / 2**30
    except ImportError:
        pass
    if os.name == 'nt':
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong), ('total', ctypes.c_ulonglong),
                        ('available', ctypes.c_ulonglong), ('page_total', ctypes.c_ulonglong),
                        ('page_available', ctypes.c_ulonglong), ('virtual_total', ctypes.c_ulonglong),
                        ('virtual_available', ctypes.c_ulonglong), ('extended', ctypes.c_ulonglong)]
        status = Status(length=ctypes.sizeof(Status))
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.available / 2**30
    try:
        return os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE') / 2**30
    except (AttributeError, ValueError, OSError):
        return 64.


def jobs(per_job_gb, most=None):
    """Processes that fit: one core left for the window, per_job_gb of free memory each."""
    cpu = max(1, (os.cpu_count() or 2) - 1)
    return max(1, min(cpu if most is None else min(cpu, most), int(free_memory_gb() // per_job_gb)))


def replace_dir(source, target, attempts=60):
    """Rename a freshly written folder. Windows refuses (WinError 5) while an antivirus or the
    indexer still holds one of its new files: Ukraine's 35 000 tiles once failed the final rename."""
    for attempt in range(attempts):
        try:
            return Path(source).replace(target)
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(1)
