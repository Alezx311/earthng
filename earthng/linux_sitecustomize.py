"""sitecustomize of the Linux package's Python (prepare_linux.py copies it into site-packages).

pyosmium's extension modules need libexpat.so.1, which the manylinux rules leave to the system
and a minimal system (a bare Ubuntu 20.04) does not have. Every interpreter of the package (the
page server, the service, its workers) loads it here first: the system's copy if there is one,
else the one in earthng.libs beside this file. The dynamic linker then answers osmium's need
with the library already loaded, by its soname.
"""
import ctypes
import os

try:
    ctypes.CDLL('libexpat.so.1', mode=ctypes.RTLD_GLOBAL)
except OSError:
    try:
        ctypes.CDLL(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'earthng.libs', 'libexpat.so.1'),
                    mode=ctypes.RTLD_GLOBAL)
    except OSError:
        pass
