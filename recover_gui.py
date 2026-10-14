#!/usr/bin/env python3
"""
recover_gui.py - STOP/Djvu JPEG Recovery Tool (PyQt6 GUI)

A graphical front-end for the STOP/Djvu JPEG recovery pipeline.

Features:
  - File pickers for encrypted file, reference, and output
  - All pipeline parameters adjustable via GUI
  - Live preview of input reference
  - Before/after image comparison
  - Log output panel
  - Batch mode (process entire folder)
  - Worker thread (non-blocking UI)
  - Auto-detect MCU size and ref_prefix

Requirements:
    PyQt6
    Pillow
    numpy

Usage:
    python3 recover_gui.py
"""

import os
import sys
import traceback
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFile

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QIcon, QFont, QAction
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QFileDialog, QSpinBox, QDoubleSpinBox,
    QCheckBox, QGroupBox, QFormLayout, QTextEdit, QProgressBar,
    QTabWidget, QSplitter, QMessageBox, QScrollArea, QComboBox,
    QStatusBar, QToolBar, QListWidget, QListWidgetItem,
)

ImageFile.LOAD_TRUNCATED_IMAGES = True


# ============================================================
#  CORE RECOVERY PIPELINE
# ============================================================
def auto_ref_prefix(encrypted_path):
    """Choose ref_prefix based on file size."""
    size = os.path.getsize(encrypted_path)
    return 153605 if size < 50 * 1024 * 1024 else 5242880


def auto_mcu_size(reference_path):
    """Detect MCU size from reference JPEG SOF marker."""
    ref = open(reference_path, "rb").read()
    best = (8, None)
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
                    s = ref[idx + 10 + c * 3 + 1]
                    hmax = max(hmax, s >> 4)
                    vmax = max(vmax, s & 0x0F)
                mcu = 8 * max(hmax, vmax)
                pixels = w * h
                if best[1] is None or pixels > best[1]:
                    best = (mcu, pixels)
            except Exception:
                pass
            start = idx + 2
    return best[0]


def _clarity_lut(strength=0.35):
    """Midtone contrast S-curve LUT."""
    x = np.arange(256, dtype=np.float32) / 255.0
    curved = x + strength * (x - 0.5) * (1.0 - np.abs(2.0 * x - 1.0))
    return (np.clip(curved, 0, 1) * 255).astype(np.uint8)


def splice_and_decode(encrypted_path, reference_path,
                      ref_prefix=153605,
                      crop_top=424, crop_bottom=60,
                      log=print):
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
    log(f"[1] Decoded:       {w}x{h}")

    im = im.crop((0, crop_top, w, h - crop_bottom))
    log(f"[2] Cropped:       {im.size}")
    return im


def half_swap(im, log=print):
    w, h = im.size
    mid = w // 2
    left = im.crop((0, 0, mid, h))
    right = im.crop((mid, 0, w, h))
    new = Image.new("RGB", (w, h))
    new.paste(right, (0, 0))
    new.paste(left, (right.width, 0))
    log(f"[3] Half-swapped:  {new.size}")
    return new


def shift_left_half_down(im, shift_px=8, log=print):
    w, h = im.size
    mid = w // 2
    left = im.crop((0, 0, mid, h))
    right = im.crop((mid, 0, w, h))
    shifted = Image.new("RGB", (mid, h), (0, 0, 0))
    src = left.crop((0, 0, mid, h - shift_px))
    shifted.paste(src, (0, shift_px))
    fill = left.crop((0, shift_px, mid, shift_px + 1)).resize((mid, shift_px))
    shifted.paste(fill, (0, 0))
    new = Image.new("RGB", (w, h))
    new.paste(shifted, (0, 0))
    new.paste(right, (mid, 0))
    log(f"[4] Shifted L+{shift_px}px: {new.size}")
    return new


def crop_right_seam(im, seam_col=None, log=print):
    w, h = im.size
    if seam_col is None:
        arr = np.array(im).astype(np.float32)
        col_mean = arr.mean(axis=(0, 2))
        col_delta = np.abs(np.diff(col_mean))
        start = int(w * 0.75)
        seam_col = start + int(np.argmax(col_delta[start:]))
    im = im.crop((0, 0, seam_col - 5, h))
    log(f"[5] Right-cropped: {im.size}  (seam at col {seam_col})")
    return im


