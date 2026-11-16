"""Load the local probe into a specific, explicitly selected BeamNG test process.

Run only against a disposable test profile. The game installation is untouched.
This experimental loader does not disable Lua sandboxing or expose a Lua API.
"""
import argparse
import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
import sys
import time

import psutil

if sys.platform != 'win32':
    raise SystemExit('Windows only')

k = c.WinDLL('kernel32', use_last_error=True)
def bind(name, restype, argtypes):
    f = getattr(k, name)
    f.restype, f.argtypes = restype, argtypes
    return f

HANDLE = w.HANDLE
OpenProcess = bind('OpenProcess', HANDLE, [w.DWORD, w.BOOL, w.DWORD])
VirtualAllocEx = bind('VirtualAllocEx', c.c_void_p, [HANDLE, c.c_void_p, c.c_size_t, w.DWORD, w.DWORD])
VirtualFreeEx = bind('VirtualFreeEx', w.BOOL, [HANDLE, c.c_void_p, c.c_size_t, w.DWORD])
WriteProcessMemory = bind('WriteProcessMemory', w.BOOL, [HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)])
CreateRemoteThread = bind('CreateRemoteThread', HANDLE, [HANDLE, c.c_void_p, c.c_size_t, c.c_void_p, c.c_void_p, w.DWORD, c.c_void_p])
WaitForSingleObject = bind('WaitForSingleObject', w.DWORD, [HANDLE, w.DWORD])
GetExitCodeThread = bind('GetExitCodeThread', w.BOOL, [HANDLE, c.POINTER(w.DWORD)])
CloseHandle = bind('CloseHandle', w.BOOL, [HANDLE])
GetModuleHandleW = bind('GetModuleHandleW', HANDLE, [w.LPCWSTR])
GetProcAddress = bind('GetProcAddress', c.c_void_p, [HANDLE, c.c_char_p])
LoadLibraryExW = bind('LoadLibraryExW', HANDLE, [w.LPCWSTR, HANDLE, w.DWORD])
FreeLibrary = bind('FreeLibrary', w.BOOL, [HANDLE])

def check(value, message):
    if not value:
        raise c.WinError(c.get_last_error(), message)
    return value

def remote_string(process, value):
    data = c.create_unicode_buffer(str(value))
    size = c.sizeof(data)
    addr = check(VirtualAllocEx(process, None, size, 0x3000, 0x04), 'VirtualAllocEx')
    written = c.c_size_t()
    if not WriteProcessMemory(process, addr, c.cast(data, c.c_void_p), size, c.byref(written)) or written.value != size:
        VirtualFreeEx(process, addr, 0, 0x8000)
        raise c.WinError(c.get_last_error(), 'WriteProcessMemory')
    return addr

def call(process, function, argument):
    thread = check(CreateRemoteThread(process, None, 0, function, argument, 0, None), 'CreateRemoteThread')
    try:
        wait = WaitForSingleObject(thread, 15000)
        if wait != 0:
            # The remote thread may still access its arguments: caller must not free them.
            raise RuntimeError(f'remote thread did not finish (wait={wait}); terminate the disposable game process')
        result = w.DWORD()
        check(GetExitCodeThread(thread, c.byref(result)), 'GetExitCodeThread')
        return result.value
    finally:
        CloseHandle(thread)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--user', type=Path, required=True, help='isolated -userpath of the test game')
    parser.add_argument('--dll', type=Path, required=True)
    parser.add_argument('--marker', type=Path, required=True)
    args = parser.parse_args()
    target = psutil.Process(args.pid)
    if target.name().lower() != 'beamng.drive.x64.exe':
        raise SystemExit('Refusing target: expected BeamNG.drive.x64.exe')
    cmd = target.cmdline()
    if '-userpath' not in cmd or any(x.startswith('--type=') for x in cmd):
        raise SystemExit('Refusing target: not a main game process with an explicit test userpath')
    user = args.user.resolve(strict=True)
    index = cmd.index('-userpath')
    if index + 1 >= len(cmd) or Path(cmd[index + 1]).resolve() != user:
        raise SystemExit('Refusing target: userpath mismatch')
    dll = args.dll.resolve(strict=True)
    marker = args.marker.resolve()
    if not marker.is_relative_to(user / 'current'):
        raise SystemExit('Refusing marker outside isolated current profile')
    if marker.exists():
        raise SystemExit('Marker already exists; use a new path')
    local = check(LoadLibraryExW(str(dll), None, 1), 'LoadLibraryExW')
    try:
        export = check(GetProcAddress(local, b'earthng_probe'), 'GetProcAddress')
        offset = export - local
    finally:
        FreeLibrary(local)
    process = check(OpenProcess(0x043A, False, args.pid), 'OpenProcess')
    try:
        # Only free buffers after a completed remote thread. On timeout preserve the
        # buffer until the isolated process exits, avoiding a remote use-after-free.
        dll_arg = remote_string(process, dll)
        load = check(GetProcAddress(GetModuleHandleW('kernel32.dll'), b'LoadLibraryW'), 'LoadLibraryW')
        result = call(process, load, dll_arg)
        VirtualFreeEx(process, dll_arg, 0, 0x8000)
        if result == 0:
            raise RuntimeError('Remote LoadLibraryW failed')
        # The thread exit code is 32-bit, not a 64-bit HMODULE. Find the real base.
        base = None
        for _ in range(20):
            for m in target.memory_maps(grouped=False):
                if m.path.lower() == str(dll).lower():
                    base = int(m.addr.split('-')[0], 16)
                    break
            if base is not None:
                break
            time.sleep(.05)
        if base is None:
            raise RuntimeError('DLL module was not found in target memory maps')
        marker_arg = remote_string(process, marker)
        result = call(process, base + offset, marker_arg)
        VirtualFreeEx(process, marker_arg, 0, 0x8000)
        if result != 0:
            raise RuntimeError(f'Probe export failed: {result}')
        print(f'pid={args.pid} module_base=0x{base:x} marker={marker}')
    finally:
        CloseHandle(process)

if __name__ == '__main__':
    main()
