# STOP/Djvu JPEG Recovery Tool

Recover JPEG photos encrypted by **STOP/Djvu ransomware** using a same-camera clean JPEG as a decoder warm-up reference.

> **⚠️ This is not decryption.** Full decryption requires the attacker's RSA private key. This tool exploits the fact that STOP/Djvu only encrypts the **first 153,605 bytes** of small files — everything after is untouched JPEG scan data. By splicing a same-camera reference's warm-up bytes with the surviving encrypted data, we can decode the majority of the image.

---

## 📋 Table of Contents

- [How It Works](#-how-it-works)
- [Requirements](#-requirements)
- [Installation](#-installation)
- [Quick Start](#-quick-start)
- [Usage](#-usage)
- [Parameters Reference](#-parameters-reference)
- [Step-by-Step Explanation](#-step-by-step-explanation)
- [Troubleshooting](#-troubleshooting)
- [Compatibility](#-compatibility)
- [Case Studies](#-case-studies)
- [Batch Processing](#-batch-processing)
- [Security Checklist](#-security-checklist)
- [Technical Background](#-technical-background)

---

## 🧠 How It Works

STOP/Djvu ransomware uses a fixed encryption scheme:

| File size | Bytes encrypted (from start) |
|---|---|
| < 50 MB | 153,605 bytes |
| ≥ 50 MB | 5,242,880 bytes (5 MB) |

**What survives:**
- The 4-byte JPEG header (`FF D8 FF E1`) at the very start
- All scan data after the encrypted boundary

**The problem:** A JPEG decoder can't start mid-stream. It needs valid Huffman-coded MCUs at the beginning to establish state (DC prediction, bit alignment).

**The solution:** Splice the first 153,605 bytes of a **clean same-camera reference** onto the encrypted file's surviving data. The decoder warms up on the reference, then continues into the recovered data.

```
[reference 0:153605]  +  [encrypted 153605:end]
       (warm-up)              (surviving data)
              ↓
       Decodable JPEG
              ↓
       Crop + align + color-correct
              ↓
       Recovered photo
```

---

## 📦 Requirements

- **Python 3.10+**
- **Pillow** — image decoding
- **NumPy** — array operations

Optional:
- **libjpeg-turbo-progs** — for `djpeg` fallback (`sudo apt install libjpeg-turbo-progs`)

---

## 🔧 Installation

### Option 1: pip (recommended)

```bash
pip install -r requirements.txt
```

### Option 2: Ubuntu 24.04+ (system-managed Python)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Option 3: apt (dependencies only)

```bash
sudo apt install python3-pil python3-numpy
```

---

## 🚀 Quick Start

```bash
# Basic usage
python3 recover_full.py encrypted.nppp reference.JPG output.jpg

# Example
python3 recover_full.py _NHL0591.JPG.nppp _NHL0592.JPG recovered.jpg
```

### Prerequisites

Before running, you need:

1. **The encrypted file** — e.g., `IMG_4054.JPG.nppp`
2. **A clean same-camera JPEG** — must be from the **same camera model** as the encrypted file. Ideally shot in the same session or from the same device.
3. **(Optional) Ransom note** — `_readme.txt` contains the Personal ID for offline-key lookup

---

## 📖 Usage

### Single File

```bash
python3 recover_full.py <encrypted> <reference> <output>
```

### With Custom Parameters

```bash
python3 recover_full.py IMG_4054.JPG.nppp IMG_4312.JPG out.jpg \
    --mcu-size 16 \
    --crop-top 600 \
    --crop-bottom 90 \
    --shift 16
```

### Batch

```bash
mkdir -p recovered

for enc in *.JPG.nppp; do
    base="${enc%.nppp}"
    python3 recover_full.py "$enc" reference.JPG "recovered/${base}_RECOVERED.jpg"
done
```

---

## ⚙️ Parameters Reference

| Parameter | Default | Description |
|---|---|---|
| `--ref-prefix` | `153605` | Bytes of reference used as decoder warm-up |
| `--crop-top` | `424` | Pixels to crop from top (reference bleed) |
| `--crop-bottom` | `60` | Pixels to crop from bottom (white fill) |
| `--shift` | `8` | Left-half downward shift in pixels |
| `--right-seam` | auto | Manual right seam column (auto-detect if omitted) |
| `--top-scanlines` | `1` | MCU scanlines to crop from top |
| `--mcu-size` | `8` | `8` for 4:4:4, `16` for 4:2:0 / 4:2:2 |
| `--clarity` | `0.35` | Midtone contrast strength (0.0–1.0) |
| `--saturation` | `1.10` | Saturation factor (1.0 = no change) |
| `--quality` | `95` | Output JPEG quality |

### Choosing the Right Values

| Camera / Image | MCU Size | Typical Shift |
|---|---|---|
| 4:4:4 (no subsampling) | 8 | 8 |
| 4:2:2 (horizontal subsampling) | 16 | 16 |
| 4:2:0 (both subsampled) | 16 | 16 |

**Detect MCU size** with this snippet:

```python
ref = open("reference.JPG", "rb").read()
for marker in (0xC0, 0xC1, 0xC2, 0xC3):
    idx = ref.find(bytes([0xFF, marker]))
    if idx > 0:
        n = ref[idx+9]
        hmax = vmax = 0
        for c in range(n):
            s = ref[idx+10+c*3+1]
            hmax = max(hmax, s>>4)
            vmax = max(vmax, s&0xF)
        print(f"MCU: {8*max(hmax,vmax)}x{8*max(hmax,vmax)}")
```

---

## 🔬 Step-by-Step Explanation

### Step 1–2: Splice and Decode

```
[reference 0:153605] + [encrypted 153605:end]
```

The reference's first 153,605 bytes warm up the decoder. The encrypted file's surviving data supplies the actual content.

### Step 3: Half-Swap (optional)

Some cameras produce decoded output where the left/right halves are swapped. `--half-swap` fixes this.

### Step 4: Left-Half Shift

The left half of the recovered image may be off by exactly one MCU (8 or 16 pixels). Shifting it down aligns the horizontal seam.

### Step 5: Right Seam Crop

Auto-detects the vertical column where reference content (left) meets recovered content (right) and crops just past it.

### Step 5.5: Top Scanline Crop

Removes one MCU row from the top to eliminate residual bleed.

### Step 6: Auto-Correct

1. **White Balance** — independent per-channel percentile stretch (0.05% clip)
2. **Clarity** — midtone contrast S-curve
3. **Saturation** — mild boost

---

## 🐛 Troubleshooting

### `UnidentifiedImageError`

- **Wrong ref-prefix** — try `100000`, `150000`, `155000`
- **Wrong reference** — must be same camera
- **File ≥ 50 MB** — use `--ref-prefix 5242880`

### `JPEG datastream contains no image`

- The splice didn't decode — increase `--ref-prefix` to give the decoder more warm-up

### Visible seam

- **Horizontal** (top↔bottom): adjust `--shift` (`0`, `4`, `8`, `16`)
- **Vertical** (left↔right): increase `--crop-top` or specify `--right-seam`
- **Middle**: try `--top-scanlines 2` or `3`

### Too dark / color cast

- Adjust `--clarity` down to `0.2` for flatter look
- Reduce `--saturation` to `1.0`
- Lower `--wb-high` to `99.5` for cooler result

### Reference content bleeding through

- **Left bleed** → crop manually with a modified script (see Case Study 2)
- **Right bleed** → increase `--right-seam` value

---

## 📊 Compatibility

| Case | Works? | Notes |
|---|---|---|
| STOP/Djvu JPEG (`.nppp`, `.djvu`, `.gero`, `.nnuz`) | ✅ | Same-camera reference required |
| STOP/Djvu file < 50 MB | ✅ | `--ref-prefix 153605` |
| STOP/Djvu file ≥ 50 MB | ✅ | `--ref-prefix 5242880` |
| STOP/Djvu PNG / RAW / HEIC | ❌ | Not JPEG — different format |
| Non-STOP ransomware (LockBit, Conti, etc.) | ❌ | Different crypto scheme |
| Camera-deleted JPEG (no ransomware) | ✅ | Use `photorec` / `testdisk` instead |

---

## 📚 Case Studies

### Case 1: `_NHL0591.JPG.nppp` (Canon 3888×2592, 4:4:4)

**Setup:**
- Encrypted: 3.26 MB
- Reference: `_NHL0592.JPG` (portrait, same camera)
- MCU: 8×8 (4:4:4 chroma)

**Command:**
```bash
python3 recover_full.py \
    _NHL0591.JPG.nppp \
    _NHL0592.JPG \
    _NHL0591_RECOVERED_FINAL.jpg \
    --mcu-size 8 \
    --crop-top 424 \
    --crop-bottom 60 \
    --shift 8 \
    --top-scanlines 1
```

**Result:** 3570 × 2100 recovered image with correct color.

### Case 2: `IMG_4054.JPG.nppp` (Canon 6000×4000, 4:2:2)

**Setup:**
- Encrypted: 11.26 MB
- Reference: `IMG_4312.JPG` (landscape, same camera)
- MCU: 16×16 (4:2:2 chroma)

**Command:**
```bash
python3 recover_full.py \
    IMG_4054.JPG.nppp \
    IMG_4312.JPG \
    IMG_4054_RECOVERED.jpg \
    --mcu-size 16 \
    --crop-top 600 \
    --crop-bottom 90 \
    --shift 16 \
    --top-scanlines 1
```

**Note:** This case needed additional manual cropping because reference content bled into one side. See the `auto_recover_v3.py` script for flexible manual crop handling.

---

## 🔄 Batch Processing

### Bash loop

```bash
#!/bin/bash
REF="reference.JPG"
mkdir -p recovered

for enc in *.JPG.nppp; do
    base="${enc%.nppp}"
    echo "=== $enc ==="
    python3 recover_full.py "$enc" "$REF" "recovered/${base}_RECOVERED.jpg" \
        --mcu-size 16 --crop-top 600 --crop-bottom 90 --shift 16
done

ls -la recovered/
```

### Parallel (faster for many files)

```bash
ls *.JPG.nppp | xargs -P 4 -I {} bash -c '
    enc="{}"
    base="${enc%.nppp}"
    python3 recover_full.py "$enc" reference.JPG "recovered/${base}.jpg"
'
```

---

## 🔐 Security Checklist

If you've been infected with STOP/Djvu:

1. **Disconnect** the infected machine from the network immediately
2. **Do NOT pay** the ransom — paying does not guarantee recovery
3. **Preserve** all `.nppp` files and `_readme.txt` notes
4. **Check `_readme.txt`** for the Personal ID — if it ends in `t1`, an offline key may exist
5. **Run the official Emsisoft decryptor** for STOP/Djvu: https://www.emsisoft.com/en/business/download/stop-djvu/
6. **Scan the machine** with Malwarebytes or Emsisoft Emergency Kit
7. **Change passwords** for all accounts accessed from the infected machine
8. **Enable backups** (File History, Time Machine, cloud sync) going forward
9. **Keep encrypted originals** — if a key is released later, you can decrypt for a pixel-perfect copy

---

## 🧪 Technical Background

### Why 153,605 bytes?

`0x25805` = 153,605. This is the exact byte count STOP/Djvu encrypts for files < 50 MB. Files ≥ 50 MB use `0x500000` = 5,242,880 bytes.

### Why must the reference be from the same camera?

The JPEG file header contains **Huffman tables** and **quantization tables**. These must match between the reference and the encrypted file, or the scan data won't decode. Same-camera files share identical tables.

### Why can't we just decrypt?

STOP/Djvu encrypts file content with **Salsa20** using a per-file random key. That key is encrypted with the attacker's **RSA-2048** public key and appended to the file. Without the private key (held by the attacker), you can't reverse the RSA to obtain the Salsa20 key.

### Why does the top of the image end up lost?

The top portion of the JPEG was within the first 153,605 bytes — those pixels were overwritten by Salsa20 keystream. They are mathematically unrecoverable without decryption.

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