def crop_top_scanline(im, scanlines=1, mcu_size=8, log=print):
    pixels = scanlines * mcu_size
    w, h = im.size
    im = im.crop((0, pixels, w, h))
    log(f"[5.5] Top-cropped {pixels}px: {im.size}")
    return im


def auto_correct(im,
                 wb_low=0.05, wb_high=99.95,
                 clarity_strength=0.35,
                 saturation=1.10,
                 log=print):
    arr = np.array(im.convert("RGB"), dtype=np.uint8)

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

    lut = _clarity_lut(clarity_strength)
    arr = lut[arr]

    out = Image.fromarray(arr, "RGB")
    out = ImageEnhance.Color(out).enhance(saturation)

    log(f"[6] Auto-correct:  WB({wb_low}/{wb_high})  "
        f"Clarity({clarity_strength})  Sat({saturation})")
    return out


def recover_pipeline(encrypted_path, reference_path, output_path,
                     ref_prefix=None,
                     crop_top=424, crop_bottom=60,
                     shift=8,
                     right_seam_col=None,
                     top_scanlines=1, mcu_size=None,
                     wb_low=0.05, wb_high=99.95,
                     clarity_strength=0.35,
                     saturation=1.10,
                     quality=95,
                     do_half_swap=True,
                     auto_detect=True,
                     log=print):
    """Full recovery pipeline."""

    log("=" * 55)
    log("STOP/Djvu JPEG Recovery")
    log("=" * 55)
    log(f"Encrypted: {encrypted_path}")
    log(f"Reference: {reference_path}")
    log(f"Output:    {output_path}")
    log("")

    # Auto-detect
    if auto_detect:
        if ref_prefix is None:
            ref_prefix = auto_ref_prefix(encrypted_path)
            log(f"[auto] ref_prefix: {ref_prefix}")
        if mcu_size is None:
            mcu_size = auto_mcu_size(reference_path)
            log(f"[auto] MCU size:   {mcu_size}")
        log("")

    if ref_prefix is None:
        ref_prefix = 153605
    if mcu_size is None:
        mcu_size = 8

    im = splice_and_decode(encrypted_path, reference_path,
                           ref_prefix=ref_prefix,
                           crop_top=crop_top,
                           crop_bottom=crop_bottom,
                           log=log)

    if do_half_swap:
        im = half_swap(im, log=log)

    if shift > 0:
        im = shift_left_half_down(im, shift_px=shift, log=log)
    else:
        log("[4] Skipped shift (shift=0)")

    im = crop_right_seam(im, seam_col=right_seam_col, log=log)

    if top_scanlines > 0:
        im = crop_top_scanline(im, scanlines=top_scanlines,
                               mcu_size=mcu_size, log=log)

    im = auto_correct(im,
                      wb_low=wb_low, wb_high=wb_high,
                      clarity_strength=clarity_strength,
                      saturation=saturation,
                      log=log)

    im.save(output_path, quality=quality)
    log(f"\n\u2714 Saved: {output_path}  ({im.size})")
    return im


# ============================================================
#  WORKER THREAD
# ============================================================
class RecoveryWorker(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, params):
        super().__init__()
        self.params = params

    def run(self):
        try:
            recover_pipeline(**self.params, log=self.log_signal.emit)
            self.progress_signal.emit(100)
            self.finished_signal.emit(True, self.params["output_path"])
        except Exception as e:
            self.log_signal.emit(f"\n\u274c ERROR: {e}")
            self.log_signal.emit(traceback.format_exc())
            self.finished_signal.emit(False, str(e))


