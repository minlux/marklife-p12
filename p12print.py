#!/usr/bin/env python3
"""Print text on a Marklife P12 thermal label printer via USB (usblp).

Protocol ("L11"), as documented by
  https://github.com/thermal-label/marklife  (docs/protocol/l11.md)
  https://github.com/tomLadder/thermoprint   (REVERSE_ENGINEERING.md)

  [density]  1F 70 02 dd                  (optional, 1..3)
  [wakeup]   00 x 15
  [enable]   10 FF F1 02
  [raster]   1D 76 30 00 wL wH hL hH + rows (MSB first, 1 = black)
  [advance]  1D 0C (gap labels) | 1B 4A nn (continuous tape, feed nn dots)
  [stop]     10 FF F1 45

The print head is 96 dots (12 bytes) wide at 203 dpi (8 dots/mm). The tape
feeds lengthwise, so the text is rendered landscape and rotated 90 degrees.
"""

import argparse
import math
import os
import select
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

HEAD_DOTS = 96
DOTS_PER_MM = 8

WAKEUP = bytes(15)
ENABLE = bytes([0x10, 0xFF, 0xF1, 0x02])
STOP = bytes([0x10, 0xFF, 0xF1, 0x45])
POSITION_TO_GAP = bytes([0x1D, 0x0C])


