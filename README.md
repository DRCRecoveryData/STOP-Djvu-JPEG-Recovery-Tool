# STOP/Djvu JPEG Recovery Tool

<img width="2444" height="1704" alt="image" src="https://github.com/user-attachments/assets/94d47004-cc14-4b1b-b9d7-45670c97db05" />

Recover JPEG photos encrypted by **STOP/Djvu ransomware** using a same-camera clean JPEG as a decoder warm-up reference.

> **⚠️ Not a decryption tool.** Full decryption requires the attacker's RSA private key. This tool exploits a specific weakness: STOP/Djvu only encrypts the **first 153,605 bytes** of files under 50 MB. The rest is untouched JPEG scan data. By splicing a same-camera reference's warm-up bytes with the surviving data, we can decode and recover the majority of the image.

---

## 📋 Table of Contents

- [How It Works](#-how-it-works)
- [Requirements](#-requirements)
- [Installation](#-installation)
- [Quick Start](#-quick-start)
- [Usage](#-usage)
- [Parameters Reference](#-parameters-reference)
- [Pipeline Explained](#-pipeline-explained)
- [Auto-Detection](#-auto-detection)
- [Batch Processing](#-batch-processing)
- [Troubleshooting](#-troubleshooting)
- [Compatibility](#-compatibility)
- [Case Studies](#-case-studies)
- [Technical Background](#-technical-background)
- [Security Checklist](#-security-checklist)
- [License](#-license)

---

## 🧠 How It Works

STOP/Djvu ransomware encrypts files with a predictable pattern:

| File size | Bytes encrypted (from start) |
|---|---|
| **< 50 MB** | 153,605 bytes |
| **≥ 50 MB** | 5,242,880 bytes (5 MB) |

### What Survives

- The 4-byte JPEG header (`FF D8 FF E1`)
- All scan data **after** the encrypted boundary

### The Problem

JPEG decoders cannot start mid-stream. They need valid Huffman-coded MCUs at the beginning to establish DC prediction state and bit alignment.

### The Solution

Splice the first 153,605 bytes of a **clean same-camera reference JPEG** onto the encrypted file's surviving data:

```
[reference 0:153605]  +  [encrypted 153605:end]
      (warm-up)               (surviving data)
             ↓
      Decodable JPEG
             ↓
      Crop + align + color-correct
             ↓
      Recovered photo
```

The decoder warms up on valid reference content, then continues seamlessly into the recovered data.

---

## 📦 Requirements

- **Python 3.10+**
- **Pillow** — JPEG decoding
- **NumPy** — array operations

Optional:
- **libjpeg-turbo-progs** — provides `djpeg` fallback (`sudo apt install libjpeg-turbo-progs`)

---

## 🔧 Installation

### Option 1: Virtual environment (recommended)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Option 2: System install (Ubuntu 24.04+ requires venv)

```bash
pip install --break-system-packages -r requirements.txt
```

### Option 3: apt (dependencies only)

```bash
sudo apt install python3-pil python3-numpy
```

---

## 🚀 Quick Start

```bash
python3 recover.py encrypted.nppp reference.JPG output.jpg
```

**Real example:**

```bash
python3 recover.py _NHL0591.JPG.nppp _NHL0592.JPG _NHL0591_RECOVERED.jpg
```

### Prerequisites

1. **The encrypted file** — e.g., `_NHL0591.JPG.nppp`, `IMG_4054.JPG.nppp`
2. **A clean same-camera JPEG** — must be from the **same camera model**. Ideally shot in the same session.
3. **(Optional) The ransom note** — `_readme.txt` contains the Personal ID (for offline-key lookup)

---

## 📖 Usage

### Single File

```bash
python3 recover.py <encrypted> <reference> <output>
```

### With Manual Parameters

```bash
python3 recover.py IMG_4054.JPG.nppp IMG_4312.JPG out.jpg \
    --mcu-size 16 \
    --crop-top 600 \
    --crop-bottom 90 \
    --shift 16
```

### Skip Auto-Detection

```bash
python3 recover.py enc.nppp ref.JPG out.jpg --no-auto \
    --ref-prefix 153605 --mcu-size 16
```

### Skip Half-Swap (composition already correct)

```bash
python3 recover.py enc.nppp ref.JPG out.jpg --no-swap
```

---

## ⚙️ Parameters Reference

| Parameter | Default | Description |
|---|---|---|
| `--ref-prefix` | auto | Reference warm-up bytes (`153605` or `5242880`) |
| `--crop-top` | `424` | Pixels to crop from top (reference bleed) |
| `--crop-bottom` | `60` | Pixels to crop from bottom (white EOF fill) |
| `--shift` | `8` | Left-half downward shift (use `0` to skip) |
| `--right-seam` | auto | Manual right seam column |
| `--top-scanlines` | `1` | MCU scanlines to crop from top |
| `--mcu-size` | auto | `8` (4:4:4) or `16` (4:2:0/4:2:2) |
| `--no-swap` | off | Skip the half-swap step |
| `--no-auto` | off | Disable auto-detection |
| `--wb-low` | `0.05` | White-balance low percentile |
| `--wb-high` | `99.95` | White-balance high percentile |
| `--clarity` | `0.35` | Midtone contrast strength (0.0–1.0) |
| `--saturation` | `1.10` | Saturation factor (1.0 = no change) |
| `--quality` | `95` | Output JPEG quality |

### MCU Size Selection Guide

| Chroma Subsampling | MCU Size | Typical Cameras |
|---|---|---|
| **4:4:4** (no subsampling) | 8 | Higher-end compacts, some DSLRs |
| **4:2:2** (horizontal) | 16 | Canon DSLRs (default JPEG) |
| **4:2:0** (both axes) | 16 | Most phones, consumer cameras |

---

## 🔬 Pipeline Explained

### Step 1–2: Splice and Decode

```
[reference 0:153605] + [encrypted 153605:end]
```

Reference bytes warm up the decoder. Encrypted file's surviving data supplies the actual content.

### Step 3: Half-Swap

Some cameras produce decoded output where left/right halves are swapped. This step restores correct composition.

### Step 4: Left-Half Shift

The left half may be off by exactly one MCU (8 or 16 px). Shifting it down aligns the horizontal seam.

### Step 5: Right Seam Crop

Auto-detects the vertical column where reference content meets recovered content, then crops just past it.

### Step 5.5: Top Scanline Crop

Removes one MCU row from top to eliminate residual bleed.

### Step 6: PhotoDemon-Style Auto-Correct

1. **White Balance** — independent per-channel percentile stretch (0.05% clip)
2. **Clarity** — midtone contrast S-curve via LUT
3. **Saturation** — mild boost (1.10×)

---

## 🎯 Auto-Detection

The script auto-detects two critical parameters:

### `ref_prefix` — based on file size

```python
size = os.path.getsize(encrypted_path)
ref_prefix = 153605 if size < 50*1024*1024 else 5242880
```

### `mcu_size` — from reference JPEG's SOF marker

Parses the Start-Of-Frame marker to extract chroma subsampling factors:

```
Component 1: H=2 V=1  → hmax=2, vmax=1 → MCU = 16×16 (4:2:2)
Component 1: H=2 V=2  → hmax=2, vmax=2 → MCU = 16×16 (4:2:0)
Component 1: H=1 V=1  → hmax=1, vmax=1 → MCU = 8×8  (4:4:4)
```

---

## 🔄 Batch Processing

### Bash Loop

```bash
#!/bin/bash
REF="reference.JPG"
mkdir -p recovered

for enc in *.JPG.nppp; do
    base="${enc%.nppp}"
    echo "=== $enc ==="
    python3 recover.py "$enc" "$REF" "recovered/${base}_RECOVERED.jpg"
done

ls -la recovered/
```

### Parallel (faster for many files)

```bash
ls *.JPG.nppp | xargs -P 4 -I {} bash -c '
    enc="{}"
    base="${enc%.nppp}"
    python3 recover.py "$enc" reference.JPG "recovered/${base}.jpg"
'
```

### With Per-File Parameters

```bash
# Different crops for different files
python3 recover.py IMG_4054.JPG.nppp ref.JPG out1.jpg --crop-right 2590
python3 recover.py IMG_4055.JPG.nppp ref.JPG out2.jpg --crop-right 4500
python3 recover.py IMG_4056.JPG.nppp ref.JPG out3.jpg --crop-right 4650
python3 recover.py IMG_4057.JPG.nppp ref.JPG out4.jpg --crop-left 850
```

---

## 🐛 Troubleshooting

### `UnidentifiedImageError: cannot identify image file`

**Causes:**
- Wrong `--ref-prefix` — try `100000`, `150000`, `155000`
- Wrong reference — must be same camera
- File ≥ 50 MB — use `--ref-prefix 5242880`

**Fix:**
```bash
python3 recover.py enc.nppp ref.jpg out.jpg --ref-prefix 155000
```

### `JPEG datastream contains no image`

The splice didn't decode. Increase `--ref-prefix` to give the decoder more warm-up.

### Visible Horizontal Seam

The left/right halves are misaligned vertically.

**Fix:** Adjust `--shift` (try `0`, `4`, `8`, `16`, `24`)

### Visible Vertical Seam

Reference content bleeding in from left or right.

**Fix:**
- Right bleed → increase `--right-seam` value
- Left bleed → modify script to add `--crop-left` (see manual crop section)

### Too Dark / Wrong Color

- Reduce `--clarity` to `0.2` for flatter look
- Set `--saturation 1.0` for no saturation change
- Lower `--wb-high` to `99.5` for cooler result
- Raise `--wb-low` to `0.5` for more aggressive WB

### Reference Content Still Visible

Manually crop it off with PIL:

```python
from PIL import Image
im = Image.open("output.jpg")
im = im.crop((left_crop, top_crop, right_crop, bottom_crop))
im.save("output_cropped.jpg", quality=95)
```

Find the crop coordinates visually with markers:

```python
from PIL import Image, ImageDraw
im = Image.open("output.jpg")
draw = ImageDraw.Draw(im)
for col in range(0, im.width, 500):
    draw.line([(col, 0), (col, 60)], fill=(255,0,0), width=6)
    draw.text((col+8, 15), str(col), fill=(255,0,0))
im.save("marked.jpg", quality=90)
```

---

## 📊 Compatibility

| Case | Works? | Notes |
|---|---|---|
| STOP/Djvu JPEG (`.nppp`, `.djvu`, `.gero`, `.nnuz`) | ✅ | Same-camera reference required |
| STOP/Djvu < 50 MB | ✅ | `--ref-prefix 153605` |
| STOP/Djvu ≥ 50 MB | ✅ | `--ref-prefix 5242880` |
| STOP/Djvu PNG / RAW / HEIC | ❌ | Not JPEG format |
| Non-STOP ransomware (LockBit, Conti, etc.) | ❌ | Different crypto scheme |
| Camera-deleted JPEG (no ransomware) | ✅ | Use `photorec` / `testdisk` instead |

---

## 📚 Case Studies

### Case 1: `_NHL0591.JPG.nppp` — Canon 3888×2592, 4:4:4

**Setup:**
| Parameter | Value |
|---|---|
| Encrypted size | 3.26 MB |
| Reference | `_NHL0592.JPG` (portrait) |
| MCU size | 8×8 (4:4:4) |

**Command:**
```bash
python3 recover.py \
    _NHL0591.JPG.nppp \
    _NHL0592.JPG \
    _NHL0591_RECOVERED.jpg
```

**Result:** 3570 × 2100 recovered image with correct color.

### Case 2: `IMG_4054.JPG.nppp` — Canon 6000×4000, 4:2:2

**Setup:**
| Parameter | Value |
|---|---|
| Encrypted size | 11.26 MB |
| Reference | `IMG_4312.JPG` (landscape) |
| MCU size | 16×16 (4:2:2) |

**Command:**
```bash
python3 recover.py \
    IMG_4054.JPG.nppp \
    IMG_4312.JPG \
    IMG_4054_RECOVERED.jpg \
    --mcu-size 16 \
    --crop-top 600 \
    --crop-bottom 90 \
    --shift 16
```

**Note:** This case needed additional manual cropping because reference content bled into one side. See the `--crop-left`/`--crop-right` examples.

---

## 🧪 Technical Background

### Why 153,605 bytes?

`0x25805` = 153,605. This is the exact byte count STOP/Djvu encrypts for files under 50 MB. Files ≥ 50 MB use `0x500000` = 5,242,880 bytes.

### Why must the reference be same-camera?

The JPEG file header contains **Huffman tables** and **quantization tables**. These must match between reference and encrypted file, or the scan data won't decode. Same-camera files share identical tables.

### Why can't we just decrypt?

STOP/Djvu encrypts file content with **Salsa20** using a per-file random key. That key is encrypted with the attacker's **RSA-2048** public key and appended to the file. Without the private key (held by the attacker), you can't reverse the RSA to get the Salsa20 key.

### Why is the top of the image lost?

The top portion of the JPEG was within the first 153,605 bytes — those pixels were overwritten by Salsa20 keystream. They are mathematically unrecoverable without decryption.

### Why does the reference need to be a DIFFERENT photo?

If the reference were the same photo as the encrypted file, the splice would produce the original — but the reference itself would have to be an unencrypted copy of the same file. That's a contradiction — if you had an unencrypted copy, you wouldn't need recovery.

---

## 🔐 Security Checklist

If you've been infected with STOP/Djvu:

1. **Disconnect** the infected machine from the network immediately
2. **Do NOT pay** the ransom — paying does not guarantee recovery
3. **Preserve** all `.nppp` files and `_readme.txt` notes
4. **Check `_readme.txt`** for the Personal ID — if it ends in `t1`, an offline key may exist
5. **Run the official Emsisoft decryptor**: https://www.emsisoft.com/en/business/download/stop-djvu/
6. **Scan the machine** with Malwarebytes or Emsisoft Emergency Kit
7. **Change passwords** for all accounts accessed from the infected machine
8. **Enable backups** (File History, Time Machine, cloud sync)
9. **Keep encrypted originals** — if a key is released later, you can decrypt for a pixel-perfect copy

---

## 📁 Output Files

After recovery you should have:

| File | Purpose |
|---|---|
| `output.jpg` | ✅ Recovered photo |
| `encrypted.nppp` | 🔒 Encrypted original — **keep forever** |
| `reference.JPG` | 🔒 Same-camera reference — keep if more files need recovery |

**Keep the encrypted `.nppp` file indefinitely.** If Emsisoft releases a decryption key for your variant, you can decrypt it for a pixel-perfect original.

---

## 🎯 Summary

This tool provides a **practical recovery path** for STOP/Djvu-encrypted JPEG files when no decryption key is available. It's not a perfect solution — the top portion of each image is permanently lost — but it recovers the majority of your photos in a matter of seconds.

**Key takeaways:**

- Same-camera reference is **mandatory**
- Faster than waiting for a decryption key
- Works for any JPEG encrypted by STOP/Djvu
- No network access required (runs fully offline)

---

## 🙏 Credits

- **Emsisoft** — public STOP/Djvu research and decryptor tools
- **PhotoDemon** — auto-correct algorithm inspiration
- **JPEG-Repair-Tool community** — MCU repair techniques

---

## 📜 License

MIT — free to use, modify, and distribute. No warranty.

---

## 💬 Support

If this tool helps you recover files:

1. **Back up** your recovered images immediately
2. **Report** your case to Emsisoft for future decryption research
3. **Share** the tool with others facing similar infections
4. **Do not pay** the ransom — recovery is possible with the right approach
