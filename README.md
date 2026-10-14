# STOP/Djvu JPEG Recovery Tool — PyQt6 GUI

A graphical recovery tool for JPEG photos encrypted by **STOP/Djvu ransomware**, using a same-camera clean JPEG as a decoder warm-up reference.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![PyQt6](https://img.shields.io/badge/PyQt6-6.5+-green)
![License](https://img.shields.io/badge/license-MIT-orange)

> **⚠️ Not a decryption tool.** Full decryption requires the attacker's RSA private key. This tool exploits STOP/Djvu's fixed encryption boundary (153,605 bytes for files under 50 MB) to recover the majority of an encrypted image.

---

## 📋 Table of Contents

- [Features](#-features)
- [Screenshots](#-screenshots)
- [Requirements](#-requirements)
- [Installation](#-installation)
- [Quick Start](#-quick-start)
- [GUI Walkthrough](#-gui-walkthrough)
- [Parameter Reference](#-parameter-reference)
- [Batch Mode](#-batch-mode)
- [How It Works](#-how-it-works)
- [Troubleshooting](#-troubleshooting)
- [Compatibility](#-compatibility)
- [Case Studies](#-case-studies)
- [Security Checklist](#-security-checklist)
- [Technical Background](#-technical-background)
- [License](#-license)

---

## ✨ Features

| Feature | Description |
|---|---|
| **Non-blocking UI** | Recovery runs in a worker thread — interface stays responsive |
| **Live preview** | Reference and recovered output shown side-by-side |
| **Color-coded log** | Step-by-step pipeline progress in a dedicated tab |
| **Auto-detect** | MCU size and encryption boundary detected automatically |
| **Batch mode** | Process an entire folder of `.nppp` files |
| **All parameters adjustable** | Crops, shift, WB, clarity, saturation — via spinboxes |
| **Dark theme** | Eye-friendly, easy on long sessions |
| **Cross-platform** | Linux, macOS, Windows |
| **Reset to defaults** | One click restores known-good parameter set |

---

## 🖼 Screenshots

<img width="2444" height="1704" alt="image" src="https://github.com/user-attachments/assets/26821dc9-34c5-4286-a181-5cbbe02829e0" />

---

## 📦 Requirements

- **Python 3.10+**
- **PyQt6** — GUI framework
- **Pillow** — JPEG decoding and image manipulation
- **NumPy** — array operations

---

## 🔧 Installation

### 1. Create a virtual environment

```bash
cd ~/Pictures
python3 -m venv venv
source venv/bin/activate     # Linux/macOS
# venv\Scripts\activate      # Windows
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the GUI

```bash
python3 recover_gui.py
```

### Ubuntu 24.04+ — Faster install (avoids slow PyQt6 download)

```bash
# Install PyQt6 and image libraries system-wide
sudo apt install python3-pyqt6 python3-numpy python3-pil

# Reuse system packages in venv
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r requirements.txt   # only installs what's missing
```

### Linux — Missing Qt platform plugin

If you see `qt.qpa.plugin: Could not load the Qt platform plugin "xcb"`:

```bash
sudo apt install libxcb-cursor0 libxcb-xinerama0
```

On Wayland:

```bash
export QT_QPA_PLATFORM=wayland
python3 recover_gui.py
```

---

## 🚀 Quick Start

```bash
cd ~/Pictures
source venv/bin/activate
python3 recover_gui.py
```

Then in the GUI:

1. **Encrypted file** → browse to `_NHL0591.JPG.nppp`
2. **Reference** → browse to `_NHL0592.JPG`
3. **Output** → auto-filled, adjust if needed
4. Click **▶ Run Recovery**
5. Check the **Log** tab for progress
6. View result in the **Preview** tab

---

## 🖥 GUI Walkthrough

### Files Section (top)

| Field | Purpose |
|---|---|
| **Encrypted file** | The `.nppp` / `.djvu` / `.gero` / `.nnuz` / `.bbbb` file to recover |
| **Reference** | A clean same-camera JPEG (must be different photo, same device) |
| **Output** | Where to save the recovered image (auto-filled as `<name>_RECOVERED.jpg`) |

### Parameters Panel (left)

#### Auto-Detection Group

| Option | Default | Description |
|---|---|---|
| **Enable auto-detection** | ✅ On | Detects `ref_prefix` (from file size) and `MCU size` (from reference SOF marker) |
| **Apply half-swap** | ✅ On | Swaps left/right halves to correct composition |

#### Crop Parameters Group

| Parameter | Default | Description |
|---|---|---|
| **Ref prefix** | `153605` | Bytes of reference used as decoder warm-up |
| **Crop top** | `424` | Pixels to remove from top (reference bleed) |
| **Crop bottom** | `60` | Pixels to remove from bottom (white EOF fill) |
| **Left-half shift** | `8` | Vertical alignment shift in pixels |
| **MCU size** | `8` | `8` for 4:4:4, `16` for 4:2:0 / 4:2:2 |
| **Top scanlines** | `1` | MCU rows to crop from top |
| **Right seam** | `0` (Auto) | Manual column override for right crop |

#### Color Correction Group

| Parameter | Default | Description |
|---|---|---|
| **WB low percentile** | `0.05` | Lower clip for white balance |
| **WB high percentile** | `99.95` | Upper clip for white balance |
| **Clarity strength** | `0.35` | Midtone contrast (0.0–1.0) |
| **Saturation** | `1.10` | Color boost (1.0 = no change) |
| **JPEG quality** | `95` | Output quality |

### Preview / Log / Batch Tabs (right)

- **Preview** — Side-by-side reference and output images
- **Log** — Live pipeline progress (auto-scrolls)
- **Batch** — Folder-based batch processing

### Bottom Bar

- **▶ Run Recovery** — Start the pipeline
- **Progress bar** — Shows 0–100% completion

### Toolbar

- **Load Batch Folder** — Quick access to batch mode
- **Clear Log** — Wipes the log panel

---

## ⚙️ Parameter Reference

### MCU Size Selection

| Chroma Subsampling | MCU Size | Typical Cameras |
|---|---|---|
| **4:4:4** | 8 | Higher-end compacts, some DSLRs |
| **4:2:2** | 16 | Canon DSLRs (default JPEG) |
| **4:2:0** | 16 | Most phones, consumer cameras |

**Auto-detect** parses the reference's SOF marker to determine this. If auto-detect fails, set manually.

### Encrypted Region Size

| File size | Bytes encrypted (ref prefix) |
|---|---|
| **< 50 MB** | `153605` |
| **≥ 50 MB** | `5242880` |

### Crop Tuning Guide

| Camera / Resolution | Typical crop-top | Typical shift |
|---|---|---|
| 3888×2592 (4:4:4) | 400–500 | 8 |
| 6000×4000 (4:2:2) | 550–700 | 16 |
| 4000×3000 (4:2:0) | 400–600 | 16 |

If reference content still bleeds at the top after running, **increase crop-top by 50–100** and retry.

---

## 🔄 Batch Mode

### Via GUI

1. Click the **Batch** tab
2. Click **Browse...** and select the folder containing `.nppp` files
3. Ensure the **Reference** field in the Files section is filled
4. Click **Run Batch**
5. Output goes to `[folder]/recovered/`

### Via CLI (equivalent)

```bash
mkdir -p recovered
for enc in *.JPG.nppp; do
    base="${enc%.nppp}"
    python3 recover_gui.py --cli "$enc" reference.JPG "recovered/${base}_RECOVERED.jpg"
done
```

*(The GUI has no CLI mode, but `recover.py` from the CLI version works fine for scripts.)*

---

## 🧠 How It Works

STOP/Djvu encrypts files with a **fixed-size prefix**:

```
[encrypted: bytes 0..153605]  [untouched scan data: 153605..end]
```

The encrypted region contains:
- The JPEG header tables (Huffman, quantization)
- The first ~150 KB of scan data (top portion of image)

Because JPEG decoding is **stateful**, we can't just start reading mid-stream. Solution:

1. **Splice** — Reference file's first 153,605 bytes + encrypted file's surviving data
2. **Decode** — JPEG decoder warms up on reference, then continues into your data
3. **Crop** — Remove reference bleed at top, white fill at bottom
4. **Align** — Half-swap + shift to match composition
5. **Color correct** — Percentile WB + clarity S-curve + saturation

**Result:** A viewable JPEG containing the majority of your original photo, minus the top portion.

---

## 🐛 Troubleshooting

### GUI won't start

```bash
python3 -c "from PyQt6.QtWidgets import QApplication; print('PyQt6 OK')"
```

If it fails:
```bash
pip install --force-reinstall PyQt6
```

### `qt.qpa.plugin: Could not load the Qt platform plugin`

```bash
sudo apt install libxcb-cursor0 libxcb-xinerama0
# or
export QT_QPA_PLATFORM=xcb
```

### `UnidentifiedImageError: cannot identify image file`

- Wrong `ref_prefix` — try `100000`, `150000`, `155000`
- Wrong reference — must be same camera
- File ≥ 50 MB — enable larger ref_prefix (`5242880`)

### Image is too dark / has color cast

- Lower **Clarity** to `0.2` for a flatter look
- Set **Saturation** to `1.0` for no boost
- Lower **WB high** to `99.5` for cooler result
- Raise **WB low** to `0.5` for stronger white balance

### Horizontal seam (left↔right misaligned)

- Adjust **Left-half shift**: try `0`, `4`, `8`, `16`, `24`

### Reference content still visible

- Right side → increase **crop-right** manually (set **Right seam**)
- Left side → rerun with lower **crop-left** (modify `recover_gui.py`)

### Worker thread crashes

The **Log** tab shows the full traceback. Common causes:
- Reference JPEG is corrupt
- Output path is not writable
- File is not a STOP/Djvu-encrypted JPEG

---

## 📊 Compatibility

| Case | Works? | Notes |
|---|---|---|
| STOP/Djvu JPEG (`.nppp`, `.djvu`, `.gero`, `.nnuz`) | ✅ | Same-camera reference required |
| STOP/Djvu < 50 MB | ✅ | `ref_prefix = 153605` |
| STOP/Djvu ≥ 50 MB | ✅ | `ref_prefix = 5242880` |
| STOP/Djvu PNG / RAW / HEIC | ❌ | Not JPEG format |
| Other ransomware (LockBit, Conti, etc.) | ❌ | Different crypto scheme |
| Camera-deleted JPEG (no ransomware) | ✅ | Use `photorec` / `testdisk` instead |

---

## 📚 Case Studies

### Case 1 — Canon 3888×2592 (4:4:4)

| Parameter | Value |
|---|---|
| Encrypted | `_NHL0591.JPG.nppp` (3.26 MB) |
| Reference | `_NHL0592.JPG` |
| MCU size | 8 (4:4:4) |
| Crop top | 424 |
| Crop bottom | 60 |
| Shift | 8 |

**Result:** 3570 × 2100 recovered image with correct color.

### Case 2 — Canon 6000×4000 (4:2:2)

| Parameter | Value |
|---|---|
| Encrypted | `IMG_4054.JPG.nppp` (11.26 MB) |
| Reference | `IMG_4312.JPG` |
| MCU size | 16 (4:2:2) |
| Crop top | 600 |
| Crop bottom | 90 |
| Shift | 16 |

**Result:** Recovered with correct composition, needed manual right-edge crop because reference content bled into one side.

---

## 🔐 Security Checklist

If you've been infected with STOP/Djvu:

1. **Disconnect** the infected machine from the network
2. **Do NOT pay** the ransom — recovery is possible with the right approach
3. **Preserve** all `.nppp` files and `_readme.txt`
4. **Check `_readme.txt`** for the Personal ID — if it ends in `t1`, an offline key may exist
5. **Run the official Emsisoft decryptor**: https://www.emsisoft.com/en/business/download/stop-djvu/
6. **Scan** the machine with Malwarebytes or Emsisoft Emergency Kit
7. **Change passwords** for all accounts accessed from the infected machine
8. **Enable backups** (File History, Time Machine, cloud sync)
9. **Keep encrypted originals** — for potential future decryption

---

## 🧪 Technical Background

### Why 153,605 bytes?

`0x25805` = 153,605 — the exact byte count STOP/Djvu encrypts for files under 50 MB.

### Why same-camera reference?

JPEG headers contain **Huffman tables** and **quantization tables** specific to the camera model. These must match between reference and encrypted file, or scan data won't decode.

### Why can't we decrypt directly?

File content is encrypted with **Salsa20** using a per-file random key. That key is encrypted with the attacker's **RSA-2048** public key and appended to the file. Without the private key, RSA can't be reversed.

### Why is the top of the image lost?

The top portion of the JPEG was within the first 153,605 bytes — overwritten by the Salsa20 keystream. Mathematically unrecoverable without decryption.

---

## 📁 File Structure

```
~/Pictures/
├── recover_gui.py          # GUI application (main file)
├── recover.py              # CLI version (optional)
├── requirements.txt        # Python dependencies
├── README.md               # This file
├── _NHL0591.JPG.nppp       # Encrypted original — keep forever
├── _NHL0592.JPG            # Reference
└── recovered/              # Batch output folder
```

---

## 🙏 Credits

- **Emsisoft** — public STOP/Djvu research and decryptor tools
- **PhotoDemon** — auto-correct algorithm inspiration
- **Qt / PyQt6** — GUI framework
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
4. **Do not pay** the ransom — recovery is possible
