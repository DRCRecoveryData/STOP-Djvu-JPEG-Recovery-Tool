#!/usr/bin/env python3
"""
recover.py - STOP/Djvu JPEG Recovery Tool

Recovers JPEG photos encrypted by STOP/Djvu ransomware using a
same-camera clean JPEG as a decoder warm-up reference.

Pipeline:
  1. Splice: reference prefix (warm-up) + encrypted file (surviving data)
  2. Decode, crop top (reference bleed) and bottom (white fill)
  3. Half-swap left/right for composition correction
  4. Shift left half down by N pixels (MCU alignment)
  5. Crop right-edge seam
  6. Crop N MCU scanlines from top
  7. PhotoDemon-style auto-correct (WB + Clarity + Saturation)

Usage:
    python3 recover.py <encrypted> <reference> <output> [options]

Example:
    python3 recover.py _NHL0591.JPG.nppp _NHL0592.JPG recovered.jpg
    python3 recover.py IMG_4054.JPG.nppp IMG_4312.JPG out.jpg --mcu-size 16
"""

import os
import argparse
import numpy as np
from PIL import Image, ImageEnhance, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True


# ============================================================
#  STEP 1-2: SPLICE + DECODE + CROP
# ============================================================
def splice_and_decode(encrypted_path, reference_path,
                      ref_prefix=153605,
                      crop_top=424, crop_bottom=60):
    """Splice reference prefix + encrypted data, decode, crop bleed/fill."""
    ref = open(reference_path, "rb").read()
    enc = open(encrypted_path, "rb").read()

    spliced = ref[:ref_prefix] + enc[ref_prefix:]
    tmp = "_splice_tmp.jpg"
    with open(tmp, "wb") as f:
        f.write(spliced)

    try:
        im = Image.open(tmp).convert("RGB")
        im.load()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    w, h = im.size
    print(f"[1] Decoded:       {w}x{h}")

    im = im.crop((0, crop_top, w, h - crop_bottom))
    print(f"[2] Cropped:       {im.size}")
    return im


# ============================================================
#  STEP 3: HALF-SWAP LEFT/RIGHT
# ============================================================
def half_swap(im):
    """Split at midpoint, swap left and right halves."""
    w, h = im.size
    mid = w // 2

    left = im.crop((0, 0, mid, h))
    right = im.crop((mid, 0, w, h))

    new = Image.new("RGB", (w, h))
    new.paste(right, (0, 0))
    new.paste(left, (right.width, 0))

    print(f"[3] Half-swapped:  {new.size}")
    return new


# ============================================================
#  STEP 4: SHIFT LEFT HALF DOWN
# ============================================================
def shift_left_half_down(im, shift_px=8):
    """Shift the left half down by N pixels to align with right half."""
    w, h = im.size
    mid = w // 2

    left = im.crop((0, 0, mid, h))
    right = im.crop((mid, 0, w, h))

    shifted = Image.new("RGB", (mid, h), (0, 0, 0))
    src = left.crop((0, 0, mid, h - shift_px))
    shifted.paste(src, (0, shift_px))
    # Fill top gap by repeating row 'shift_px'
    fill = left.crop((0, shift_px, mid, shift_px + 1)).resize((mid, shift_px))
    shifted.paste(fill, (0, 0))

    new = Image.new("RGB", (w, h))
    new.paste(shifted, (0, 0))
    new.paste(right, (mid, 0))

    print(f"[4] Shifted L+{shift_px}px: {new.size}")
    return new


# ============================================================
#  STEP 5: CROP RIGHT-EDGE SEAM
# ============================================================
def crop_right_seam(im, seam_col=None):
    """Detect and crop the right-edge reference seam."""
    w, h = im.size

    if seam_col is None:
        arr = np.array(im).astype(np.float32)
        col_mean = arr.mean(axis=(0, 2))
        col_delta = np.abs(np.diff(col_mean))
        start = int(w * 0.75)
        seam_col = start + int(np.argmax(col_delta[start:]))

    im = im.crop((0, 0, seam_col - 5, h))
    print(f"[5] Right-cropped: {im.size}  (seam at col {seam_col})")
    return im


# ============================================================
#  STEP 5.5: CROP TOP MCU SCANLINE
# ============================================================
def crop_top_scanline(im, scanlines=1, mcu_size=8):
    """Crop N MCU scanlines from top."""
    pixels = scanlines * mcu_size
    w, h = im.size
    im = im.crop((0, pixels, w, h))
    print(f"[5.5] Top-cropped {pixels}px: {im.size}")
    return im


