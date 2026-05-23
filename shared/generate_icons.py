"""
Icon generator for AI Email Organizer
Creates local base64 PNG icons for the extension and add-in.
"""

import base64
import struct
import zlib
import os


def create_simple_png(width, height, color_rgb):
    """Create a simple solid color PNG"""

    def png_chunk(chunk_type, data):
        chunk_len = struct.pack(">I", len(data))
        chunk_crc = struct.pack(">I", zlib.crc32(chunk_type + data) & 0xffffffff)
        return chunk_len + chunk_type + data + chunk_crc

    signature = b'\x89PNG\r\n\x1a\n'

    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = png_chunk(b'IHDR', ihdr_data)

    raw_data = b''
    for y in range(height):
        raw_data += b'\x00'
        for x in range(width):
            raw_data += bytes(color_rgb)

    compressed = zlib.compress(raw_data, 9)
    idat = png_chunk(b'IDAT', compressed)

    iend = png_chunk(b'IEND', b'')

    return signature + ihdr + idat + iend


def main():
    base_path = os.path.dirname(os.path.dirname(__file__))
    outlook_icons = os.path.join(base_path, "outlook-addin", "icons")

    os.makedirs(outlook_icons, exist_ok=True)

    color = (102, 126, 234)

    sizes = [16, 32, 48, 128]

    for size in sizes:
        png_data = create_simple_png(size, size, color)

        outlook_path = os.path.join(outlook_icons, f"icon{size}.png")
        with open(outlook_path, "wb") as f:
            f.write(png_data)
        print(f"Created: {outlook_path}")

    print("\nIcons created! Replace with actual branded icons before publishing.")


if __name__ == "__main__":
    main()
