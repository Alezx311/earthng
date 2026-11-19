"""GPU-ready offline map sheets, shared by the planet atlas and area builder."""
import io
import struct
from PIL import Image


def save_photo(image, path):
    """A GPU-ready DXT5 sheet. Keep its soft alpha border and all mip levels."""
    lod = image
    levels = []
    while True:
        buf = io.BytesIO()
        lod.save(buf, 'DDS', pixel_format='DXT5')
        encoded = buf.getvalue()
        if not levels:
            header = bytearray(encoded[:128])
        levels.append(encoded[128:])
        if lod.size == (1, 1):
            break
        lod = lod.resize((max(1, lod.width // 2), max(1, lod.height // 2)), Image.Resampling.BOX)
    flags = struct.unpack_from('<I', header, 8)[0]
    struct.pack_into('<I', header, 8, flags | 0x20000)  # DDSD_MIPMAPCOUNT
    struct.pack_into('<I', header, 28, len(levels))
    struct.pack_into('<I', header, 108, 0x401008)       # texture, complex, mipmap
    path.write_bytes(header + b''.join(levels))

