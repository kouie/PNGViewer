import os
import re
import io
import json
import time
import base64
import random
import itertools
import requests
from datetime import datetime, date
from pathlib import Path
from PIL import Image, PngImagePlugin
from PIL.PngImagePlugin import PngImageFile
from functools import partial

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSplitter, QPushButton, QTextEdit, QFileDialog, QTabWidget,
    QScrollArea, QFrame, QLineEdit, QLayout, QDialog, QCheckBox,
    QMenu, QSlider, QComboBox, QListWidget, QListWidgetItem, QMessageBox,
    QGroupBox, QGridLayout, QSpinBox, QDoubleSpinBox, QProgressBar, QWidgetAction
)
from PySide6.QtCore import Qt, QSize, QRect, QPoint, Signal, QMimeData, QUrl, QByteArray, QEvent, QThread, QTimer, QMutex, QMutexLocker
from PySide6.QtGui import (
    QPixmap, QDragEnterEvent, QDropEvent, QColor, QDrag, QCursor,
    QGuiApplication, QFont, QIcon, QAction, QTextCursor,
    QTextCharFormat, QKeySequence, QShortcut
)

COLLECTIONS_DIR = "collections"
DEFAULT_OUTPUT_DIR = "outputs"
FORGE_URL = "http://127.0.0.1:7860"
os.makedirs(COLLECTIONS_DIR, exist_ok=True)
os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)

# =====================================================================
# ホイールスクロールによる値変更を無効化したカスタムUI部品
# =====================================================================

class NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event): event.ignore()

class NoWheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event): event.ignore()

class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event): event.ignore()


# =====================================================================
# Forge バックグラウンド処理・ヘルパー関数群
# =====================================================================

def get_cpu_temperature() -> float:
    try:
        res = requests.get("http://localhost:8085/data.json", timeout=1)
        if res.status_code == 200:
            data = res.json()
            def find_temp(node):
                if node.get("Text") == "Temperatures":
                    for child in node.get("Children", []):
                        if "Package" in child.get("Text", "") or "Core" in child.get("Text", ""):
                            val_str = child.get("Value", "").replace("°C", "").strip()
                            try: return float(val_str)
                            except: pass
                for child in node.get("Children", []):
                    t = find_temp(child)
                    if t is not None: return t
                return None
            temp = find_temp(data)
            if temp is not None: return temp
    except: pass
    return -1.0

def expand_prompts(prompt_template: str) -> list[str]:
    parts = re.split(r'(\{[^}]+\})', prompt_template)
    options_list = []
    for part in parts:
        if part.startswith('{') and part.endswith('}'):
            options_list.append([c.strip() for c in part[1:-1].split('|')])
        else:
            options_list.append([part])
    return ["".join(comb) for comb in itertools.product(*options_list)]

def get_next_sequence_number(directory: str) -> int:
    if not os.path.exists(directory): return 1
    max_num = 0
    for filename in os.listdir(directory):
        if m := re.match(r'^(\d{5})-.*\.png$', filename, re.IGNORECASE):
            num = int(m.group(1))
            if num > max_num: max_num = num
    return max_num + 1

def create_generation_tasks(base_payload: dict, steps_list: list[int], batch_count: int, fixed_seed: bool) -> list[dict]:
    tasks = []
    prompts = expand_prompts(base_payload.get("prompt", ""))
    current_seed = base_payload.get("seed", -1)
    if current_seed == -1: current_seed = random.randint(0, 4294967295)    

    actual_batch = 1 if len(steps_list) > 1 else batch_count
    for batch_idx in range(actual_batch):
        for prompt in prompts:
            for step_val in steps_list:
                task = base_payload.copy()
                task["prompt"] = prompt
                task["steps"] = step_val
                task["seed"] = (current_seed + batch_idx) if fixed_seed else current_seed
                if not fixed_seed: current_seed += 1
                tasks.append(task)
    return tasks


# =====================================================================
# コントロール拡張エディタ＆スレッド
# =====================================================================

class PromptTextEdit(QTextEdit):
    def keyPressEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            cursor = self.textCursor()
            delta = 0.1 if event.key() == Qt.Key.Key_Up else -0.1
            text = self.toPlainText()
            
            blocks = []
            for m in re.finditer(r'\(([^()]+):([0-9.]+)\)', text):
                try: blocks.append((m.start(), m.end(), m.group(1), m.group(2), float(m.group(2))))
                except ValueError: pass

            if cursor.hasSelection():
                start, end, sel_text = cursor.selectionStart(), cursor.selectionEnd(), cursor.selectedText()
                for b_start, b_end, content, val_str, val_f in blocks:
                    content_start, content_end = b_start + 1, b_end - len(val_str) - 2
                    if (start == b_start and end == b_end) or (start == content_start and end == content_end):
                        new_val = round(val_f + delta, 2)
                        new_str = content if abs(new_val - 1.0) < 0.001 else f"({content}:{new_val:.1f})"
                        cursor.setPosition(b_start); cursor.setPosition(b_end, QTextCursor.MoveMode.KeepAnchor)
                        cursor.insertText(new_str); cursor.setPosition(b_start); cursor.setPosition(b_start + len(new_str), QTextCursor.MoveMode.KeepAnchor)
                        self.setTextCursor(cursor); return
                    if start <= content_start and end < content_end and end > b_start: return
                new_val = round(1.0 + delta, 2); new_str = f"({sel_text}:{new_val:.1f})"
                cursor.insertText(new_str); cursor.setPosition(start); cursor.setPosition(start + len(new_str), QTextCursor.MoveMode.KeepAnchor)
                self.setTextCursor(cursor); return
            else:
                pos = cursor.position(); target_block, min_len = None, len(text) + 1
                for b in blocks:
                    if b[0] <= pos <= b[1] and (b[1] - b[0]) < min_len: min_len, target_block = (b[1] - b[0]), b
                if target_block:
                    b_start, b_end, content, val_str, val_f = target_block
                    new_val = round(val_f + delta, 2)
                    new_str = content if abs(new_val - 1.0) < 0.001 else f"({content}:{new_val:.1f})"
                    cursor.setPosition(b_start); cursor.setPosition(b_end, QTextCursor.MoveMode.KeepAnchor)
                    cursor.insertText(new_str); self.setTextCursor(cursor); return
                else:
                    cursor.select(QTextCursor.SelectionType.WordUnderCursor); word = cursor.selectedText()
                    if word and not word.isspace():
                        new_val = round(1.0 + delta, 2); new_str = f"({word}:{new_val:.1f})"
                        cursor.insertText(new_str); self.setTextCursor(cursor)
                    return
        super().keyPressEvent(event)


# class GenerationThread(QThread):
#     status_updated = Signal(str)
#     image_generated = Signal(str, str, object)    
#     finished_all = Signal()
#     error_occurred = Signal(str)
#     generation_started = Signal()

#     def __init__(self, tasks: list[dict], interval: int, target_temp: float, target_model: str, output_dir: str, forever_mode: bool, fixed_seed: bool):
#         super().__init__()
#         self.tasks, self.interval, self.target_temp, self.target_model, self.output_dir, self.forever_mode = tasks, interval, target_temp, target_model, output_dir, forever_mode
#         self.fixed_seed = fixed_seed
#         self.is_running = True

#         self._mutex = QMutex()
#         self._pending_update = None # 更新待機用の変数
#         self.has_generated = False  # パラメータ更新時のタイマー継続用

#     def update_parameters(self, base_payload: dict, steps_list: list[int], fixed_seed: bool):
#         """UIスレッドから呼ばれる：次回のループで適用するパラメータを安全に予約する"""
#         with QMutexLocker(self._mutex):
#             self._pending_update = (base_payload, steps_list, fixed_seed)

#     def run(self):
#         task_idx, total_tasks = 0, len(self.tasks)

#         while self.is_running:

#             # --- [追加] ループの先頭でタスクの更新を検知して切り替える ---
#             self._mutex.lock()
#             if self._pending_update:
#                 base_payload, steps_list, new_fixed_seed = self._pending_update
#                 self._pending_update = None
#                 self.fixed_seed = new_fixed_seed
                
#                 # ① シード値の引き継ぎ計算（次に使う予定だったシード値を算出）
#                 idx_in_list = task_idx % total_tasks
#                 next_seed = self.tasks[idx_in_list]["seed"]
#                 if task_idx >= total_tasks:
#                     next_seed += (task_idx // total_tasks) * total_tasks
                
#                 # ② 算出したシード値を base_payload に強制上書き
#                 base_payload["seed"] = next_seed
                
#                 # ③ タスクリストを作成し直し、インデックスをリセット
#                 # ※ create_generation_tasks は外部関数としてアクセスできる前提[cite: 1]
#                 self.tasks = create_generation_tasks(base_payload, steps_list, 1, self.fixed_seed)
#                 total_tasks = len(self.tasks)
#                 task_idx = 0
#             self._mutex.unlock()
#             # --------------------------------------------------------

#             idx_in_list = task_idx % total_tasks
#             task = self.tasks[idx_in_list].copy()
#             if task_idx >= total_tasks: task["seed"] += (task_idx // total_tasks) * total_tasks
#             if self.target_model: task["override_settings"] = {"sd_model_checkpoint": self.target_model}

#             #if task_idx > 0 or self.target_temp < 100.0:
#             if self.has_generated or self.target_temp < 100.0:                
#                 start_time = time.time()
#                 while self.is_running:
#                     elapsed = time.time() - start_time
#                     #time_ok = (elapsed >= self.interval) if task_idx > 0 else True
#                     time_ok = (elapsed >= self.interval) if self.has_generated else True
#                     temp = get_cpu_temperature()
#                     temp_ok = (temp <= self.target_temp) if temp != -1.0 else True
#                     temp_str = f"{temp}℃" if temp != -1.0 else "取得不可"
#                     #rem = max(0, int(self.interval - elapsed)) if task_idx > 0 else 0
#                     rem = max(0, int(self.interval - elapsed)) if self.has_generated else 0
#                     mode_str = f" [∞ 無限ループ中 #{task_idx+1}]" if self.forever_mode else f" [{task_idx+1}/{total_tasks}]"
#                     self.status_updated.emit(f"⏳ 待機中{mode_str} | 残り: {rem}秒 | CPU温度: {temp_str} (目標 <= {self.target_temp}℃)")
#                     if time_ok and temp_ok: break
#                     time.sleep(1)

#             if not self.is_running: break
#             mode_str = f" [∞ 無限モード #{task_idx+1}]" if self.forever_mode else f" [{task_idx+1}/{total_tasks}]"
#             self.status_updated.emit(f"🎨 画像を生成中...{mode_str} Steps:{task['steps']} / Seed:{task['seed']}")
#             self.generation_started.emit()
            
#             try:
#                 res = requests.post(f"{FORGE_URL}/sdapi/v1/txt2img", json=task, timeout=300); res.raise_for_status(); result = res.json()
#                 img_data = base64.b64decode(result["images"][0]); image = Image.open(io.BytesIO(img_data))
#                 date_str = date.today().strftime("%Y-%m-%d"); date_dir = os.path.join(self.output_dir, date_str); os.makedirs(date_dir, exist_ok=True)
#                 seq_num = get_next_sequence_number(date_dir); filename = f"{seq_num:05d}-{task['seed']}.png"; filepath = os.path.join(date_dir, filename)
#                 pnginfo = PngImagePlugin.PngInfo()
#                 if "info" in result:
#                     info_dict = json.loads(result["info"]); pnginfo.add_text("parameters", info_dict.get("infotexts", [result["info"]])[0])
#                 image.save(filepath, pnginfo=pnginfo)
#                 self.image_generated.emit(filepath, f"Seed: {task['seed']} | Steps: {task['steps']} | Prompt: {task['prompt'][:40]}...", task['seed'])
#             except Exception as e:
#                 if self.is_running: self.error_occurred.emit(f"生成エラー: {str(e)}")
#                 break