# ============================================================
#  IMAGE PREVIEW WIDGET
# ============================================================
class ImagePreview(QLabel):
    """Label that displays a scaled image with aspect ratio preserved."""

    def __init__(self, placeholder="No image"):
        super().__init__()
        self.placeholder = placeholder
        self._pixmap = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(300, 200)
        self.setStyleSheet(
            "border: 1px solid #444; background: #1e1e1e; color: #888;")
        self.setText(placeholder)

    def set_image(self, path_or_image):
        try:
            if isinstance(path_or_image, (str, Path)):
                img = Image.open(str(path_or_image))
            else:
                img = path_or_image

            # Convert to QPixmap
            img_rgb = img.convert("RGB")
            w, h = img_rgb.size
            data = img_rgb.tobytes("raw", "RGB")
            from PyQt6.QtGui import QImage
            qimg = QImage(data, w, h, 3 * w, QImage.Format.Format_RGB888)
            self._pixmap = QPixmap.fromImage(qimg)
            self._update_scaled()
        except Exception as e:
            self.setText(f"Failed to load: {e}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scaled()

    def _update_scaled(self):
        if self._pixmap is None:
            return
        scaled = self._pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.setPixmap(scaled)


# ============================================================
#  MAIN WINDOW
# ============================================================
class RecoveryWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("STOP/Djvu JPEG Recovery Tool")
        self.setMinimumSize(1200, 800)
        self.worker = None

        self._build_ui()
        self._apply_dark_theme()

    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow { background: #2b2b2b; }
            QWidget { color: #e0e0e0; font-size: 10pt; }
            QGroupBox {
                border: 1px solid #444; border-radius: 5px;
                margin-top: 10px; padding-top: 8px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 10px;
                padding: 0 5px; color: #4ea1ff;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
                background: #1e1e1e; color: #e0e0e0;
                border: 1px solid #555; border-radius: 3px;
                padding: 4px; min-height: 20px;
            }
            QPushButton {
                background: #3a3a3a; color: #e0e0e0;
                border: 1px solid #555; border-radius: 4px;
                padding: 6px 14px; min-height: 22px;
            }
            QPushButton:hover { background: #4a4a4a; }
            QPushButton:pressed { background: #2a2a2a; }
            QPushButton#runBtn {
                background: #2d7d46; color: white;
                font-weight: bold; font-size: 11pt;
                min-height: 34px;
            }
            QPushButton#runBtn:hover { background: #3a9c58; }
            QPushButton#runBtn:disabled { background: #444; color: #888; }
            QTextEdit {
                background: #1e1e1e; color: #c8e6c9;
                border: 1px solid #444; border-radius: 3px;
                font-family: monospace; font-size: 9pt;
            }
            QProgressBar {
                border: 1px solid #555; border-radius: 3px;
                text-align: center; background: #1e1e1e;
            }
            QProgressBar::chunk { background: #2d7d46; }
            QTabWidget::pane { border: 1px solid #444; }
            QTabBar::tab {
                background: #3a3a3a; color: #ccc;
                padding: 6px 16px; border: 1px solid #444;
            }
            QTabBar::tab:selected { background: #2d7d46; color: white; }
            QStatusBar { background: #1e1e1e; color: #aaa; }
        """)

    def _build_ui(self):
        # Toolbar
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        act_load = QAction("Load Batch Folder", self)
        act_load.triggered.connect(self._pick_batch_folder)
        toolbar.addAction(act_load)

        act_clear = QAction("Clear Log", self)
        act_clear.triggered.connect(lambda: self.log_view.clear())
        toolbar.addAction(act_clear)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # Top: file selection
        main_layout.addWidget(self._build_file_section())

        # Middle: two-column (params | previews + log)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: parameters
        left_panel = self._build_params_panel()
        splitter.addWidget(left_panel)

        # Right: previews + log tabs
        right_panel = QTabWidget()
        right_panel.addTab(self._build_preview_tab(), "Preview")
        right_panel.addTab(self._build_log_tab(), "Log")
        right_panel.addTab(self._build_batch_tab(), "Batch")
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        main_layout.addWidget(splitter, stretch=1)

        # Bottom: run button + progress
        bottom = QHBoxLayout()
        self.run_btn = QPushButton("\u25b6  Run Recovery")
        self.run_btn.setObjectName("runBtn")
        self.run_btn.clicked.connect(self._run_recovery)
        bottom.addWidget(self.run_btn, stretch=3)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        bottom.addWidget(self.progress, stretch=2)

        main_layout.addLayout(bottom)

        # Status bar
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")

    def _build_file_section(self):
        box = QGroupBox("Files")
        layout = QFormLayout(box)

        # Encrypted file
        row = QHBoxLayout()
        self.enc_path = QLineEdit()
        self.enc_path.setPlaceholderText("Select the .nppp / .djvu encrypted file...")
        btn_enc = QPushButton("Browse...")
        btn_enc.clicked.connect(self._pick_encrypted)
        row.addWidget(self.enc_path, stretch=1)
        row.addWidget(btn_enc)
        layout.addRow("Encrypted file:", row)

        # Reference file
        row = QHBoxLayout()
        self.ref_path = QLineEdit()
        self.ref_path.setPlaceholderText("Select a clean same-camera JPEG...")
        btn_ref = QPushButton("Browse...")
        btn_ref.clicked.connect(self._pick_reference)
        row.addWidget(self.ref_path, stretch=1)
        row.addWidget(btn_ref)
        layout.addRow("Reference:", row)

        # Output file
        row = QHBoxLayout()
        self.out_path = QLineEdit()
        self.out_path.setPlaceholderText("Output path (auto-filled if empty)...")
        btn_out = QPushButton("Browse...")
        btn_out.clicked.connect(self._pick_output)
        row.addWidget(self.out_path, stretch=1)
        row.addWidget(btn_out)
        layout.addRow("Output:", row)

        return box

    def _build_params_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        # Auto-detect group
        grp_auto = QGroupBox("Auto-Detection")
        form = QFormLayout(grp_auto)

        self.chk_auto = QCheckBox("Enable auto-detection")
        self.chk_auto.setChecked(True)
        form.addRow(self.chk_auto)

        self.chk_swap = QCheckBox("Apply half-swap")
        self.chk_swap.setChecked(True)
        form.addRow(self.chk_swap)

        layout.addWidget(grp_auto)

        # Crop group
        grp_crop = QGroupBox("Crop Parameters")
        form = QFormLayout(grp_crop)

        self.sp_ref_prefix = QSpinBox()
        self.sp_ref_prefix.setRange(0, 100_000_000)
        self.sp_ref_prefix.setValue(153605)
        form.addRow("Ref prefix (bytes):", self.sp_ref_prefix)

        self.sp_crop_top = QSpinBox()
        self.sp_crop_top.setRange(0, 10000)
        self.sp_crop_top.setValue(424)
        form.addRow("Crop top (px):", self.sp_crop_top)

        self.sp_crop_bottom = QSpinBox()
        self.sp_crop_bottom.setRange(0, 10000)
        self.sp_crop_bottom.setValue(60)
        form.addRow("Crop bottom (px):", self.sp_crop_bottom)

        self.sp_shift = QSpinBox()
        self.sp_shift.setRange(0, 512)
        self.sp_shift.setValue(8)
        form.addRow("Left-half shift (px):", self.sp_shift)

        self.sp_mcu = QSpinBox()
        self.sp_mcu.setRange(4, 64)
        self.sp_mcu.setValue(8)
        form.addRow("MCU size (px):", self.sp_mcu)

        self.sp_top_scanlines = QSpinBox()
        self.sp_top_scanlines.setRange(0, 20)
        self.sp_top_scanlines.setValue(1)
        form.addRow("Top scanlines:", self.sp_top_scanlines)

        self.sp_right_seam = QSpinBox()
        self.sp_right_seam.setRange(0, 100000)
        self.sp_right_seam.setValue(0)  # 0 = auto
        self.sp_right_seam.setSpecialValueText("Auto")
        form.addRow("Right seam (0=auto):", self.sp_right_seam)

        layout.addWidget(grp_crop)

        # Color group
        grp_color = QGroupBox("Color Correction")
        form = QFormLayout(grp_color)

        self.sp_wb_low = QDoubleSpinBox()
        self.sp_wb_low.setRange(0.0, 10.0)
        self.sp_wb_low.setDecimals(3)
        self.sp_wb_low.setSingleStep(0.05)
        self.sp_wb_low.setValue(0.05)
        form.addRow("WB low percentile:", self.sp_wb_low)

        self.sp_wb_high = QDoubleSpinBox()
        self.sp_wb_high.setRange(90.0, 100.0)
        self.sp_wb_high.setDecimals(3)
        self.sp_wb_high.setSingleStep(0.05)
        self.sp_wb_high.setValue(99.95)
        form.addRow("WB high percentile:", self.sp_wb_high)

        self.sp_clarity = QDoubleSpinBox()
        self.sp_clarity.setRange(0.0, 1.0)
        self.sp_clarity.setDecimals(2)
        self.sp_clarity.setSingleStep(0.05)
        self.sp_clarity.setValue(0.35)
        form.addRow("Clarity strength:", self.sp_clarity)

        self.sp_saturation = QDoubleSpinBox()
        self.sp_saturation.setRange(0.0, 3.0)
        self.sp_saturation.setDecimals(2)
        self.sp_saturation.setSingleStep(0.05)
        self.sp_saturation.setValue(1.10)
        form.addRow("Saturation:", self.sp_saturation)

        self.sp_quality = QSpinBox()
        self.sp_quality.setRange(50, 100)
        self.sp_quality.setValue(95)
        form.addRow("JPEG quality:", self.sp_quality)

        layout.addWidget(grp_color)

        # Reset button
        btn_reset = QPushButton("Reset to Defaults")
        btn_reset.clicked.connect(self._reset_params)
        layout.addWidget(btn_reset)

        layout.addStretch()

        # Wrap in a scroll area
        scroll = QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(340)
        return scroll

    def _build_preview_tab(self):
        tab = QWidget()
        layout = QHBoxLayout(tab)

        # Reference preview
        ref_box = QGroupBox("Reference JPEG")
        ref_layout = QVBoxLayout(ref_box)
        self.ref_preview = ImagePreview("Reference preview")
        ref_layout.addWidget(self.ref_preview)
        layout.addWidget(ref_box, stretch=1)

        # Output preview
        out_box = QGroupBox("Recovered Output")
        out_layout = QVBoxLayout(out_box)
        self.out_preview = ImagePreview("Recovered preview")
        out_layout.addWidget(self.out_preview)
        layout.addWidget(out_box, stretch=1)

        return tab

    def _build_log_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Monospace", 9))
        layout.addWidget(self.log_view)
        return tab

    def _build_batch_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Folder picker
        row = QHBoxLayout()
        self.batch_folder = QLineEdit()
        self.batch_folder.setPlaceholderText("Folder with .nppp files...")
        btn_pick = QPushButton("Browse...")
        btn_pick.clicked.connect(self._pick_batch_folder)
        row.addWidget(self.batch_folder, stretch=1)
        row.addWidget(btn_pick)
        layout.addLayout(row)

        # File list
        self.batch_list = QListWidget()
        layout.addWidget(QLabel("Files to process:"))
        layout.addWidget(self.batch_list, stretch=1)

        # Controls
        row = QHBoxLayout()
        btn_refresh = QPushButton("Refresh List")
        btn_refresh.clicked.connect(self._refresh_batch_list)
        row.addWidget(btn_refresh)

        self.chk_use_reference = QCheckBox("Use reference from Files section")
        self.chk_use_reference.setChecked(True)
        row.addWidget(self.chk_use_reference)

        row.addStretch()
        layout.addLayout(row)

        btn_run_batch = QPushButton("Run Batch")
        btn_run_batch.clicked.connect(self._run_batch)
        layout.addWidget(btn_run_batch)

        return tab

    # ----- Slots -----
    def _pick_encrypted(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select encrypted file",
            str(Path.home()),
            "Encrypted (*.nppp *.djvu *.gero *.nnuz *.bbbb *.jpg *.jpeg);;All files (*)")
        if path:
            self.enc_path.setText(path)
            # Auto-fill output path
            if not self.out_path.text():
                out = path
                for ext in (".nppp", ".djvu", ".gero", ".nnuz", ".bbbb"):
                    if out.endswith(ext):
                        out = out[:-len(ext)]
                        break
                self.out_path.setText(out + "_RECOVERED.jpg")

    def _pick_reference(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select reference JPEG",
            str(Path.home()),
            "JPEG (*.jpg *.jpeg *.JPG *.JPEG);;All files (*)")
        if path:
            self.ref_path.setText(path)
            self.ref_preview.set_image(path)

    def _pick_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save output as",
            str(Path.home() / "recovered.jpg"),
            "JPEG (*.jpg *.jpeg)")
        if path:
            self.out_path.setText(path)

    def _pick_batch_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select folder", str(Path.home()))
        if folder:
            self.batch_folder.setText(folder)
            self._refresh_batch_list()

    def _refresh_batch_list(self):
        self.batch_list.clear()
        folder = self.batch_folder.text()
        if not folder or not os.path.isdir(folder):
            return
        for f in sorted(os.listdir(folder)):
            if any(f.endswith(ext) for ext in
                   (".nppp", ".djvu", ".gero", ".nnuz", ".bbbb")):
                self.batch_list.addItem(f)

    def _reset_params(self):
        self.sp_ref_prefix.setValue(153605)
        self.sp_crop_top.setValue(424)
        self.sp_crop_bottom.setValue(60)
        self.sp_shift.setValue(8)
        self.sp_mcu.setValue(8)
        self.sp_top_scanlines.setValue(1)
        self.sp_right_seam.setValue(0)
        self.sp_wb_low.setValue(0.05)
        self.sp_wb_high.setValue(99.95)
        self.sp_clarity.setValue(0.35)
        self.sp_saturation.setValue(1.10)
        self.sp_quality.setValue(95)
        self.chk_auto.setChecked(True)
        self.chk_swap.setChecked(True)
        self.log_view.append("[i] Parameters reset to defaults.")

    def _log(self, msg):
        self.log_view.append(msg)
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum())

    def _build_params(self, enc, ref, out):
        """Build the parameter dict for the worker."""
        right_seam = self.sp_right_seam.value()
        return {
            "encrypted_path": enc,
            "reference_path": ref,
            "output_path": out,
            "ref_prefix": self.sp_ref_prefix.value() if not self.chk_auto.isChecked() else None,
            "crop_top": self.sp_crop_top.value(),
            "crop_bottom": self.sp_crop_bottom.value(),
            "shift": self.sp_shift.value(),
            "right_seam_col": right_seam if right_seam > 0 else None,
            "top_scanlines": self.sp_top_scanlines.value(),
            "mcu_size": self.sp_mcu.value() if not self.chk_auto.isChecked() else None,
            "wb_low": self.sp_wb_low.value(),
            "wb_high": self.sp_wb_high.value(),
            "clarity_strength": self.sp_clarity.value(),
            "saturation": self.sp_saturation.value(),
            "quality": self.sp_quality.value(),
            "do_half_swap": self.chk_swap.isChecked(),
            "auto_detect": self.chk_auto.isChecked(),
        }

    def _run_recovery(self):
        enc = self.enc_path.text().strip()
        ref = self.ref_path.text().strip()
        out = self.out_path.text().strip()

        if not enc or not os.path.isfile(enc):
            QMessageBox.warning(self, "Missing input",
                                "Please select a valid encrypted file.")
            return
        if not ref or not os.path.isfile(ref):
            QMessageBox.warning(self, "Missing reference",
                                "Please select a valid reference JPEG.")
            return
        if not out:
            QMessageBox.warning(self, "Missing output",
                                "Please specify an output path.")
            return

        params = self._build_params(enc, ref, out)
        self._start_worker(params)

    def _start_worker(self, params):
        self.log_view.clear()
        self.progress.setValue(0)
        self.run_btn.setEnabled(False)
        self.statusBar().showMessage("Running...")

        self.worker = RecoveryWorker(params)
        self.worker.log_signal.connect(self._log)
        self.worker.progress_signal.connect(self.progress.setValue)
        self.worker.finished_signal.connect(self._on_finished)
        self.worker.start()

    def _on_finished(self, success, msg):
        self.run_btn.setEnabled(True)
        if success:
            self.statusBar().showMessage(f"Done: {msg}")
            self.progress.setValue(100)
            # Load output preview
            try:
                self.out_preview.set_image(msg)
            except Exception as e:
                self._log(f"[warn] Could not preview output: {e}")
        else:
            self.statusBar().showMessage(f"Failed: {msg}")
            self.progress.setValue(0)

    def _run_batch(self):
        folder = self.batch_folder.text()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "Batch", "Select a valid folder.")
            return

        ref = self.ref_path.text().strip()
        if not ref or not os.path.isfile(ref):
            QMessageBox.warning(self, "Batch",
                                "Please set a reference JPEG in the Files section.")
            return

        files = [self.batch_list.item(i).text()
                 for i in range(self.batch_list.count())]
        if not files:
            QMessageBox.warning(self, "Batch", "No encrypted files found.")
            return

        out_dir = os.path.join(folder, "recovered")
        os.makedirs(out_dir, exist_ok=True)

        self.log_view.clear()
        self._log(f"[batch] Processing {len(files)} files into {out_dir}/")

        # Run sequentially in the UI thread with processEvents for simplicity.
        # For production, chain QThreads.
        for i, fname in enumerate(files, 1):
            enc = os.path.join(folder, fname)
            base = fname
            for ext in (".nppp", ".djvu", ".gero", ".nnuz", ".bbbb"):
                if base.endswith(ext):
                    base = base[:-len(ext)]
                    break
            out = os.path.join(out_dir, f"{base}_RECOVERED.jpg")

            self._log(f"\n[batch {i}/{len(files)}] {fname}")
            params = self._build_params(enc, ref, out)
            try:
                recover_pipeline(**params, log=self._log)
            except Exception as e:
                self._log(f"[batch] FAILED: {e}")

        self._log(f"\n[batch] Done. Output in {out_dir}/")
        QMessageBox.information(self, "Batch complete",
                                f"Processed {len(files)} files.\nOutput: {out_dir}")


# ============================================================
#  ENTRY POINT
# ============================================================
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("STOP/Djvu JPEG Recovery")
    win = RecoveryWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