# ============================================================
#  STEP 6: PHOTODEMON-STYLE AUTO-CORRECT
# ============================================================
def _clarity_lut(strength=0.35):
    """Midtone contrast S-curve LUT (256 entries)."""
    x = np.arange(256, dtype=np.float32) / 255.0
    curved = x + strength * (x - 0.5) * (1.0 - np.abs(2.0 * x - 1.0))
    return (np.clip(curved, 0, 1) * 255).astype(np.uint8)


def auto_correct(im,
                 wb_low=0.05, wb_high=99.95,
                 clarity_strength=0.35,
                 saturation=1.10):
    """
    PhotoDemon-style auto-correct:
      1. White balance (per-channel percentile stretch)
      2. Clarity (midtone contrast S-curve)
      3. Saturation boost
    """
    arr = np.array(im.convert("RGB"), dtype=np.uint8)

    # 1. White Balance
    chans = []
    for c in range(3):
        ch = arr[:, :, c]
        lo = np.percentile(ch, wb_low)
        hi = np.percentile(ch, wb_high)
        if hi <= lo:
            chans.append(ch)
        else:
            s = (ch.astype(np.float32) - lo) * (255.0 / (hi - lo))
            chans.append(np.clip(s, 0, 255).astype(np.uint8))
    arr = np.stack(chans, axis=2)

    # 2. Clarity
    lut = _clarity_lut(clarity_strength)
    arr = lut[arr]

    # 3. Saturation
    out = Image.fromarray(arr, "RGB")
    out = ImageEnhance.Color(out).enhance(saturation)

    print(f"[6] Auto-correct:  WB({wb_low}/{wb_high})  "
          f"Clarity({clarity_strength})  Sat({saturation})")
    return out


# ============================================================
#  MAIN PIPELINE
# ============================================================
def recover(encrypted_path, reference_path, output_path,
            ref_prefix=153605,
            crop_top=424, crop_bottom=60,
            shift=8,
            right_seam_col=None,
            top_scanlines=1, mcu_size=8,
            wb_low=0.05, wb_high=99.95,
            clarity_strength=0.35,
            saturation=1.10,
            quality=95,
            do_half_swap=True):
    """Run the full recovery pipeline."""

    print("=" * 55)
    print("STOP/Djvu JPEG Recovery")
    print("=" * 55)
    print(f"Encrypted: {encrypted_path}")
    print(f"Reference: {reference_path}")
    print(f"Output:    {output_path}")
    print()

    # 1-2: Splice + decode + crop top/bottom
    im = splice_and_decode(encrypted_path, reference_path,
                           ref_prefix=ref_prefix,
                           crop_top=crop_top,
                           crop_bottom=crop_bottom)

    # 3: Optional half-swap
    if do_half_swap:
        im = half_swap(im)

    # 4: Shift left half down
    if shift > 0:
        im = shift_left_half_down(im, shift_px=shift)
    else:
        print(f"[4] Skipped shift (shift=0)")

    # 5: Crop right seam
    im = crop_right_seam(im, seam_col=right_seam_col)

    # 5.5: Crop top scanline
    if top_scanlines > 0:
        im = crop_top_scanline(im, scanlines=top_scanlines, mcu_size=mcu_size)

    # 6: Auto color
    im = auto_correct(im,
                      wb_low=wb_low, wb_high=wb_high,
                      clarity_strength=clarity_strength,
                      saturation=saturation)

    # Save
    im.save(output_path, quality=quality)
    print(f"\n\u2714 Saved: {output_path}  ({im.size})")
    return im


# ============================================================
#  AUTO-DETECT HELPERS
# ============================================================
def auto_ref_prefix(encrypted_path):
    """Choose ref_prefix based on file size."""
    size = os.path.getsize(encrypted_path)
    return 153605 if size < 50 * 1024 * 1024 else 5242880