#             self.has_generated = True

#             task_idx += 1
#             if not self.forever_mode and task_idx >= total_tasks: break
        
#         self.finished_all.emit()

#     def stop_loop_only(self): self.is_running = False
#     def stop_and_interrupt(self):
#         self.is_running = False
#         try: requests.post(f"{FORGE_URL}/sdapi/v1/interrupt", timeout=2)
#         except: pass

class GenerationThread(QThread):
    status_updated = Signal(str)
    image_generated = Signal(str, str, object)    
    finished_all = Signal()
    error_occurred = Signal(str)
    generation_started = Signal()

    def __init__(self, tasks: list[dict], interval: int, target_temp: float, target_model: str, output_dir: str, forever_mode: bool, fixed_seed: bool):
        super().__init__()
        self.tasks, self.interval, self.target_temp, self.target_model, self.output_dir, self.forever_mode = tasks, interval, target_temp, target_model, output_dir, forever_mode
        self.fixed_seed = fixed_seed
        self.is_running = True

        self._mutex = QMutex()
        self._pending_update = None # 更新待機用の変数
        self.has_generated = False  # パラメータ更新時のタイマー継続用

    def update_parameters(self, base_payload: dict, steps_list: list[int], fixed_seed: bool, interval: int, target_temp: float):
        """UIスレッドから呼ばれる：次回のループで適用するパラメータを安全に予約する"""
        with QMutexLocker(self._mutex):
            self._pending_update = (base_payload, steps_list, fixed_seed, interval, target_temp)

    def run(self):
        task_idx, total_tasks = 0, len(self.tasks)

        while self.is_running:
            
            # --- 【修正】1. 先にインターバル・温度の待機処理を行う ---
            if self.has_generated or self.target_temp < 100.0:                
                start_time = time.time()
                while self.is_running:
                    # 待機ループ中にもパラメータ更新を監視し、タスク情報を更新する（UI表示即時反映のため）
                    self._mutex.lock()
                    if self._pending_update:
                        #base_payload, steps_list, new_fixed_seed = self._pending_update
                        base_payload, steps_list, new_fixed_seed, new_interval, new_target_temp = self._pending_update
                        self._pending_update = None
                        self.fixed_seed = new_fixed_seed
                        self.interval = new_interval
                        self.target_temp = new_target_temp
                        
                        idx_in_list = task_idx % total_tasks
                        next_seed = self.tasks[idx_in_list]["seed"]
                        if task_idx >= total_tasks:
                            next_seed += (task_idx // total_tasks) * total_tasks
                        
                        base_payload["seed"] = next_seed
                        self.tasks = create_generation_tasks(base_payload, steps_list, 1, self.fixed_seed)
                        total_tasks = len(self.tasks)
                        task_idx = 0
                    self._mutex.unlock()

                    elapsed = time.time() - start_time
                    time_ok = (elapsed >= self.interval) if self.has_generated else True
                    temp = get_cpu_temperature()
                    temp_ok = (temp <= self.target_temp) if temp != -1.0 else True
                    temp_str = f"{temp}℃" if temp != -1.0 else "取得不可"
                    rem = max(0, int(self.interval - elapsed)) if self.has_generated else 0
                    mode_str = f" [∞ 無限ループ中 #{task_idx+1}]" if self.forever_mode else f" [{task_idx+1}/{total_tasks}]"
                    self.status_updated.emit(f"⏳ 待機中{mode_str} | 残り: {rem}秒 | CPU温度: {temp_str} (目標 <= {self.target_temp}℃)")
                    if time_ok and temp_ok: break
                    time.sleep(1)

            if not self.is_running: break

            # --- 【修正】2. 待機をスキップした場合に備え、生成直前にもタスクの更新を検知して切り替える ---
            self._mutex.lock()
            if self._pending_update:
                #base_payload, steps_list, new_fixed_seed = self._pending_update
                base_payload, steps_list, new_fixed_seed, new_interval, new_target_temp = self._pending_update
                self._pending_update = None
                self.fixed_seed = new_fixed_seed
                self.interval = new_interval
                self.target_temp = new_target_temp
                
                idx_in_list = task_idx % total_tasks
                next_seed = self.tasks[idx_in_list]["seed"]
                if task_idx >= total_tasks:
                    next_seed += (task_idx // total_tasks) * total_tasks
                
                base_payload["seed"] = next_seed
                self.tasks = create_generation_tasks(base_payload, steps_list, 1, self.fixed_seed)
                total_tasks = len(self.tasks)
                task_idx = 0
            self._mutex.unlock()
            
            # --- 【修正】3. 最新のタスク情報を取得 ---
            idx_in_list = task_idx % total_tasks
            task = self.tasks[idx_in_list].copy()
            if task_idx >= total_tasks: task["seed"] += (task_idx // total_tasks) * total_tasks
            if self.target_model: task["override_settings"] = {"sd_model_checkpoint": self.target_model}

            # --- 4. 生成処理を実行 ---
            mode_str = f" [∞ 無限モード #{task_idx+1}]" if self.forever_mode else f" [{task_idx+1}/{total_tasks}]"
            self.status_updated.emit(f"🎨 画像を生成中...{mode_str} Steps:{task['steps']} / Seed:{task['seed']}")
            self.generation_started.emit()
            
            try:
                res = requests.post(f"{FORGE_URL}/sdapi/v1/txt2img", json=task, timeout=300); res.raise_for_status(); result = res.json()
                img_data = base64.b64decode(result["images"][0]); image = Image.open(io.BytesIO(img_data))
                date_str = date.today().strftime("%Y-%m-%d"); date_dir = os.path.join(self.output_dir, date_str); os.makedirs(date_dir, exist_ok=True)
                seq_num = get_next_sequence_number(date_dir); filename = f"{seq_num:05d}-{task['seed']}.png"; filepath = os.path.join(date_dir, filename)
                pnginfo = PngImagePlugin.PngInfo()
                if "info" in result:
                    info_dict = json.loads(result["info"]); pnginfo.add_text("parameters", info_dict.get("infotexts", [result["info"]])[0])
                image.save(filepath, pnginfo=pnginfo)
                self.image_generated.emit(filepath, f"Seed: {task['seed']} | Steps: {task['steps']} | Prompt: {task['prompt'][:40]}...", task['seed'])
            except Exception as e:
                if self.is_running: self.error_occurred.emit(f"生成エラー: {str(e)}")
                break

            self.has_generated = True

            task_idx += 1
            if not self.forever_mode and task_idx >= total_tasks: break
        
        self.finished_all.emit()

    def stop_loop_only(self): self.is_running = False
    def stop_and_interrupt(self):
        self.is_running = False
        try: requests.post(f"{FORGE_URL}/sdapi/v1/interrupt", timeout=2)
        except: pass

# =====================================================================
# ビューア用＆プレビュー用 ドラッグ対応ラベル
# =====================================================================

class DraggableImageLabel(QLabel):
    def __init__(self, image_path="", parent=None):
        super().__init__(parent); self.image_path = image_path
        if image_path and os.path.exists(image_path): self.setPixmap(QPixmap(image_path))
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.pixmap() is None or self.pixmap().isNull(): return
            self.drag_start_position = event.pos()
        super().mousePressEvent(event)
    def mouseMoveEvent(self, event):
        if self.pixmap() is None or self.pixmap().isNull() or not (event.buttons() & Qt.MouseButton.LeftButton): return
        if (event.pos() - self.drag_start_position).manhattanLength() < QApplication.startDragDistance() or not self.image_path or not os.path.exists(self.image_path): return
        drag = QDrag(self); mime_data = QMimeData(); file_url = QUrl.fromLocalFile(os.path.abspath(self.image_path))
        mime_data.setUrls([file_url]); self.setup_mime_data(mime_data); drag.setMimeData(mime_data)
        preview_pixmap = self.pixmap().scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatio)
        drag.setPixmap(preview_pixmap); drag.setHotSpot(QPoint(int(preview_pixmap.width() / 2), int(preview_pixmap.height() / 2)))
        drag.exec(Qt.DropAction.CopyAction)
    def setup_mime_data(self, mime_data): mime_data.setData("application/x-imageviewer", QByteArray(self.image_path.encode()))        


class DraggablePreviewLabel(DraggableImageLabel):
    file_dropped = Signal(str)
    def __init__(self):
        super().__init__("")
        self.setText("📷 ここにPNG画像をドロップしてパラメータを読込\n（ダブルクリックで原寸表示 / ドラッグして外部へ移動可）")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter); self.setStyleSheet("border: 2px dashed #aaaaaa; background-color: #2b2b2b; color: #dddddd; font-size: 13px;")
        self.setAcceptDrops(True); self.setMinimumSize(250, 200); self.original_pixmap = None
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls() and (urls := event.mimeData().urls()) and urls[0].toLocalFile().lower().endswith(".png"):
            event.acceptProposedAction(); self.setStyleSheet("border: 2px dashed #4CAF50; background-color: #333333; color: #ffffff; font-size: 13px;"); return
        event.ignore()
    def dragLeaveEvent(self, event): self.setStyleSheet("border: 2px dashed #aaaaaa; background-color: #2b2b2b; color: #dddddd; font-size: 13px;")
    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet("border: 2px dashed #aaaaaa; background-color: #2b2b2b; color: #dddddd; font-size: 13px;")
        if urls := event.mimeData().urls(): self.file_dropped.emit(urls[0].toLocalFile())
    def set_preview_image(self, filepath: str):
        self.image_path, self.original_pixmap = filepath, QPixmap(filepath); self.update_pixmap_display()
    def update_pixmap_display(self):
        if self.original_pixmap and not self.original_pixmap.isNull():
            self.setPixmap(self.original_pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    def resizeEvent(self, event): super().resizeEvent(event); self.update_pixmap_display()
    def mouseDoubleClickEvent(self, event):
        if self.image_path and os.path.exists(self.image_path):
            original_view = OriginalViewWindow(self.image_path); original_view.show()
            if not hasattr(QApplication.instance(), "_original_windows"): QApplication.instance()._original_windows = []
            QApplication.instance()._original_windows.append(original_view)
            original_view.originalWindowClosed.connect(lambda w: QApplication.instance()._original_windows.remove(w) if w in QApplication.instance()._original_windows else None)


class ViewerDraggableLabel(DraggableImageLabel):
    deleteRequested = Signal(str)
    def __init__(self, image_path, parent=None):
        super().__init__(image_path, parent); self.setAcceptDrops(True); self.thumbnail_size = 130   
        self.setFixedSize(self.thumbnail_size + 8, self.thumbnail_size + 8); self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.customContextMenuRequested.connect(self.showContextMenu)
    def setup_mime_data(self, mime_data): super().setup_mime_data(mime_data); mime_data.setData("application/x-image-sortable", QByteArray(self.image_path.encode()))
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasFormat("application/x-image-sortable"): event.acceptProposedAction()
        else: event.ignore()
    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasFormat("application/x-image-sortable"):
            source_path = event.mimeData().data("application/x-image-sortable").data().decode(); target_path = self.image_path
            if source_path == target_path: event.ignore(); return
            parent = self.parent()
            while parent:
                if isinstance(parent, CollectionWidget): parent.swapImages(source_path, target_path); event.acceptProposedAction(); break
                parent = parent.parent()
        else: event.ignore()
    def showContextMenu(self, position):
        context_menu = QMenu(self); delete_action = context_menu.addAction("削除"); delete_action.triggered.connect(lambda: self.deleteRequested.emit(self.image_path)); context_menu.exec(self.mapToGlobal(position))
    def mouseDoubleClickEvent(self, event):
        if self.image_path and os.path.exists(self.image_path):
            original_view = OriginalViewWindow(self.image_path); original_view.show()
            if not hasattr(QApplication.instance(), "_original_windows"): QApplication.instance()._original_windows = []
            QApplication.instance()._original_windows.append(original_view)
            original_view.originalWindowClosed.connect(lambda w: QApplication.instance()._original_windows.remove(w) if w in QApplication.instance()._original_windows else None)


# =====================================================================
# UIヘルパー（メタデータラベル、ダイアログ、コレクション等）
# =====================================================================

class MetadataLabel(QLabel):
    r_button_clicked = Signal()
    send_single_to_forge = Signal(str, str, bool)
    send_all_to_forge = Signal(bool)

    def __init__(self, label="", value="", parent=None):
        super().__init__(parent); self.label, self.value = label, value; self.setFont(QFont('SansSerif', 11)); self.setTextFormat(Qt.TextFormat.RichText); self.setWordWrap(True); self.update_text(); self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    def update_text(self, highlight=False):
        if highlight: self.setText(f"<b>{self.label}:</b> <span style='background-color: #FFEB3B'>{self.value}</span>")
        else: self.setText(f"<b>{self.label}:</b> {self.value.replace(chr(10), '<br>')}")
    def apply_highlight(self, words_to_highlight, color):
        all_text = self.value 
        for word in words_to_highlight: all_text = all_text.replace(word, f'<span style="background-color: {color};">{word}</span>')
        self.setText(f"<b>{self.label}:</b> {all_text.replace(chr(10), '<br>')}")
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        copyAction = menu.addAction("コピー"); copyAction.triggered.connect(self.copy)
        selectAllAction = menu.addAction("パラメータの値をコピー"); selectAllAction.triggered.connect(self.selectAll)
        menu.addSeparator()
        sendAction = menu.addAction("👉 このパラメータを生成パネルにセット"); sendAction.triggered.connect(lambda: self.send_single_to_forge.emit(self.label, self.value, False))
        sendGenAction = menu.addAction("🚀 このパラメータをセットして生成スタート"); sendGenAction.triggered.connect(lambda: self.send_single_to_forge.emit(self.label, self.value, True))
        menu.addSeparator()
        sendAllAction = menu.addAction("👉 この画像の全パラメータをセット"); sendAllAction.triggered.connect(lambda: self.send_all_to_forge.emit(False))
        sendAllGenAction = menu.addAction("🚀 全パラメータをセットして生成スタート"); sendAllGenAction.triggered.connect(lambda: self.send_all_to_forge.emit(True))
        menu.addSeparator()
        customAction = menu.addAction("表示するパラメータを選択..."); customAction.triggered.connect(self.on_r_mouse_clicked); menu.exec(event.globalPos())
    def on_r_mouse_clicked(self): self.r_button_clicked.emit()
    def copy(self): QGuiApplication.clipboard().setText(self.selectedText())
    def selectAll(self): QGuiApplication.clipboard().setText(self.value)


class CheckableListDialog(QDialog):
    def __init__(self, items, parent=None):
        super().__init__(parent); self.setWindowTitle("表示するパラメータの選択"); self.resize(180, 400); self.layout = QVBoxLayout(self); self.checkboxes = []
        for item in items:
            checkbox = QCheckBox(item); self.checkboxes.append(checkbox); self.layout.addWidget(checkbox)
        self.okButton = QPushButton("OK"); self.okButton.clicked.connect(self.accept); self.layout.addWidget(self.okButton)
    def getSelectedItems(self): return [cb.text() for cb in self.checkboxes if cb.isChecked()]


class OpenNavigationButton(QPushButton):
    new_folder = Signal()
    def __init__(self, parent=None):
        super().__init__(parent); self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.current_folder, self.pinned_folders, self.folder_history, self.history_index = "", [], [], -1
        self.clicked.connect(self.open_folder); self.customContextMenuRequested.connect(self.show_context_menu)        
    def create_pinned_folder_widget(self, folder):
        widget = QWidget(); layout = QHBoxLayout(widget); layout.setContentsMargins(20, 0, 5, 0)
        label = QLabel(os.path.basename(folder) or folder); label.setToolTip(folder)
        delete_button = QPushButton("×"); delete_button.setFixedSize(20, 20); delete_button.setToolTip("ピン留め解除"); delete_button.clicked.connect(lambda: self.unpin_folder(folder))
        layout.addWidget(label); layout.addStretch(); layout.addWidget(delete_button); widget.setMouseTracking(True); widget.setCursor(Qt.CursorShape.PointingHandCursor)
        return widget
    def handle_pinned_folder_click(self, event, folder):
        if event.button() == Qt.MouseButton.LeftButton and not isinstance(self.childAt(event.pos()), QPushButton): self.navigate_to_folder(folder)
    def navigate_to_folder(self, folder):
        if not os.path.exists(folder): QMessageBox.warning(self, "エラー", f"フォルダが見つかりません: {folder}"); return
        if self.current_folder:
            if self.history_index < len(self.folder_history) - 1: self.folder_history = self.folder_history[:self.history_index + 1]
            self.folder_history.append(self.current_folder); self.history_index = len(self.folder_history) - 1
        self.current_folder = folder; self.new_folder.emit()
    def unpin_folder(self, folder):
        if folder in self.pinned_folders: self.pinned_folders.remove(folder)
    def show_context_menu(self, pos):
        menu = QMenu(); m_next = menu.addAction("次のフォルダ"); m_next.setEnabled(self.current_folder != ""); m_next.triggered.connect(partial(self.move_folder, 1))
        m_prev = menu.addAction("前のフォルダ"); m_prev.setEnabled(self.current_folder != ""); m_prev.triggered.connect(partial(self.move_folder, -1))
        pinning = menu.addAction("ピン留めする"); pinning.setEnabled(self.current_folder != "" and self.current_folder not in self.pinned_folders); pinning.triggered.connect(self.pin_current_folder)
        if self.pinned_folders:
            menu.addSeparator()       
            for folder in self.pinned_folders:
                widget = self.create_pinned_folder_widget(folder); widget.mouseReleaseEvent = lambda event, f=folder: self.handle_pinned_folder_click(event, f)
                widget_action = QWidgetAction(menu); widget_action.setDefaultWidget(widget); menu.addAction(widget_action)
        menu.exec(self.mapToGlobal(pos))
    def pin_current_folder(self):
        if self.current_folder and self.current_folder not in self.pinned_folders: self.pinned_folders.append(self.current_folder)
    def open_folder(self):
        if folder := QFileDialog.getExistingDirectory(self, "Select Folder", self.current_folder): self.current_folder = folder; self.new_folder.emit()
    def move_folder(self, direction):
        parent_folder = Path(self.current_folder).parent; folders = [f for f in os.listdir(parent_folder) if os.path.isdir(parent_folder / f)]
        if not folders: return
        try:
            new_index = (folders.index(Path(self.current_folder).name) + direction) % len(folders)
            self.current_folder = str(parent_folder / folders[new_index]).replace("\\", "/"); self.new_folder.emit()
        except ValueError: pass


class SliderPopup(QFrame):
    filter_changed = Signal(bool)
    def __init__(self, parent=None):
        super().__init__(parent); self.setFrameShape(QFrame.Shape.StyledPanel); self.setFrameShadow(QFrame.Shadow.Raised); self.setWindowFlags(Qt.WindowType.Popup)
        self.image_files, self.current_index = [], 0; layout = QHBoxLayout(self); layout.setContentsMargins(8, 5, 8, 5)
        self.slider = QSlider(Qt.Orientation.Horizontal); self.slider.setMinimum(0); self.slider.setMaximum(0); layout.addWidget(self.slider)
        self.lbl_page = QLabel("0/0"); self.lbl_page.setFont(QFont('SansSerif', 9, QFont.Weight.Bold)); self.lbl_page.setMinimumWidth(60); self.lbl_page.setAlignment(Qt.AlignmentFlag.AlignCenter); layout.addWidget(self.lbl_page)
        #self.chk_filter = QCheckBox("フィルタ適用"); self.chk_filter.setToolTip("テキストボックスに入力された条件でリストを絞り込みます"); self.chk_filter.stateChanged.connect(lambda state: self.filter_changed.emit(state != 0)); layout.addWidget(self.chk_filter)
        self.setFixedWidth(420)
    def mousePressEvent(self, event): super().mousePressEvent(event); event.accept()
    def update_page_display(self, index, total): self.lbl_page.setText(f"{index}/{total}" if total > 0 else "0/0")


class FlowLayout(QLayout):    
    def __init__(self, parent=None): super().__init__(parent); self.setContentsMargins(5, 5, 5, 5); self.setSpacing(5); self.items = []
    def __del__(self):
        while item := self.takeAt(0): pass
    def addItem(self, item): self.items.append(item)
    def count(self): return len(self.items)
    def itemAt(self, index): return self.items[index] if 0 <= index < self.count() else None
    def takeAt(self, index): return self.items.pop(index) if 0 <= index < self.count() else None
    def expandingDirections(self): return Qt.Orientation(0)
    def hasHeightForWidth(self): return True
    def heightForWidth(self, width): return self.do_layout(QRect(0, 0, width, 0))
    def sizeHint(self): return self.minimumSize()
    def minimumSize(self):
        size = QSize()
        for item in self.items: size = size.expandedTo(item.minimumSize())
        margin = self.contentsMargins()
        return size + QSize(margin.left() + margin.right(), margin.top() + margin.bottom())
    def setGeometry(self, rect): super().setGeometry(rect); self.do_layout(rect)
    def do_layout(self, rect):
        x, y, line_height, layout_spacing = rect.x(), rect.y(), 0, self.spacing()
        for item in self.items:
            next_x = x + item.sizeHint().width() + layout_spacing
            if next_x - layout_spacing > rect.right() and line_height > 0:
                x, y = rect.x(), y + line_height + layout_spacing
                next_x = x + item.sizeHint().width() + layout_spacing; line_height = 0
            item.setGeometry(QRect(QPoint(x, y), item.sizeHint())); x = next_x; line_height = max(line_height, item.sizeHint().height())
        return y + line_height - rect.y()


class CollectionWidget(QWidget):
    image_selected = Signal(str)
    def __init__(self, parent=None):
        super().__init__(parent); self.images, self.thumbnails, self.thumbnail_map = [], [], {}; self.setMinimumWidth(170); self.init_ui()
    def init_ui(self):
        self.main_layout = QVBoxLayout(self); toolbar_layout = QHBoxLayout()
        self.clear_button = QPushButton("クリア", self); self.clear_button.setFixedWidth(50); self.clear_button.clicked.connect(self.clear_collection); toolbar_layout.addWidget(self.clear_button)
        self.text_box = QLineEdit(); self.text_box.setMinimumWidth(100); self.text_box.setPlaceholderText("メモ..."); toolbar_layout.addWidget(self.text_box)
        self.save_button = QPushButton("💾 保存", self); self.save_button.clicked.connect(self.save_collection); toolbar_layout.addWidget(self.save_button)
        self.load_button = QPushButton("📂 読込", self); self.load_button.clicked.connect(self.show_load_dialog); toolbar_layout.addWidget(self.load_button)
        toolbar_layout.addStretch(1); self.main_layout.addLayout(toolbar_layout)
        self.scroll_area = QScrollArea(); self.scroll_area.setWidgetResizable(True); self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded); self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded); self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_content = QWidget(); self.flow_layout = FlowLayout(self.scroll_content); self.scroll_content.setLayout(self.flow_layout)
        self.scroll_area.setWidget(self.scroll_content); self.main_layout.addWidget(self.scroll_area); self.setAcceptDrops(True)
    def add_image(self, image_path):
        if image_path in self.images or not os.path.exists(image_path): return
        self.images.append(image_path); thumbnail = ViewerDraggableLabel(image_path, self); pixmap = QPixmap(image_path)
        thumbnail.setPixmap(pixmap.scaled(thumbnail.thumbnail_size, thumbnail.thumbnail_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter); thumbnail.deleteRequested.connect(self.remove_image)
        self.thumbnails.append(thumbnail); self.thumbnail_map[image_path] = thumbnail; self.flow_layout.addWidget(thumbnail); self.flow_layout.update()
    def remove_image(self, image_path):
        if image_path in self.images:
            self.images.remove(image_path)
            if image_path in self.thumbnail_map:
                thumbnail = self.thumbnail_map[image_path]; self.thumbnails.remove(thumbnail); del self.thumbnail_map[image_path]; thumbnail.setParent(None); self.flow_layout.update()
    def swapImages(self, source_path, target_path):
        if source_path in self.images and target_path in self.images:
            source_image = self.images.pop(self.images.index(source_path)); self.images.insert(self.images.index(target_path), source_image)
            for thumbnail in self.thumbnails: thumbnail.setParent(None)
            for img_path in self.images:
                if img_path in self.thumbnail_map: self.flow_layout.addWidget(self.thumbnail_map[img_path])
            self.flow_layout.update()
    def clear_collection(self):
        for thumbnail in self.thumbnails: thumbnail.setParent(None)
        self.thumbnails.clear(); self.images.clear(); self.flow_layout.update()
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith('.png'): event.acceptProposedAction(); return
        event.ignore()
    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith('.png'): self.add_image(url.toLocalFile())
            event.acceptProposedAction()
    def save_collection(self):
        if not self.images: QMessageBox.warning(self, "通知", "保存する画像がありません。"); return
        memo = self.text_box.text().strip() or "Untitled"; now = datetime.now(); timestamp = now.strftime("%Y/%m/%d %H:%M"); filename_ts = now.strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(COLLECTIONS_DIR, f"col_{filename_ts}.json")
        try:
            with open(filepath, "w", encoding="utf-8") as f: json.dump({"memo": memo, "timestamp": timestamp, "images": self.images}, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "保存完了", f"「{memo}  {timestamp}」\nとして保存しました。")
        except Exception as e: QMessageBox.critical(self, "エラー", f"保存に失敗しました: {e}")
    def show_load_dialog(self):
        dialog = CollectionLoadDialog(self)
        if dialog.exec() and (selected_images := dialog.get_selected_images()):
            self.clear_collection()
            for img in selected_images: self.add_image(img)
            if dialog.selected_memo: self.text_box.setText(dialog.selected_memo)


class CollectionLoadDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle("コレクションの読み込み"); self.resize(450, 350); self.selected_images, self.selected_memo = [], ""
        layout = QVBoxLayout(self); sort_layout = QHBoxLayout(); sort_layout.addWidget(QLabel("ソート:"))
        self.combo_sort = NoWheelComboBox(); self.combo_sort.addItems(["日時順", "名前順"]); self.combo_sort.currentIndexChanged.connect(self.load_list)
        sort_layout.addWidget(self.combo_sort); sort_layout.addStretch(); layout.addLayout(sort_layout)
        self.list_widget = QListWidget(); self.list_widget.itemDoubleClicked.connect(self.accept_selection); layout.addWidget(self.list_widget)
        btn_layout = QHBoxLayout(); btn_load = QPushButton("選択して開く"); btn_load.clicked.connect(self.accept_selection)
        btn_cancel = QPushButton("キャンセル"); btn_cancel.clicked.connect(self.reject)
        btn_layout.addStretch(); btn_layout.addWidget(btn_load); btn_layout.addWidget(btn_cancel); layout.addLayout(btn_layout)
        self.load_list()
    def load_list(self):
        self.list_widget.clear()
        files = [os.path.join(COLLECTIONS_DIR, f) for f in os.listdir(COLLECTIONS_DIR) if f.endswith(".json")]
        items_data = []
        for fpath in files:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f); items_data.append({"path": fpath, "memo": data.get("memo", "Untitled"), "timestamp": data.get("timestamp", ""), "images": data.get("images", [])})
            except Exception: continue
        items_data.sort(key=lambda x: x["timestamp"] if self.combo_sort.currentIndex() == 0 else x["memo"].lower(), reverse=(self.combo_sort.currentIndex() == 0))
        for item_d in items_data:
            list_item = QListWidgetItem(self.list_widget); list_item.setData(Qt.ItemDataRole.UserRole, item_d)
            row_widget = QWidget(); row_layout = QHBoxLayout(row_widget); row_layout.setContentsMargins(5, 2, 5, 2)
            lbl_text = QLabel(f"{item_d['memo']}   {item_d['timestamp']}")
            btn_del = QPushButton("削除"); btn_del.setFixedSize(45, 24); btn_del.setStyleSheet("background-color: #d32f2f; color: white;"); btn_del.clicked.connect(partial(self.delete_item, fpath, list_item))
            row_layout.addWidget(lbl_text); row_layout.addStretch(); row_layout.addWidget(btn_del)
            list_item.setSizeHint(row_widget.sizeHint()); self.list_widget.setItemWidget(list_item, row_widget)
    def delete_item(self, fpath, list_item):
        if QMessageBox.question(self, "確認", "このコレクションメモを削除しますか？") == QMessageBox.StandardButton.Yes:
            try:
                if os.path.exists(fpath): os.remove(fpath)
                self.list_widget.takeItem(self.list_widget.row(list_item))
            except Exception as e: QMessageBox.critical(self, "エラー", f"削除できませんでした: {e}")
    def accept_selection(self):
        if item := self.list_widget.currentItem():
            data = item.data(Qt.ItemDataRole.UserRole); self.selected_images, self.selected_memo = data["images"], data["memo"]; self.accept()
    def get_selected_images(self): return self.selected_images


class CollectionWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent); self.collection_widget = CollectionWidget(self); self.setCentralWidget(self.collection_widget); self.setWindowTitle("画像コレクション"); self.resize(700, 220)
    def add_image(self, image_path): self.collection_widget.add_image(image_path)
    def resizeEvent(self, event):
        if hasattr(self, 'collection_widget') and hasattr(self.collection_widget, 'flow_layout'): self.collection_widget.flow_layout.update()
        super().resizeEvent(event)
    def closeEvent(self, event):
        if self.parent() and hasattr(self.parent(), 'remove_collection'): self.parent().remove_collection(self)
        super().closeEvent(event)


class OriginalViewWindow(QMainWindow):
    originalWindowClosed = Signal(object)
    def __init__(self, image_file, parent=None):
        super().__init__(parent); self.original_view = QWidget(self); self.setCentralWidget(self.original_view); self.layout = QVBoxLayout(self.original_view); self.setWindowTitle(f"オリジナルサイズ - {image_file}")
        self.image_label = QLabel(); self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter); self.image_label.setMouseTracking(True); self.image_label.mouseDoubleClickEvent = lambda e: self.close()
        self.scroll_area = QScrollArea(); self.scroll_area.setWidget(self.image_label); self.scroll_area.setWidgetResizable(True); self.scroll_area.setFrameShape(QFrame.Shape.NoFrame); self.layout.addWidget(self.scroll_area)
        self.dragging, self.drag_position = False, None
        pixmap = QPixmap(image_file); self.image_label.setPixmap(pixmap); self.resize_window_to_image(pixmap)
    def resize_window_to_image(self, pixmap):
        screen_size = QGuiApplication.primaryScreen().availableGeometry().size()
        self.resize(min(pixmap.width(), int(screen_size.width() * 0.85)) + 40, min(pixmap.height(), int(screen_size.height() * 0.85)) + 30)
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton: self.dragging, self.drag_position = True, event.globalPosition().toPoint() - self.frameGeometry().topLeft(); event.accept()
    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self.dragging: self.move(event.globalPosition().toPoint() - self.drag_position); event.accept()
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton: self.dragging = False; event.accept()
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape: self.close()
        super().keyPressEvent(event)
    def closeEvent(self, event): self.originalWindowClosed.emit(self); super().closeEvent(event)


