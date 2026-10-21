"""Stand-in for adb covering the commands the bot and the GUI run. The screen never matches a stage."""

import struct
import sys
import zlib

SERIAL = "127.0.0.1:5555"
WIDTH, HEIGHT = 1280, 720


def png(width, height, rgb):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = (b"\x00" + bytes(rgb) * width) * height
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows, 1)) + chunk(b"IEND", b"")


def main(args):
    if args[:1] == ["-s"]:
        args = args[2:]
    match args:
        case ["connect", target]:
            print(f"connected to {target}")
        case ["devices"]:
            print(f"List of devices attached\n{SERIAL}\tdevice\n")
        case ["exec-out", "screencap", "-p"]:
            sys.stdout.buffer.write(png(WIDTH, HEIGHT, (40, 90, 160)))
        case ["shell", "pidof", _]:
            print("4242")
        case ["shell", ("input" | "monkey" | "cmd"), *_]:
            pass
        case _:
            sys.exit(f"fake adb: unsupported command {args}")


if __name__ == "__main__":
    main(sys.argv[1:])