def auto_mcu_size(reference_path):
    """Detect MCU size from reference JPEG SOF marker."""
    ref = open(reference_path, "rb").read()
    best = (8, None)  # (mcu_size, total_pixels)

    for marker in (0xC0, 0xC1, 0xC2, 0xC3):
        start = 0
        while True:
            idx = ref.find(bytes([0xFF, marker]), start)
            if idx < 0:
                break
            try:
                h = (ref[idx + 5] << 8) | ref[idx + 6]
                w = (ref[idx + 7] << 8) | ref[idx + 8]
                n = ref[idx + 9]

                hmax = vmax = 0
                for c in range(n):
                    samp = ref[idx + 10 + c * 3 + 1]
                    hmax = max(hmax, samp >> 4)
                    vmax = max(vmax, samp & 0x0F)

                mcu = 8 * max(hmax, vmax)
                pixels = w * h

                if best[1] is None or pixels > best[1]:
                    best = (mcu, pixels)
            except Exception:
                pass
            start = idx + 2

    return best[0]


# ============================================================
#  CLI
# ============================================================
def main():
    ap = argparse.ArgumentParser(
        description="STOP/Djvu JPEG Recovery Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Auto-detect all parameters
    python3 recover.py encrypted.nppp reference.JPG output.jpg

    # Canon 6000x4000 (4:2:2)
    python3 recover.py IMG_4054.JPG.nppp IMG_4312.JPG out.jpg --mcu-size 16

    # No half-swap (if composition already correct)
    python3 recover.py enc.nppp ref.jpg out.jpg --no-swap
        """)

    ap.add_argument("encrypted", help="STOP/Djvu encrypted file (.nppp, .djvu, etc.)")
    ap.add_argument("reference", help="Clean same-camera JPEG")
    ap.add_argument("output", help="Output JPEG path")

    # Auto-detection
    ap.add_argument("--no-auto", action="store_true",
                    help="Disable auto-detection of ref-prefix and MCU size")

    # Pipeline parameters
    ap.add_argument("--ref-prefix", type=int, default=None,
                    help="Reference warm-up bytes (auto: 153605 or 5242880)")
    ap.add_argument("--crop-top", type=int, default=424,
                    help="Pixels to crop from top (default: 424)")
    ap.add_argument("--crop-bottom", type=int, default=60,
                    help="Pixels to crop from bottom (default: 60)")
    ap.add_argument("--shift", type=int, default=8,
                    help="Left-half shift in pixels (default: 8, use 0 to skip)")
    ap.add_argument("--right-seam", type=int, default=None,
                    help="Right seam column (auto-detect if omitted)")
    ap.add_argument("--top-scanlines", type=int, default=1,
                    help="MCU scanlines to crop from top (default: 1)")
    ap.add_argument("--mcu-size", type=int, default=None,
                    help="MCU size: 8 (4:4:4) or 16 (4:2:0/4:2:2). Auto-detect if omitted.")
    ap.add_argument("--no-swap", action="store_true",
                    help="Skip half-swap step")

    # Color correction
    ap.add_argument("--wb-low", type=float, default=0.05,
                    help="White-balance low percentile (default: 0.05)")
    ap.add_argument("--wb-high", type=float, default=99.95,
                    help="White-balance high percentile (default: 99.95)")
    ap.add_argument("--clarity", type=float, default=0.35,
                    help="Midtone contrast strength (default: 0.35)")
    ap.add_argument("--saturation", type=float, default=1.10,
                    help="Saturation factor (default: 1.10)")
    ap.add_argument("--quality", type=int, default=95,
                    help="Output JPEG quality (default: 95)")

    args = ap.parse_args()

    # Auto-detect parameters
    ref_prefix = args.ref_prefix
    mcu_size = args.mcu_size

    if not args.no_auto:
        if ref_prefix is None:
            ref_prefix = auto_ref_prefix(args.encrypted)
            print(f"[auto] ref_prefix: {ref_prefix}")
        if mcu_size is None:
            mcu_size = auto_mcu_size(args.reference)
            print(f"[auto] MCU size:   {mcu_size}")
        print()

    if ref_prefix is None:
        ref_prefix = 153605
    if mcu_size is None:
        mcu_size = 8

    recover(
        encrypted_path=args.encrypted,
        reference_path=args.reference,
        output_path=args.output,
        ref_prefix=ref_prefix,
        crop_top=args.crop_top,
        crop_bottom=args.crop_bottom,
        shift=args.shift,
        right_seam_col=args.right_seam,
        top_scanlines=args.top_scanlines,
        mcu_size=mcu_size,
        wb_low=args.wb_low,
        wb_high=args.wb_high,
        clarity_strength=args.clarity,
        saturation=args.saturation,
        quality=args.quality,
        do_half_swap=not args.no_swap,
    )


if __name__ == "__main__":
    main()