# =====================================================================
# ImageView （単体/左右比較のビューア）
# =====================================================================

class ImageView(QWidget):
    image_loaded = Signal()
    area_resized = Signal(int)
    metaarea_changed = Signal()
    send_all_to_forge = Signal(dict, bool)
    send_single_to_forge = Signal(str, str, bool)

    def __init__(self, set_id, parent=None):
        super().__init__(parent)        
        self.metadata, self.current_image_path, self.current_folder, self.current_index, self.set_id = {}, "", "", 0, set_id
        self.meta_tags = ["Prompt", "Negative prompt", "Steps", "Sampler", "CFG scale", "Seed", "Size", "Model", "VAE", "Denoising strength", "Variation seed", "Variation seed strength", "Clip skip"]
        self.container = QWidget(); layout = QVBoxLayout(self.container)
        self.splitter = QSplitter(Qt.Orientation.Vertical); layout.addWidget(self.splitter)

        scroll_area = QScrollArea(); scroll_area.setWidgetResizable(True); scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.image_label = DraggableImageLabel("", self); self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setText("ファイルをドラッグ&ドロップするか\n[Open] ボタンでフォルダを指定してください")
        self.image_label.setMouseTracking(True); self.image_label.mouseDoubleClickEvent = self.on_image_double_click
        scroll_area.setWidget(self.image_label); self.splitter.addWidget(scroll_area)
        scroll_area.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); scroll_area.customContextMenuRequested.connect(self.show_slider_popup)

        metadata_scroll = QScrollArea(); metadata_scroll.setWidgetResizable(True)
        self.metadata_widget = QWidget(); self.metadata_layout = QVBoxLayout(self.metadata_widget)
        metadata_scroll.setWidget(self.metadata_widget); self.splitter.addWidget(metadata_scroll)
        metadata_scroll.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); metadata_scroll.customContextMenuRequested.connect(self.show_tagSelection_ContextMenu)
        
        self.splitter.setSizes([500, 400]); self.splitter.splitterMoved.connect(lambda: self.area_resized.emit(self.set_id))
        self.slider_popup = SliderPopup(self); self.slider_popup.slider.valueChanged.connect(self.on_slider_value_changed)
        self.slider_popup.filter_changed.connect(self.on_slider_filter_changed)

        self.toolbar = self.setup_toolbar(); layout.insertLayout(0, self.toolbar)
        self.image_label.installEventFilter(self); self.container.setAcceptDrops(True); self.container.installEventFilter(self)
        self.open_button.new_folder.connect(self.on_new_folder); self.original_views = [] 

    def setup_toolbar(self):
        toolbar = QHBoxLayout()
        self.open_button = OpenNavigationButton(); self.open_button.setText("Open"); self.open_button.setFixedWidth(50); toolbar.addWidget(self.open_button)
        copy_seed_button = QPushButton("Copy"); copy_seed_button.clicked.connect(self.copy_seed); copy_seed_button.setFixedWidth(45); toolbar.addWidget(copy_seed_button)
        #self.chk_desc = QCheckBox("降順"); self.chk_desc.stateChanged.connect(self.refresh_folder_view); toolbar.addWidget(self.chk_desc)
        
        # 1350px壁解決策③：比較画面でも突っ張らないようテキストボックスの最小幅を柔軟(80px)に設定
        self.text_box = QLineEdit(); self.text_box.setMinimumWidth(80); self.text_box.setPlaceholderText("Filter ( - : neg prompt)"); self.text_box.setClearButtonEnabled(True); self.text_box.editingFinished.connect(self.text_entered); toolbar.addWidget(self.text_box)
        
        toolbar.addStretch()
        self.lbl_page = QLabel("0/0"); self.lbl_page.setFont(QFont('SansSerif', 10, QFont.Weight.Bold)); self.lbl_page.setMinimumWidth(65); self.lbl_page.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter); toolbar.addWidget(self.lbl_page)

        self.combo_sort = NoWheelComboBox()
        self.combo_sort.addItems(["日付順", "名前順"])
        self.combo_sort.currentIndexChanged.connect(self.refresh_folder_view)
        toolbar.addWidget(self.combo_sort)

        self.open_collection_button = QPushButton("CL"); self.open_collection_button.setFixedWidth(35); toolbar.addWidget(self.open_collection_button)

        self.open_button.setStyleSheet("""
            QPushButton {
                background-color: #555555; color: white; font-weight: bold; padding: 5px;
            }
        """)

        return toolbar        

    def get_sorted_image_files(self, apply_filter=False):
        if not self.current_folder or not os.path.exists(self.current_folder): return []
        files = [f for f in os.listdir(self.current_folder) if f.lower().endswith('.png')]
        if apply_filter and self.text_box.text().strip():
            query = self.text_box.text().strip(); is_neg = query.startswith("-"); pattern_str = query[1:].strip() if is_neg else query
            if pattern_str:
                try:
                    regex = re.compile(pattern_str, re.IGNORECASE)
                    files = [f for f in files if regex.search(self.extract_png_metadata(os.path.join(self.current_folder, f)).get("Negative prompt" if is_neg else "Prompt", ""))]
                except re.error: pass
        #files.sort(key=lambda f: os.path.getmtime(os.path.join(self.current_folder, f)) if self.combo_sort.currentIndex() == 0 else f.lower(), reverse=self.chk_desc.isChecked())
        files.sort(key=lambda f: os.path.getmtime(os.path.join(self.current_folder, f)) if self.combo_sort.currentIndex() == 0 else f.lower(), reverse=False)
        return files

    def refresh_folder_view(self):
        #if self.current_folder and (files := self.get_sorted_image_files(apply_filter=self.slider_popup.chk_filter.isChecked())):
        files = self.get_sorted_image_files(True)
        if files:
            current_name = os.path.basename(self.current_image_path)
            if current_name in files: self.current_index = files.index(current_name)
            else: self.current_index = 0; self.load_image(os.path.join(self.current_folder, files[0]))
            self.update_page_display(len(files))

    def update_page_display(self, total_files=None):
        #if total_files is None: total_files = len(self.get_sorted_image_files(apply_filter=self.slider_popup.chk_filter.isChecked()))
        if total_files is None: total_files = len(self.get_sorted_image_files(apply_filter=True))
        idx_display = self.current_index + 1 if total_files > 0 else 0
        self.lbl_page.setText(f"{idx_display}/{total_files}"); self.slider_popup.update_page_display(idx_display, total_files)

    def on_slider_filter_changed(self):
        self.refresh_folder_view()
        if self.slider_popup.isVisible(): self.show_slider_popup(None)

    def show_tagSelection_ContextMenu(self, position):
        menu = QMenu()
        if self.metadata:
            sendAllAction = menu.addAction("👉 この画像の全パラメータをセット")
            sendAllAction.triggered.connect(lambda: self.send_all_to_forge.emit(self.metadata, False))
            sendAllGenAction = menu.addAction("🚀 全パラメータをセットして生成スタート")
            sendAllGenAction.triggered.connect(lambda: self.send_all_to_forge.emit(self.metadata, True))
            menu.addSeparator()
            
        selectAction = QAction("表示するパラメータを選択...", self); selectAction.triggered.connect(self.selectItems); menu.addAction(selectAction)
        menu.exec(self.metadata_widget.mapToGlobal(position))

    def on_slider_value_changed(self, index):
        if 0 <= index < len(self.slider_popup.image_files):
            self.current_index = index; self.load_image(os.path.join(self.current_folder, self.slider_popup.image_files[index]))

    def show_slider_popup(self, position):
        #if not self.current_folder or not (image_files := self.get_sorted_image_files(apply_filter=self.slider_popup.chk_filter.isChecked())): return
        if not self.current_folder or not (image_files := self.get_sorted_image_files(apply_filter=True)): return

        self.slider_popup.slider.blockSignals(True)
        self.slider_popup.slider.setMaximum(len(image_files) - 1)
        self.slider_popup.image_files = image_files.copy()

        current_name = os.path.basename(self.current_image_path)
        if current_name in image_files:
            self.current_index = image_files.index(current_name)
        self.slider_popup.slider.setValue(self.current_index)
        self.slider_popup.slider.blockSignals(False)
        self.update_page_display(len(image_files))

        if position is not None:
            popup_pos = QCursor.pos() + QPoint(-self.slider_popup.width() // 2, 10)
            screen_rect = QGuiApplication.primaryScreen().geometry()
            popup_pos.setX(max(screen_rect.left(), min(popup_pos.x(), screen_rect.right() - self.slider_popup.width())))
            self.slider_popup.move(popup_pos)
            self.slider_popup.show()

    def selectItems(self):
        dialog = CheckableListDialog(self.metadata.keys(), self)
        for checkbox in dialog.checkboxes:
            if checkbox.text() in self.meta_tags: checkbox.setChecked(True)
        if dialog.exec(): self.meta_tags = dialog.getSelectedItems(); self.display_metadata(self.metadata); self.image_loaded.emit()

    def on_new_folder(self): self.current_folder = self.open_button.current_folder; self.current_index = 0; self.load_first_image(); self.image_loaded.emit()
    def load_first_image(self):
        #if image_files := self.get_sorted_image_files(apply_filter=self.slider_popup.chk_filter.isChecked()): self.load_image(os.path.join(self.current_folder, image_files[0]))
        if image_files := self.get_sorted_image_files(apply_filter=True): self.load_image(os.path.join(self.current_folder, image_files[0]))
        else: self.clear_view_area("No matching png files found")

    def load_image(self, image_path):
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            self.image_label.setPixmap(pixmap.scaled(self.image_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            self.current_image_path, self.image_label.image_path = image_path, image_path
            #files = self.get_sorted_image_files(apply_filter=self.slider_popup.chk_filter.isChecked())
            files = self.get_sorted_image_files(apply_filter=True)
            if os.path.basename(image_path) in files: self.current_index = files.index(os.path.basename(image_path))
            self.update_page_display(len(files)); metadata = self.extract_png_metadata(image_path); self.display_metadata(metadata); self.metadata = metadata
        self.image_loaded.emit()

    def clear_view_area(self, text):
        self.image_label.setText(text)
        #self.image_label.setPixmap(QPixmap())
        self.current_image_path, self.image_label.image_path = "", ""
        while child := self.metadata_layout.takeAt(0):
            if child.widget(): child.widget().deleteLater()
        self.lbl_page.setText("0/0")

    def change_image(self, event):
        if not self.current_folder: return
        #if self.slider_popup.chk_filter.isChecked():
        if 0:
            if not (files := self.get_sorted_image_files(apply_filter=True)): return
            current_idx = files.index(os.path.basename(self.current_image_path)) if os.path.basename(self.current_image_path) in files else 0
            self.load_image(os.path.join(self.current_folder, files[(current_idx + (-1 if event.angleDelta().y() > 0 else 1)) % len(files)]))
        else:
            if not (files := self.get_sorted_image_files(apply_filter=True)): return
            current_idx = files.index(os.path.basename(self.current_image_path)) if os.path.basename(self.current_image_path) in files else 0
            new_idx = (current_idx + (-1 if event.angleDelta().y() > 0 else 1)) % len(files)
            if self.text_box.text().strip():
                query = self.text_box.text().strip(); is_neg = query.startswith("-"); pattern_str = query[1:].strip() if is_neg else query
                if pattern_str:
                    try:
                        regex = re.compile(pattern_str, re.IGNORECASE)
                        for _ in range(len(files)):
                            if regex.search(self.extract_png_metadata(os.path.join(self.current_folder, files[new_idx])).get("Negative prompt" if is_neg else "Prompt", "")):
                                self.load_image(os.path.join(self.current_folder, files[new_idx])); self.refresh_folder_view(); return
                            new_idx = (new_idx + (-1 if event.angleDelta().y() > 0 else 1)) % len(files)
                        return
                    except re.error: pass
            self.load_image(os.path.join(self.current_folder, files[new_idx]))

    def text_entered(self):
        if not self.current_folder or not (files := self.get_sorted_image_files(apply_filter=False)): return
        current_idx = files.index(os.path.basename(self.current_image_path)) if os.path.basename(self.current_image_path) in files else 0
        if not (query := self.text_box.text().strip()): self.refresh_folder_view(); return
        is_neg = query.startswith("-"); pattern_str = query[1:].strip() if is_neg else query
        if pattern_str:
            try:
                regex = re.compile(pattern_str, re.IGNORECASE)
                for _ in range(len(files)):
                    if regex.search(self.extract_png_metadata(os.path.join(self.current_folder, files[current_idx])).get("Negative prompt" if is_neg else "Prompt", "")):
                        self.load_image(os.path.join(self.current_folder, files[current_idx])); self.refresh_folder_view(); return
                    current_idx = (current_idx + 1) % len(files)
                self.clear_view_area("No matching images found")
            except re.error: pass

    def parse_metadata(self, text):
        metadata = {}; neg_prompt_index = text.find("Negative prompt:")
        if neg_prompt_index == -1: neg_prompt_index = text.find("Steps:")
        if neg_prompt_index != -1:
            metadata["Prompt"] = text[:neg_prompt_index].strip(); remaining_text = text[neg_prompt_index:]; steps_index = remaining_text.find("Steps:")
            metadata["Negative prompt"] = remaining_text[:steps_index].replace("Negative prompt:", "").strip()
            for param in remaining_text[steps_index:].split(","):
                if ":" in param: key, value = param.split(":", 1); metadata[key.strip()] = value.strip()
        return metadata

    def extract_comfy_metadata(self, value):
        try:
            metadata = json.loads(value); prompt, others, prompt_tags, text_id = {}, {}, ["Prompt", "Negative prompt"], 0
            for values in metadata.values():
                inputs = values.get("inputs", {})
                if values.get("class_type") == "CLIPTextEncode":
                    if "text" in inputs and text_id < len(prompt_tags): prompt[prompt_tags[text_id]] = str(inputs["text"]); text_id += 1
                else:
                    for k, v in inputs.items(): others[k] = str(v)
            return prompt | others
        except Exception: return {}

    def extract_png_metadata(self, image_path):
        try:
            with Image.open(image_path) as img:
                if isinstance(img, PngImageFile):
                    for key, value in img.info.items():
                        if key.lower() == 'parameters': return self.parse_metadata(value)
                        elif key.lower() == 'prompt': return self.extract_comfy_metadata(value)
        except Exception: pass
        return {}
            
    def display_metadata(self, metadata, clear=True):
        if clear:
            while child := self.metadata_layout.takeAt(0):
                if child.widget(): child.widget().deleteLater()
        for key in self.meta_tags:
            if key in metadata:
                label = MetadataLabel(key, metadata[key])
                self.metadata_layout.addWidget(label)
                label.r_button_clicked.connect(self.selectItems)
                label.send_single_to_forge.connect(self.send_single_to_forge.emit)
                label.send_all_to_forge.connect(lambda auto: self.send_all_to_forge.emit(self.metadata, auto))
        self.metadata_layout.insertWidget(0, MetadataLabel("File", self.current_image_path.replace("\\", "/")))
        self.metadata_layout.addStretch()

    def copy_seed(self):
        for i in range(self.metadata_layout.count()):
            if (item := self.metadata_layout.itemAt(i)) and item.widget() and isinstance(item.widget(), MetadataLabel) and item.widget().label.lower() == "seed":
                QGuiApplication.clipboard().setText(item.widget().value); break

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel and watched == self.image_label: self.change_image(event); return True
        elif event.type() == QEvent.Type.DragEnter and event.mimeData().hasUrls(): event.acceptProposedAction(); return True
        elif event.type() == QEvent.Type.Drop and watched == self.container: self.dropped_image(event); return True
        elif event.type() == QEvent.Type.MouseButtonPress and self.slider_popup.isVisible() and not self.slider_popup.geometry().contains(event.globalPosition().toPoint()):
            self.slider_popup.hide(); return True
        return super().eventFilter(watched, event)
    
    def dropped_image(self, event):
        if (files := [u.toLocalFile() for u in event.mimeData().urls()]) and os.path.isfile(files[0]) and files[0].lower().endswith('.png'):
            self.current_folder = os.path.dirname(files[0]); self.open_button.current_folder = self.current_folder; self.load_image(files[0])

    def on_image_double_click(self, event):
        if self.current_image_path and os.path.exists(self.current_image_path):
            original_view = OriginalViewWindow(self.current_image_path)
            original_view.originalWindowClosed.connect(lambda w: self.original_views.remove(w) if w in self.original_views else None)    
            original_view.show(); self.original_views.append(original_view)


# =====================================================================
# Forge クライアントパネル （右端に展開される生成パネル）
# =====================================================================

class ForgeClientPanel(QWidget):
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread = None
        self.shortcuts = []
        self.init_ui()
        self.load_models()
        self.progress_timer = QTimer(self)
        self.progress_timer.timeout.connect(self.check_forge_progress)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        main_layout.addWidget(self.splitter)

        top_widget = QWidget(); top_layout = QVBoxLayout(top_widget); top_layout.setContentsMargins(5, 5, 5, 5)
        header_layout = QHBoxLayout()
        self.btn_close = QPushButton("◀ パネルを閉じる"); self.btn_close.setStyleSheet("background-color: #555555; color: white; font-weight: bold; padding: 5px;")
        self.btn_close.clicked.connect(lambda: self.close_requested.emit())
        header_layout.addWidget(self.btn_close)
        self.lbl_status = QLabel("待機中..."); self.lbl_status.setStyleSheet("font-weight: bold; font-size: 13px; padding-left: 10px;")
        header_layout.addWidget(self.lbl_status, stretch=1); top_layout.addLayout(header_layout)
        self.preview_label = DraggablePreviewLabel(); self.preview_label.file_dropped.connect(self.on_file_dropped); top_layout.addWidget(self.preview_label, stretch=1)
        self.progress_bar = QProgressBar(); self.progress_bar.setRange(0, 100); self.progress_bar.setValue(0); top_layout.addWidget(self.progress_bar)

        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("▶️ 生成スタート")
        self.btn_start.setStyleSheet("background-color: #4CAF50; color: white; font-size: 14px; font-weight: bold; padding: 10px;")
        self.btn_start.clicked.connect(self.start_generation)
        self.btn_stop_loop = QPushButton("⏹️ ループ停止")
        self.btn_stop_loop.setStyleSheet("background-color: #FF9800; color: white; font-weight: bold;")
        self.btn_stop_loop.setEnabled(False)
        self.btn_stop_loop.clicked.connect(self.stop_loop_only)
        self.btn_interrupt = QPushButton("🛑 中断")
        self.btn_interrupt.setStyleSheet("background-color: #f44336; color: white; font-weight: bold;")
        self.btn_interrupt.setEnabled(False)
        self.btn_interrupt.clicked.connect(self.stop_and_interrupt)
        btn_layout.addWidget(self.btn_start, stretch=3)
        btn_layout.addWidget(self.btn_stop_loop, stretch=1)
        btn_layout.addWidget(self.btn_interrupt, stretch=1)
        top_layout.addLayout(btn_layout)

        self.splitter.addWidget(top_widget)

        scroll_area = QScrollArea(); scroll_area.setWidgetResizable(True); scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        bottom_widget = QWidget(); bottom_layout = QVBoxLayout(bottom_widget); scroll_area.setWidget(bottom_widget); self.splitter.addWidget(scroll_area)

        #bottom_splitter = QSplitter(Qt.Orientation.Vertical)
        #bottom_layout.addWidget(bottom_splitter)

        prompt_group = QGroupBox("1. プロンプト ( Ctrl+↑/↓ 強調, {a|b} 展開 )")
        prompt_group.setMinimumHeight(400)
        prompt_layout = QVBoxLayout(prompt_group)
        prompt_layout.addWidget(QLabel("Prompt:")); self.txt_prompt = PromptTextEdit(); self.txt_prompt.setFont(QFont("Segoe UI", 10)); prompt_layout.addWidget(self.txt_prompt)
        prompt_layout.addWidget(QLabel("Negative Prompt:")); self.txt_neg_prompt = PromptTextEdit(); self.txt_neg_prompt.setFont(QFont("Segoe UI", 10)); prompt_layout.addWidget(self.txt_neg_prompt)
        bottom_layout.addWidget(prompt_group)
        #bottom_splitter.addWidget(prompt_group)

        param_group = QGroupBox("2. 基本パラメータ"); param_layout = QGridLayout(param_group)
        param_layout.addWidget(QLabel("Width:"), 0, 0); self.spin_width = NoWheelSpinBox(); self.spin_width.setRange(64, 2048); self.spin_width.setValue(512); self.spin_width.setSingleStep(64); param_layout.addWidget(self.spin_width, 0, 1)
        btn_swap = QPushButton("⇄"); btn_swap.setFixedWidth(30); btn_swap.clicked.connect(lambda: (w := self.spin_width.value(), self.spin_width.setValue(self.spin_height.value()), self.spin_height.setValue(w))); param_layout.addWidget(btn_swap, 0, 2)
        param_layout.addWidget(QLabel("Height:"), 0, 3); self.spin_height = NoWheelSpinBox(); self.spin_height.setRange(64, 2048); self.spin_height.setValue(768); self.spin_height.setSingleStep(64); param_layout.addWidget(self.spin_height, 0, 4)
        param_layout.addWidget(QLabel("Steps:"), 1, 0); self.edit_steps = QLineEdit("20"); param_layout.addWidget(self.edit_steps, 1, 1, 1, 4)
        param_layout.addWidget(QLabel("CFG:"), 2, 0); self.spin_cfg = NoWheelDoubleSpinBox(); self.spin_cfg.setRange(1.0, 30.0); self.spin_cfg.setValue(7.0); self.spin_cfg.setSingleStep(0.5); param_layout.addWidget(self.spin_cfg, 2, 1, 1, 4)
        param_layout.addWidget(QLabel("Sampler:"), 3, 0); self.edit_sampler = QLineEdit("Euler a"); param_layout.addWidget(self.edit_sampler, 3, 1, 1, 4)

        param_layout.addWidget(QLabel("Seed:"), 4, 0)
        self.edit_seed = QLineEdit("-1")
        param_layout.addWidget(self.edit_seed, 4, 1, 1, 2)
        btn_random_seed = QPushButton("🎲 -1")
        btn_random_seed.clicked.connect(lambda: self.edit_seed.setText("-1"))
        param_layout.addWidget(btn_random_seed, 4, 3)
        btn_get_seed = QPushButton("♻️ 取得")
        btn_get_seed.setToolTip("プレビュー画像のSeed値を取得します")
        btn_get_seed.clicked.connect(self.get_preview_seed)
        param_layout.addWidget(btn_get_seed, 4, 4)
        bottom_layout.addWidget(param_group)
        #bottom_splitter.addWidget(param_group)

        top_group = QGroupBox("3. 保存先 ＆ モデル (Checkpoint)"); top_g_layout = QVBoxLayout(top_group)
        dir_layout = QHBoxLayout(); dir_layout.addWidget(QLabel("保存:")); self.edit_out_dir = QLineEdit(os.path.abspath(DEFAULT_OUTPUT_DIR))
        btn_browse_dir = QPushButton("📁"); btn_browse_dir.setFixedWidth(35); btn_browse_dir.clicked.connect(self.browse_output_dir); dir_layout.addWidget(self.edit_out_dir); dir_layout.addWidget(btn_browse_dir); top_g_layout.addLayout(dir_layout)
        model_layout = QHBoxLayout(); self.combo_model = NoWheelComboBox(); btn_refresh_models = QPushButton("🔄"); btn_refresh_models.setFixedWidth(35); btn_refresh_models.clicked.connect(self.load_models)
        model_layout.addWidget(self.combo_model, stretch=1); model_layout.addWidget(btn_refresh_models); top_g_layout.addLayout(model_layout)

        bottom_layout.addWidget(top_group)
        #bottom_splitter.addWidget(top_group)

        monitor_group = QGroupBox("4. インターバル＆制御"); monitor_layout = QGridLayout(monitor_group)
        monitor_layout.addWidget(QLabel("待機 (秒):"), 0, 0); self.spin_interval = NoWheelSpinBox(); self.spin_interval.setRange(0, 3600); self.spin_interval.setValue(30); monitor_layout.addWidget(self.spin_interval, 0, 1)
        monitor_layout.addWidget(QLabel("上限温度:"), 0, 2); self.spin_temp = NoWheelDoubleSpinBox(); self.spin_temp.setRange(30.0, 100.0); self.spin_temp.setValue(50.0); monitor_layout.addWidget(self.spin_temp, 0, 3)
        self.chk_fixed_seed = QCheckBox("Fixed seed (組合せ時固定)"); self.chk_fixed_seed.setChecked(True); monitor_layout.addWidget(self.chk_fixed_seed, 1, 0, 1, 2)
        self.chk_forever = QCheckBox("∞ 無限ループ生成"); self.chk_forever.setStyleSheet("color: #FF9800; font-weight: bold;"); monitor_layout.addWidget(self.chk_forever, 1, 2, 1, 2)
        bottom_layout.addWidget(monitor_group)
        #bottom_splitter.addWidget(monitor_group)        

        self.splitter.setSizes([300, 600])

        # 各UI要素の変更を検知する
        self.txt_prompt.textChanged.connect(self.on_ui_parameter_changed)
        self.txt_neg_prompt.textChanged.connect(self.on_ui_parameter_changed)
        self.spin_width.valueChanged.connect(self.on_ui_parameter_changed)
        self.spin_height.valueChanged.connect(self.on_ui_parameter_changed)
        self.edit_steps.textChanged.connect(self.on_ui_parameter_changed)
        self.spin_cfg.valueChanged.connect(self.on_ui_parameter_changed)
        self.edit_sampler.textChanged.connect(self.on_ui_parameter_changed)
        self.edit_seed.textChanged.connect(self.on_ui_parameter_changed)
        self.chk_fixed_seed.stateChanged.connect(self.on_ui_parameter_changed)
        self.combo_model.currentIndexChanged.connect(self.on_ui_parameter_changed)        
        self.spin_interval.valueChanged.connect(self.on_ui_parameter_changed)
        self.spin_temp.valueChanged.connect(self.on_ui_parameter_changed)        

    def browse_output_dir(self):
        if d := QFileDialog.getExistingDirectory(self, "保存先フォルダの選択", self.edit_out_dir.text()):
            self.edit_out_dir.setText(os.path.normpath(d))

    def load_models(self):
        self.lbl_status.setText("🔄 モデル一覧を取得中...")
        QApplication.processEvents()
        try:
            res = requests.get(f"{FORGE_URL}/sdapi/v1/sd-models", timeout=3); res.raise_for_status(); models = res.json()
            self.combo_model.clear()
            for m in models: self.combo_model.addItem(m["title"], m["model_name"])
            self.lbl_status.setText(f"✨ {len(models)} 個のモデルをロード")
        except Exception: self.lbl_status.setText("⚠️ Forge未接続 (--api を確認)")

    def on_file_dropped(self, filepath: str):
        self.lbl_status.setText(f"📂 読込中: {os.path.basename(filepath)}")
        self.preview_label.set_preview_image(filepath)
        viewer_dummy = ImageView(99)
        meta = viewer_dummy.extract_png_metadata(filepath)
        if meta:
            self.set_all_parameters(meta, auto_start=False)
            self.lbl_status.setText("✨ パラメータを反映しました！")

    def set_all_parameters(self, meta: dict, auto_start=False):
        if "Prompt" in meta: self.txt_prompt.setText(meta["Prompt"])
        if "Negative prompt" in meta: self.txt_neg_prompt.setText(meta["Negative prompt"])
        if "Steps" in meta: self.edit_steps.setText(str(meta["Steps"]))
        if "CFG scale" in meta:
            try: self.spin_cfg.setValue(float(meta["CFG scale"]))
            except: pass
        if "Sampler" in meta: self.edit_sampler.setText(meta["Sampler"])
        if "Seed" in meta: self.edit_seed.setText(str(meta["Seed"]))
        if "Size" in meta and "x" in str(meta["Size"]):
            try:
                w, h = str(meta["Size"]).split("x")
                self.spin_width.setValue(int(w.strip())); self.spin_height.setValue(int(h.strip()))
            except: pass
        if "Model" in meta:
            target = meta["Model"]
            for i in range(self.combo_model.count()):
                if target.lower() in self.combo_model.itemText(i).lower(): self.combo_model.setCurrentIndex(i); break
        if auto_start: self.start_generation()

    def set_single_parameter(self, label: str, value: str, auto_start=False):
        lbl = label.lower()
        if lbl == "prompt": self.txt_prompt.setText(value)
        elif lbl == "negative prompt": self.txt_neg_prompt.setText(value)
        elif lbl == "steps": self.edit_steps.setText(str(value))
        elif lbl == "cfg scale":
            try: self.spin_cfg.setValue(float(value))
            except: pass
        elif lbl == "sampler": self.edit_sampler.setText(value)
        elif lbl == "seed": self.edit_seed.setText(str(value))
        elif lbl == "size" and "x" in value:
            try:
                w, h = value.split("x")
                self.spin_width.setValue(int(w.strip())); self.spin_height.setValue(int(h.strip()))
            except: pass
        elif lbl == "model":
            for i in range(self.combo_model.count()):
                if value.lower() in self.combo_model.itemText(i).lower(): self.combo_model.setCurrentIndex(i); break
        if auto_start: self.start_generation()

    def start_generation(self):
        # 既に生成スレッドが動いている場合は、「パラメータ更新」として処理を分岐
        if self.thread and self.thread.isRunning():
            self.apply_parameters_to_loop()
            # ボタンを再び「変更なし（クリック不可）」の状態に戻す
            self.btn_start.setEnabled(False)
            self.btn_start.setText("⚙️ 生成処理中...")
            self.btn_start.setStyleSheet("background-color: #FF9800; color: white; font-weight: bold; padding: 10px;")
            return
        
        try: seed_val = int(self.edit_seed.text().strip())
        except ValueError: seed_val = -1; self.edit_seed.setText("-1")
        steps_list = [int(s.strip()) for s in self.edit_steps.text().strip().split(',') if s.strip().isdigit()] or [20]
        base_payload = {
            "prompt": self.txt_prompt.toPlainText(), "negative_prompt": self.txt_neg_prompt.toPlainText(),
            "width": self.spin_width.value(), "height": self.spin_height.value(),
            "cfg_scale": self.spin_cfg.value(), "sampler_name": self.edit_sampler.text().strip(), "seed": seed_val
        }
        tasks = create_generation_tasks(base_payload, steps_list, 1, self.chk_fixed_seed.isChecked())
        if not tasks: return
        self.btn_start.setStyleSheet("background-color: #FF9800; color: white; font-weight: bold; padding: 10px;")
        self.btn_start.setText("⚙️ 生成処理中...")
        self.btn_start.setEnabled(False)
        self.btn_stop_loop.setEnabled(True)
        self.btn_interrupt.setEnabled(True)
        self.progress_bar.setValue(0)

        target_model = self.combo_model.itemText(self.combo_model.currentIndex()) if self.combo_model.count() > 0 else ""

        #self.thread = GenerationThread(tasks, self.spin_interval.value(), self.spin_temp.value(), target_model, self.edit_out_dir.text().strip(), self.chk_forever.isChecked())
        self.thread = GenerationThread(
            tasks, self.spin_interval.value(), self.spin_temp.value(), 
            target_model, self.edit_out_dir.text().strip(), 
            self.chk_forever.isChecked(), self.chk_fixed_seed.isChecked()
        )
        self.thread.status_updated.connect(self.lbl_status.setText)
        self.thread.image_generated.connect(self.on_image_generated)
        self.thread.error_occurred.connect(self.on_generation_error)
        self.thread.finished_all.connect(self.on_generation_finished)
        self.thread.start()
        self.thread.generation_started.connect(self.on_generation_started)
        self.progress_timer.start(1000)

    def apply_parameters_to_loop(self):
        """スレッドへ次回のループに適用するパラメータを渡す"""
        try: seed_val = int(self.edit_seed.text().strip())
        except ValueError: seed_val = -1
        
        steps_list = [int(s.strip()) for s in self.edit_steps.text().strip().split(',') if s.strip().isdigit()] or [20]
        base_payload = {
            "prompt": self.txt_prompt.toPlainText(), "negative_prompt": self.txt_neg_prompt.toPlainText(),
            "width": self.spin_width.value(), "height": self.spin_height.value(),
            "cfg_scale": self.spin_cfg.value(), "sampler_name": self.edit_sampler.text().strip(), "seed": seed_val
        }
        
        # スレッド側の更新メソッドを呼ぶ（前回提示した GenerationThread.update_parameters）
        self.thread.update_parameters(
            base_payload,
            steps_list,
            self.chk_fixed_seed.isChecked(),
            self.spin_interval.value(),
            self.spin_temp.value()
        )
        self.lbl_status.setText("🔄 次の画像から変更されたパラメータを適用します")

    def get_preview_seed(self):
        """プレビュー表示中の画像からSeed値を取得して入力欄にセットする"""
        if hasattr(self.preview_label, 'image_path') and self.preview_label.image_path:
            # 既に実装されている抽出用ダミーを利用
            viewer_dummy = ImageView(99)
            meta = viewer_dummy.extract_png_metadata(self.preview_label.image_path)
            
            if "Seed" in meta:
                self.edit_seed.setText(str(meta["Seed"]))
                self.lbl_status.setText(f"✨ Seed [{meta['Seed']}] を取得しました")
            else:
                QMessageBox.warning(self, "エラー", "この画像からはSeed値が読み取れませんでした。")
        else:
            QMessageBox.information(self, "通知", "プレビュー画像がありません。")

    def check_forge_progress(self):
        try:
            res = requests.get(f"{FORGE_URL}/sdapi/v1/progress", timeout=1)
            if res.status_code == 200:
                progress_val = res.json().get("progress", 0.0)
                step_val = int((progress_val * 100) // 20) * 20
                if step_val < self.progress_bar.value():
                    step_val = self.progress_bar.value()
                self.progress_bar.setValue(step_val)
        except Exception: pass

    def on_ui_parameter_changed(self):  
        """UIの値が変更された時に呼ばれる"""
        # スレッドが動いている（生成ループ中）場合のみボタンを「更新用」に切り替える
        if self.thread and self.thread.isRunning():
            self.btn_start.setEnabled(True)
            self.btn_start.setText("🔄 変更を適用して継続")
            self.btn_start.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold; padding: 10px;") # 青色にして目立たせる

    def stop_loop_only(self):
        if self.thread and self.thread.isRunning(): self.lbl_status.setText("⏹️ 完了次第停止します..."); self.thread.stop_loop_only(); self.btn_stop_loop.setEnabled(False)
    def stop_and_interrupt(self):
        if self.thread and self.thread.isRunning(): self.lbl_status.setText("🛑 キャンセル送信中..."); self.thread.stop_and_interrupt(); self.btn_stop_loop.setEnabled(False); self.btn_interrupt.setEnabled(False)
    def on_image_generated(self, filepath: str, info: str, seed: int): self.preview_label.set_preview_image(filepath); self.progress_bar.setValue(100)
    def on_generation_error(self, err_msg: str): QMessageBox.critical(self, "生成エラー", err_msg); self.on_generation_finished()

    def on_generation_finished(self):
        self.progress_timer.stop()
        self.progress_bar.setValue(100)
        self.lbl_status.setText("✨ 生成完了")
        self.btn_start.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 10px;")
        self.btn_start.setText("▶️ 生成スタート")
        self.btn_start.setEnabled(True) 
        self.btn_stop_loop.setEnabled(False)
        self.btn_interrupt.setEnabled(False)

    def on_generation_started(self):
        self.progress_bar.setValue(0)


# =====================================================================
# メイン統合ウィンドウ
# =====================================================================

class ImageViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Metadata Viewer & Forge Client Integrated")
        self.resize(850, 900)
        self.panel_default_width = 500
        
        # 1350px壁解決策①：開く前のウィンドウサイズを記憶するための変数
        self.saved_viewer_width = None
        
        self.central_widget = QWidget(); self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget); self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal); self.main_layout.addWidget(self.main_splitter)
        self.tab_widget = QTabWidget(); self.main_splitter.addWidget(self.tab_widget)

        self.s_view = QWidget(); layout_s = QVBoxLayout(self.s_view)
        self.m_view = ImageView(0)
        send_button = QPushButton("Send →"); self.m_view.toolbar.addWidget(send_button)      
        send_button.clicked.connect(partial(self.send_to, 0, 1)); send_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); send_button.customContextMenuRequested.connect(self.show_send_context_menu)
        layout_s.addWidget(self.m_view.container); self.tab_widget.addTab(self.s_view, "シングル")

        self.c_view = QWidget(); layout_c = QHBoxLayout(self.c_view)
        self.l_view = ImageView(1); self.r_view = ImageView(2)
        send_button1 = QPushButton("←"); send_button1.setFixedWidth(30); self.l_view.toolbar.addWidget(send_button1); send_button1.clicked.connect(partial(self.send_to, 1, 0)); send_button1.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); send_button1.customContextMenuRequested.connect(self.show_send_context_menu); layout_c.addWidget(self.l_view.container)
        send_button2 = QPushButton("←←"); send_button2.setFixedWidth(30); self.r_view.toolbar.addWidget(send_button2); send_button2.clicked.connect(partial(self.send_to, 2, 0)); send_button2.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); send_button2.customContextMenuRequested.connect(self.show_send_context_menu); layout_c.addWidget(self.r_view.container)

        self.collection_windows, self.collection_idx = [], 0
        self.l_view.image_loaded.connect(self.compare_metadata); self.r_view.image_loaded.connect(self.compare_metadata); self.l_view.metaarea_changed.connect(self.compare_metadata); self.r_view.metaarea_changed.connect(self.compare_metadata)
        self.tab_widget.addTab(self.c_view, "比較"); self.tab_widget.currentChanged.connect(self.on_tab_changed)

        self.views = [self.m_view, self.l_view, self.r_view]
        self.cp_tags = ["Prompt", "Negative prompt", "Steps", "Sampler", "CFG scale", "Seed", "Size", "Model", "VAE", "Denoising strength", "Variation seed", "Variation seed strength", "Clip skip"]
        for view in self.views:
            view.area_resized.connect(self.update_images); view.open_collection_button.clicked.connect(self.create_collection)
            view.send_all_to_forge.connect(self.on_send_all_to_forge); view.send_single_to_forge.connect(self.on_send_single_to_forge)

        self.forge_panel = ForgeClientPanel(self)
        self.main_splitter.addWidget(self.forge_panel)
        self.forge_panel.hide()
        self.forge_panel.close_requested.connect(self.close_forge_panel)

    def open_forge_panel_if_hidden(self):
        if self.forge_panel.isHidden():
            # 開く前のサイズを確実に記憶する！
            self.saved_viewer_width = self.width()
            self.forge_panel.setMinimumWidth(500) # 開くときはパネル最小幅を復活
            self.resize(self.saved_viewer_width + self.panel_default_width + 5, self.height())
            self.forge_panel.show()
            self.main_splitter.setSizes([self.saved_viewer_width, self.panel_default_width])

    def close_forge_panel(self):
        if not self.forge_panel.isHidden():
            self.forge_panel.hide()
            # 1350px壁解決策②：隠す際に「パネル最小サイズ制限」を0にリセットしてQtの呪縛を解く！
            self.forge_panel.setMinimumWidth(0)
            self.setMinimumWidth(600) # ウィンドウ全体の最小制限も一時解除
            self.updateGeometry()     # Qtにサイズ制限の再計算を強制する
            
            # 記憶していた元の幅へ1ピクセルのズレもなく復元（記憶がなければ引き算）
            #target_width = self.saved_viewer_width if self.saved_viewer_width else max(600, self.width() - self.panel_default_width)
            if self.forge_panel.width() == 500:
                target_width = self.saved_viewer_width
            else:
                target_width = max(600, self.width() - self.forge_panel.width() - 5)

            self.resize(target_width, self.height())

    def on_send_all_to_forge(self, meta: dict, auto_start: bool):
        self.open_forge_panel_if_hidden(); self.forge_panel.set_all_parameters(meta, auto_start=auto_start)
    def on_send_single_to_forge(self, label: str, value: str, auto_start: bool):
        self.open_forge_panel_if_hidden(); self.forge_panel.set_single_parameter(label, value, auto_start=auto_start)
    def show_send_context_menu(self, pos):
        sender = self.sender(); menu = QMenu(); send_move = menu.addAction("送って移動")
        if sender.text() == "Send →": send_move.setEnabled(self.m_view.current_folder != ""); send_move.triggered.connect(partial(self.send_and_move, 0, 1))
        elif sender.text() == "←": send_move.setEnabled(self.l_view.current_folder != ""); send_move.triggered.connect(partial(self.send_and_move, 1, 0))
        elif sender.text() == "←←": send_move.setEnabled(self.r_view.current_folder != ""); send_move.triggered.connect(partial(self.send_and_move, 2, 0))
        menu.exec(sender.mapToGlobal(pos))
    def send_and_move(self, source, target): self.send_to(source, target); self.tab_widget.setCurrentIndex(target)
    def compare_metadata(self):
        if self.l_view.current_image_path and self.r_view.current_image_path:
            left_metadata, right_metadata = self.l_view.metadata, self.r_view.metadata
            if not left_metadata or not right_metadata: self.l_view.display_metadata(self.l_view.metadata); self.r_view.display_metadata(self.r_view.metadata); return
        elif self.l_view.current_image_path: self.l_view.display_metadata(self.l_view.metadata); return
        elif self.r_view.current_image_path: self.r_view.display_metadata(self.r_view.metadata); return
        else: return
        left_layout, right_layout = self.l_view.metadata_layout, self.r_view.metadata_layout
        while child := left_layout.takeAt(0):
            if child.widget(): child.widget().deleteLater()
        while child := right_layout.takeAt(0):
            if child.widget(): child.widget().deleteLater()
        l_enable_tags, r_enable_tags, all_tag = self.l_view.meta_tags, self.r_view.meta_tags, list(left_metadata.keys())
        for item in right_metadata.keys():
            if item not in all_tag: all_tag.append(item)        
        self.cp_tags = all_tag.copy()

        for key in self.cp_tags[0:2]:
            left_value, right_value = left_metadata.get(key, ""), right_metadata.get(key, "")
            only_in_left, only_in_right = set([s.strip() for s in left_value.split(",") if s.strip()]) - set([s.strip() for s in right_value.split(",") if s.strip()]), set([s.strip() for s in right_value.split(",") if s.strip()]) - set([s.strip() for s in left_value.split(",") if s.strip()])
            if key in l_enable_tags:
                left_label = MetadataLabel(key, left_value); left_label.r_button_clicked.connect(self.l_view.selectItems); left_label.send_single_to_forge.connect(self.on_send_single_to_forge); left_label.send_all_to_forge.connect(lambda auto: self.on_send_all_to_forge(self.l_view.metadata, auto)); left_layout.addWidget(left_label); left_label.apply_highlight(only_in_left, "#ffff80")
            if key in r_enable_tags:
                right_label = MetadataLabel(key, right_value); right_label.r_button_clicked.connect(self.r_view.selectItems); right_label.send_single_to_forge.connect(self.on_send_single_to_forge); right_label.send_all_to_forge.connect(lambda auto: self.on_send_all_to_forge(self.r_view.metadata, auto)); right_layout.addWidget(right_label); right_label.apply_highlight(only_in_right, "#80ffff")

        for key in self.cp_tags[2:]:
            left_value, right_value = left_metadata.get(key, ""), right_metadata.get(key, "")
            if key in l_enable_tags and left_value:
                left_label = MetadataLabel(key, left_value); left_label.r_button_clicked.connect(self.l_view.selectItems); left_label.send_single_to_forge.connect(self.on_send_single_to_forge); left_label.send_all_to_forge.connect(lambda auto: self.on_send_all_to_forge(self.l_view.metadata, auto)); left_layout.addWidget(left_label)
            if key in r_enable_tags and right_value:
                right_label = MetadataLabel(key, right_value); right_label.r_button_clicked.connect(self.r_view.selectItems); right_label.send_single_to_forge.connect(self.on_send_single_to_forge); right_label.send_all_to_forge.connect(lambda auto: self.on_send_all_to_forge(self.r_view.metadata, auto)); right_layout.addWidget(right_label)
            if left_value != right_value:
                if key in l_enable_tags and left_value: left_label.update_text(highlight=True)
                if key in r_enable_tags and right_value: right_label.update_text(highlight=True)
        left_layout.addStretch(); right_layout.addStretch()
        left_layout.insertWidget(0, MetadataLabel("File", self.l_view.current_image_path.replace("\\", "/")))
        right_layout.insertWidget(0, MetadataLabel("File", self.r_view.current_image_path.replace("\\", "/")))
            
    def send_to(self, source, target):
        self.views[target].current_folder, self.views[target].current_image_path, self.views[target].image_label.image_path = self.views[source].current_folder, self.views[source].current_image_path, self.views[source].current_image_path
        self.views[target].load_image(self.views[target].current_image_path); self.views[target].open_button.current_folder = self.views[source].current_folder; self.resize_image(target)
    def resize_image(self, view_id):
        view = self.views[view_id]
        if os.path.isfile(view.current_image_path):
            sizes = view.splitter.sizes(); img = QPixmap(view.current_image_path)
            view.image_label.setPixmap(img.scaled(view.image_label.width(), sizes[0], Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        elif view.current_folder and view.current_image_path: view.clear_view_area("png file deleted")
    def on_tab_changed(self, index):
        if index == 0: self.resize_image(self.m_view.set_id)
        elif index == 1: self.resize_image(self.l_view.set_id); self.resize_image(self.r_view.set_id); self.compare_metadata()
    def update_images(self, set_id):
        if set_id == 1:
            self.resize_image(1); sizes = self.l_view.splitter.sizes()
            if os.path.isfile(self.r_view.current_image_path):
                img2 = QPixmap(self.r_view.current_image_path); self.r_view.image_label.setPixmap(img2.scaled(self.l_view.image_label.width(), sizes[0], Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            elif self.r_view.current_folder and self.r_view.current_image_path: self.r_view.clear_view_area("png file deleted")
            self.r_view.splitter.setSizes(sizes)
        elif set_id in (0, 2): self.resize_image(set_id)
    def create_collection(self):
        collection = CollectionWindow(self); collection.setGeometry(self.x() + int(self.width() / 2), 200, 700, 220); collection.setWindowTitle("Collection " + str(self.collection_idx)); collection.show()
        self.collection_idx += 1; self.collection_windows.append(collection)
    def remove_collection(self, collection):
        if collection in self.collection_windows: self.collection_windows.remove(collection)
    def resizeEvent(self, event):
        if self.tab_widget.currentIndex() == 0: self.resize_image(self.m_view.set_id)
        else: self.resize_image(self.l_view.set_id); self.resize_image(self.r_view.set_id)
        super().resizeEvent(event)


if __name__ == '__main__':
    app = QApplication([])
    app.setStyle("Fusion")
    viewer = ImageViewer()
    viewer.show()
    app.exec()