def find_font(name):
    if name and os.path.isfile(name):
        return name
    try:
        path = subprocess.run(
            ["fc-match", "-f", "%{file}", name or "DejaVu Sans:bold"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if path:
            return path
    except (OSError, subprocess.CalledProcessError):
        pass
    return None


def load_font(path, size):
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def text_bbox(font, lines, spacing):
    draw = ImageDraw.Draw(Image.new("1", (1, 1)))
    l, t, r, b = draw.multiline_textbbox((0, 0), "\n".join(lines), font=font,
                                         spacing=spacing, align="center")
    return math.floor(l), math.floor(t), math.ceil(r), math.ceil(b)


def render_label(text, font_path, size, height_dots, length_dots, margin,
                 align="left"):
    """Render text landscape: width = along the tape, height = across the tape."""
    lines = text.split("\n")
    max_h = height_dots - 2 * margin
    max_w = (length_dots - 2 * margin) if length_dots else None

    if size:
        font = load_font(font_path, size)
    else:
        # largest font size that fits the label
        font = None
        for s in range(max_h * 2, 5, -1):
            f = load_font(font_path, s)
            l, t, r, b = text_bbox(f, lines, max(1, s // 6))
            if b - t <= max_h and (max_w is None or r - l <= max_w):
                font = f
                break
        if font is None:
            sys.exit("error: text does not fit on the label")

    spacing = max(1, int(font.size) // 6)
    l, t, r, b = text_bbox(font, lines, spacing)
    tw, th = r - l, b - t
    width = length_dots or (tw + 2 * margin)
    if tw > width or th > height_dots:
        print("warning: text is clipped, reduce --size", file=sys.stderr)

    img = Image.new("L", (width, height_dots), 255)
    draw = ImageDraw.Draw(img)
    if align == "left":
        x = margin - l
    elif align == "right":
        x = width - margin - tw - l
    else:
        x = (width - tw) // 2 - l
    y = (height_dots - th) // 2 - t
    draw.multiline_text((x, y), "\n".join(lines), font=font, fill=0,
                        spacing=spacing, align=align)
    return img


def to_raster(img, invert_rotation=False):
    """Rotate the landscape image onto the print head and pack it to 1 bpp."""
    img = img.rotate(90 if invert_rotation else -90, expand=True)
    # pad/crop to the full head width, label centered
    if img.width != HEAD_DOTS:
        canvas = Image.new("L", (HEAD_DOTS, img.height), 255)
        canvas.paste(img, ((HEAD_DOTS - img.width) // 2, 0))
        img = canvas
    # PIL mode "1": 0 = black; printer: 1 = black -> invert before packing
    bw = img.point(lambda p: 255 if p < 128 else 0).convert("1")
    return img, bw.tobytes(), HEAD_DOTS // 8, img.height


def build_job(raster, width_bytes, height, gap, feed_dots, density):
    job = bytearray()
    if density:
        job += bytes([0x1F, 0x70, 0x02, density])
    job += WAKEUP + ENABLE
    job += bytes([0x1D, 0x76, 0x30, 0x00,
                  width_bytes & 0xFF, width_bytes >> 8,
                  height & 0xFF, height >> 8])
    job += raster
    if gap:
        job += POSITION_TO_GAP
    elif feed_dots > 0:
        job += bytes([0x1B, 0x4A, feed_dots])
    job += STOP
    return bytes(job)


def send(device, job, timeout):
    fd = os.open(device, os.O_RDWR)
    try:
        view = memoryview(job)
        while view:
            n = os.write(fd, view)
            view = view[n:]
        # the printer acks an accepted job with 0xAA (not every usblp setup
        # delivers it, so a missing ack is only informational)
        r, _, _ = select.select([fd], [], [], timeout)
        if r:
            reply = os.read(fd, 64)
            if reply:
                return reply
    finally:
        os.close(fd)
    return None


def main():
    p = argparse.ArgumentParser(
        description="Print text on a Marklife P12 label printer via USB.")
    p.add_argument("--usb", required=True, metavar="DEVICE",
                   help="usblp device file, e.g. /dev/usb/lp3")
    p.add_argument("text", nargs="+",
                   help="text to print (words are joined with spaces, "
                        "a literal \\n starts a new line)")
    p.add_argument("--length", type=float, default=0,
                   help="label length in mm along the tape "
                        "(default: 0 = as long as the text)")
    p.add_argument("--width", type=float, default=12,
                   help="printable label width in mm across the tape "
                        "(default: 12, max 12)")
    p.add_argument("--font", help="font file or fontconfig name "
                                  "(default: DejaVu Sans:bold)")
    p.add_argument("--size", type=int, help="font size in dots (default: auto-fit)")
    p.add_argument("--align", choices=("left", "center", "right"),
                   default="left",
                   help="text alignment (default: left)")
    p.add_argument("--margin", type=int, default=8,
                   help="margin in dots, 8 dots = 1 mm (default: 8)")
    p.add_argument("--gap", action="store_true",
                   help="die-cut labels: advance to the next label gap "
                        "(on continuous tape this feeds a long blank strip!)")
    p.add_argument("--feed", type=float, default=10,
                   help="continuous tape: extra feed in mm after printing, so the "
                        "label clears the cutter (default: 10, max 31)")
    p.add_argument("--density", type=int, choices=(1, 2, 3),
                   help="1 light, 2 normal, 3 dark (default: printer setting)")
    p.add_argument("--flip", action="store_true", help="rotate text 180 degrees")
    p.add_argument("--copies", type=int, default=1)
    p.add_argument("--preview", metavar="PNG",
                   help="also save the rendered label as PNG")
    p.add_argument("--dry-run", action="store_true",
                   help="do not send to the printer (use with --preview)")
    args = p.parse_args()

    text = " ".join(args.text).replace("\\n", "\n")
    height = min(HEAD_DOTS, round(args.width * DOTS_PER_MM))
    length = round(args.length * DOTS_PER_MM) if args.length > 0 else None

    img = render_label(text, find_font(args.font), args.size, height, length,
                       args.margin, args.align)
    rotated, raster, width_bytes, rows = to_raster(img, args.flip)

    if args.preview:
        rotated.rotate(-90 if args.flip else 90, expand=True).save(args.preview)
        print(f"preview written to {args.preview}")
    if args.dry_run:
        return

    feed_dots = min(255, round(args.feed * DOTS_PER_MM))
    job = build_job(raster, width_bytes, rows, args.gap, feed_dots, args.density)
    for i in range(args.copies):
        try:
            reply = send(args.usb, job, timeout=5)
        except OSError as e:
            sys.exit(f"error: {args.usb}: {e.strerror}")
        if reply is None:
            print(f"label {i + 1}: sent ({len(job)} bytes), no ack received")
        elif reply[0] == 0xAA:
            print(f"label {i + 1}: printed")
        else:
            print(f"label {i + 1}: printer replied {reply.hex(' ')}")


if __name__ == "__main__":
    main()
