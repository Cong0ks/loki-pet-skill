# -*- coding: utf-8 -*-
"""
表情工坊 — 把视频转换成透明背景的 PNG 帧序列表情,并提供管理面板。

转换原理: 以画面边界像素中位数为背景色,只抠除与边界连通的背景区域;
角色内部与背景同色的部分(白发/白衣)被描边隔开,完整保留,清晰度无损。
也可作为命令行使用: python emote_studio.py <视频路径> [表情名]
"""
import json
import re
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QMessageBox, QProgressBar, QPushButton, QVBoxLayout,
)

BASE_DIR = Path(__file__).resolve().parent
EMOTES_DIR = BASE_DIR / "assets" / "emotes"

VIDEO_FILTER = "视频文件 (*.mp4 *.mov *.avi *.webm *.mkv)"


# ---------------- 转换引擎 ----------------

def remove_bg(img: np.ndarray) -> np.ndarray:
    """去除与画面边界连通的纯色背景,返回 BGRA。"""
    border = np.concatenate([img[0], img[-1], img[:, 0], img[:, -1]])
    bg_color = np.median(border, axis=0)
    diff = np.abs(img.astype(np.int16) - bg_color.astype(np.int16)).max(axis=2)
    near_bg = (diff < 30).astype(np.uint8)

    # 先腐蚀切断"背景→角色内部同色区域"的细小漏缝
    kernel = np.ones((5, 5), np.uint8)
    near_bg_eroded = cv2.erode(near_bg, kernel)
    # 只有与画面边界连通的疑似背景才是真背景
    _, labels = cv2.connectedComponents(near_bg_eroded, connectivity=4)
    border_labels = np.unique(np.concatenate(
        [labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    bg_core = np.isin(labels, border_labels[border_labels != 0]) & (near_bg_eroded == 1)
    # 膨胀还原到原始边界,但不越出疑似背景范围
    bg_mask = cv2.dilate(bg_core.astype(np.uint8), kernel).astype(bool) & (near_bg == 1)

    alpha = np.where(bg_mask, 0, 255).astype(np.uint8)
    # 轻微收边 + 羽化,消除背景色残留的白边光晕
    alpha = cv2.erode(alpha, np.ones((3, 3), np.uint8), iterations=1)
    alpha = cv2.GaussianBlur(alpha, (5, 5), 0)
    out = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    out[:, :, 3] = alpha
    return out


def convert_video(video_path: Path, name: str, progress_cb=None) -> Path:
    """转换视频为 assets/emotes/<name>/ 下的透明 PNG 帧序列,返回输出目录。"""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

    out_dir = EMOTES_DIR / name
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    count = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        rgba = remove_bg(frame)
        cv2.imwrite(str(out_dir / f"frame_{count:04d}.png"), rgba)
        count += 1
        if progress_cb:
            progress_cb(count, max(total, count))
    cap.release()
    if count == 0:
        shutil.rmtree(out_dir)
        raise RuntimeError("视频中没有读到任何帧")

    (out_dir / "meta.json").write_text(
        json.dumps({"fps": round(float(fps), 3), "frames": count}),
        encoding="utf-8",
    )
    return out_dir


def list_emotes() -> list:
    """返回已导入的表情名列表。"""
    if not EMOTES_DIR.exists():
        return []
    return sorted(
        d.name for d in EMOTES_DIR.iterdir()
        if d.is_dir() and (d / "meta.json").exists()
    )


def load_emote_frames(name: str, width: int):
    """加载表情帧(缩放到显示宽度),返回 (QPixmap 列表, fps)。"""
    emote_dir = EMOTES_DIR / name
    meta = json.loads((emote_dir / "meta.json").read_text(encoding="utf-8"))
    frames = [
        QPixmap(str(p)).scaledToWidth(width, Qt.SmoothTransformation)
        for p in sorted(emote_dir.glob("frame_*.png"))
    ]
    if not frames:
        raise RuntimeError(f"表情 {name} 没有帧文件")
    return frames, float(meta.get("fps", 24.0))


# ---------------- 工坊面板 ----------------

class ConvertWorker(QThread):
    progress = Signal(int, int)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, video_path: Path, name: str):
        super().__init__()
        self.video_path = video_path
        self.name = name

    def run(self):
        try:
            convert_video(self.video_path, self.name,
                          lambda i, n: self.progress.emit(i, n))
            self.done.emit(self.name)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class EmoteStudio(QDialog):
    """表情管理面板: 导入视频转表情、预览、应用、删除。"""
    emote_applied = Signal(str)  # 表情名; 空串表示恢复静态图片

    def __init__(self, current: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Loki 表情工坊")
        self.setFixedSize(520, 380)
        self.video_path = None
        self.worker = None

        root = QHBoxLayout(self)

        # 左侧: 已有表情列表 + 操作按钮
        left = QVBoxLayout()
        left.addWidget(QLabel("已导入的表情:"))
        self.emote_list = QListWidget()
        self.emote_list.currentTextChanged.connect(self.show_preview)
        left.addWidget(self.emote_list)
        row = QHBoxLayout()
        apply_btn = QPushButton("使用")
        apply_btn.clicked.connect(self.apply_selected)
        static_btn = QPushButton("恢复静态")
        static_btn.clicked.connect(lambda: self.emote_applied.emit(""))
        del_btn = QPushButton("删除")
        del_btn.clicked.connect(self.delete_selected)
        row.addWidget(apply_btn)
        row.addWidget(static_btn)
        row.addWidget(del_btn)
        left.addLayout(row)
        root.addLayout(left, 1)

        # 右侧: 预览 + 导入新表情
        right = QVBoxLayout()
        self.preview = QLabel("选中表情可预览")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setFixedSize(240, 200)
        right.addWidget(self.preview, alignment=Qt.AlignHCenter)

        pick_btn = QPushButton("选择视频…")
        pick_btn.clicked.connect(self.pick_video)
        self.file_label = QLabel("(未选择)")
        self.file_label.setStyleSheet("color: #888;")
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("表情名(如 待机 / 开心)")
        self.convert_btn = QPushButton("转换并导入")
        self.convert_btn.clicked.connect(self.start_convert)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        right.addWidget(pick_btn)
        right.addWidget(self.file_label)
        right.addWidget(self.name_input)
        right.addWidget(self.convert_btn)
        right.addWidget(self.progress)
        root.addLayout(right, 1)

        self.refresh(select=current)

    def refresh(self, select: str = ""):
        self.emote_list.clear()
        for name in list_emotes():
            self.emote_list.addItem(name)
        if select:
            matches = self.emote_list.findItems(select, Qt.MatchExactly)
            if matches:
                self.emote_list.setCurrentItem(matches[0])

    def show_preview(self, name: str):
        if not name:
            self.preview.setText("选中表情可预览")
            self.preview.setPixmap(QPixmap())
            return
        first = sorted((EMOTES_DIR / name).glob("frame_*.png"))
        if not first:
            return
        pix = QPixmap(str(first[0])).scaled(
            self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        # 棋盘格底衬,方便确认透明区域
        canvas = QPixmap(pix.size())
        painter = QPainter(canvas)
        for y in range(0, pix.height(), 16):
            for x in range(0, pix.width(), 16):
                shade = 70 if (x // 16 + y // 16) % 2 == 0 else 100
                painter.fillRect(x, y, 16, 16, QColor(shade, shade, shade))
        painter.drawPixmap(0, 0, pix)
        painter.end()
        self.preview.setPixmap(canvas)

    def apply_selected(self):
        item = self.emote_list.currentItem()
        if item:
            self.emote_applied.emit(item.text())

    def delete_selected(self):
        item = self.emote_list.currentItem()
        if not item:
            return
        name = item.text()
        ret = QMessageBox.question(self, "删除表情", f"确定删除表情「{name}」?")
        if ret != QMessageBox.Yes:
            return
        shutil.rmtree(EMOTES_DIR / name, ignore_errors=True)
        self.refresh()
        self.emote_applied.emit("")  # 回退静态,避免引用已删表情

    def pick_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择视频", "", VIDEO_FILTER)
        if path:
            self.video_path = Path(path)
            self.file_label.setText(self.video_path.name)
            if not self.name_input.text().strip():
                self.name_input.setText(self.video_path.stem)

    def start_convert(self):
        if self.worker and self.worker.isRunning():
            return
        if not self.video_path:
            QMessageBox.warning(self, "表情工坊", "请先选择视频文件")
            return
        name = re.sub(r"[^\w\-一-鿿]", "_", self.name_input.text().strip())
        if not name:
            QMessageBox.warning(self, "表情工坊", "请填写表情名")
            return
        self.convert_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.worker = ConvertWorker(self.video_path, name)
        self.worker.progress.connect(
            lambda i, n: (self.progress.setMaximum(n), self.progress.setValue(i)))
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()

    def on_done(self, name: str):
        self.convert_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.refresh(select=name)
        self.emote_applied.emit(name)  # 导入完成后直接应用

    def on_failed(self, err: str):
        self.convert_btn.setEnabled(True)
        self.progress.setVisible(False)
        QMessageBox.critical(self, "转换失败", err)


# ---------------- 命令行入口 ----------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python emote_studio.py <视频路径> [表情名]")
        sys.exit(1)
    video = Path(sys.argv[1])
    emote_name = sys.argv[2] if len(sys.argv) > 2 else video.stem
    out = convert_video(
        video, emote_name,
        lambda i, n: print(f"\r转换中 {i}/{n}", end="", flush=True),
    )
    print(f"\n完成: {out}")
