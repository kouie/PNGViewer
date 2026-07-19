import os
import re
import json
import time
from datetime import datetime
from pathlib import Path
from PIL import Image
from PIL.PngImagePlugin import PngImageFile
from functools import partial

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSplitter, QPushButton, QTextEdit, QFileDialog, QTabWidget,
    QScrollArea, QFrame, QLineEdit, QLayout, QDialog, QCheckBox,
    QMenu, QSlider, QComboBox, QListWidget, QListWidgetItem, QMessageBox, QWidgetAction
)
from PySide6.QtCore import Qt, QSize, QRect, QPoint, Signal, QMimeData, QUrl, QByteArray, QEvent
from PySide6.QtGui import (
    QPixmap, QDragEnterEvent, QDropEvent, QColor, QDrag, QCursor,
    QGuiApplication, QFont, QIcon, QAction 
)

COLLECTIONS_DIR = "collections"
os.makedirs(COLLECTIONS_DIR, exist_ok=True)

class MetadataLabel(QLabel):
    r_button_clicked = Signal()

    def __init__(self, label="", value="", parent=None):
        super().__init__(parent)
        self.label = label
        self.value = value
        self.setFont(QFont('SansSerif', 11))
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setWordWrap(True) 
        self.update_text()
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    def update_text(self, highlight=False):
        if highlight:
            self.setText(f"<b>{self.label}:</b> <span style='background-color: #FFEB3B'>{self.value}</span>")
        else:
            value = self.value.replace("\n", "<br>")
            self.setText(f"<b>{self.label}:</b> {value}")

    def apply_highlight(self, words_to_highlight, color):
        all_text = self.value 
        for word in words_to_highlight:
            htext = '<span style="background-color: '+color+';">'+word+'</span>'
            all_text = all_text.replace(word, htext)

        all_text = all_text.replace("\n", "<br>")
        self.setText(f"<b>{self.label}:</b> {all_text}")

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        copyAction = menu.addAction("コピー")
        copyAction.triggered.connect(self.copy)
        selectAllAction = menu.addAction("項目の値をコピー")
        selectAllAction.triggered.connect(self.selectAll)
        menu.addSeparator()
        customAction = menu.addAction("項目を選択...")
        customAction.triggered.connect(self.on_r_mouse_clicked)
        menu.exec(event.globalPos())

    def on_r_mouse_clicked(self):
        self.r_button_clicked.emit()

    def copy(self):
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(self.selectedText())
    
    def selectAll(self):
        clipboard = QGuiApplication.clipboard()        
        clipboard.setText(self.value)


class CheckableListDialog(QDialog):
    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.setWindowTitle("項目選択")
        self.resize(180, 400)
        self.layout = QVBoxLayout(self)
        self.checkboxes = []
        for item in items:
            checkbox = QCheckBox(item)
            self.checkboxes.append(checkbox)
            self.layout.addWidget(checkbox)
        
        self.okButton = QPushButton("OK")
        self.okButton.clicked.connect(self.accept)
        self.layout.addWidget(self.okButton)
    
    def getSelectedItems(self):
        return [cb.text() for cb in self.checkboxes if cb.isChecked()]


class OpenNavigationButton(QPushButton):
    new_folder = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.current_folder = ""
        self.pinned_folders = []
        self.folder_history = []
        self.history_index = -1

        self.clicked.connect(self.open_folder)
        self.customContextMenuRequested.connect(self.show_context_menu)        

    def create_pinned_folder_widget(self, folder):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(20, 0, 5, 0)
        folder_name = os.path.basename(folder) or folder
        label = QLabel(folder_name)
        label.setToolTip(folder)
    
        delete_button = QPushButton("×")
        delete_button.setFixedSize(20, 20)
        delete_button.setToolTip("ピン留め解除")
        delete_button.clicked.connect(lambda: self.unpin_folder(folder))
    
        layout.addWidget(label)
        layout.addStretch()
        layout.addWidget(delete_button)
        widget.setMouseTracking(True)
        widget.setCursor(Qt.CursorShape.PointingHandCursor)
        return widget
    
    def handle_pinned_folder_click(self, event, folder):
        if event.button() == Qt.MouseButton.LeftButton:
            child_widget = self.childAt(event.pos())
            if not isinstance(child_widget, QPushButton):
                self.navigate_to_folder(folder)

    def navigate_to_folder(self, folder):
        if not os.path.exists(folder):
            QMessageBox.warning(self, "エラー", f"フォルダが見つかりません: {folder}")
            return
        if self.current_folder:
            if self.history_index < len(self.folder_history) - 1:
                self.folder_history = self.folder_history[:self.history_index + 1]
            self.folder_history.append(self.current_folder)
            self.history_index = len(self.folder_history) - 1
            
        self.current_folder = folder
        self.new_folder.emit()

    def unpin_folder(self, folder):
        if folder in self.pinned_folders:
            self.pinned_folders.remove(folder)

    def show_context_menu(self, pos):
        menu = QMenu(self)
        m_next = menu.addAction("次のフォルダ")
        m_next.setEnabled(self.current_folder != "")
        m_next.triggered.connect(partial(self.move_folder, 1))
        m_prev = menu.addAction("前のフォルダ")
        m_prev.setEnabled(self.current_folder != "")
        m_prev.triggered.connect(partial(self.move_folder, -1))
        pinning = menu.addAction("ピン留めする")  
        pinning.setEnabled(self.current_folder != "" and self.current_folder not in self.pinned_folders)
        pinning.triggered.connect(self.pin_current_folder)

        if self.pinned_folders:
            menu.addSeparator()       
            for folder in self.pinned_folders:
                widget = self.create_pinned_folder_widget(folder)
                widget.mouseReleaseEvent = lambda event, f=folder: self.handle_pinned_folder_click(event, f)
                # 【修正1】 QWidgetAction を正しく使用してエラーを回避
                widget_action = QWidgetAction(menu)
                widget_action.setDefaultWidget(widget)
                menu.addAction(widget_action)
        
        menu.exec(self.mapToGlobal(pos))

    def pin_current_folder(self):
        if self.current_folder and self.current_folder not in self.pinned_folders:
            self.pinned_folders.append(self.current_folder)

    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder", self.current_folder)
        if folder:
            self.current_folder = folder
            self.new_folder.emit()

    def move_folder(self, direction):
        parent_folder = Path(self.current_folder).parent
        folders = [f for f in os.listdir(parent_folder) if os.path.isdir(parent_folder / f)]
        if not folders:
            return
        foldername = Path(self.current_folder).name
        try:
            current_index = folders.index(foldername)
            new_index = (current_index + direction) % len(folders)
            new_folder_name = parent_folder / folders[new_index]
            self.current_folder = str(new_folder_name).replace("\\", "/")
            self.new_folder.emit()
        except ValueError:
            pass


class DraggableImageLabel(QLabel):
    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        if image_path and os.path.exists(image_path):
            self.setPixmap(QPixmap(image_path))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.pixmap() is None or self.pixmap().isNull():
                return
            self.drag_start_position = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.pixmap() is None or self.pixmap().isNull():
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if (event.pos() - self.drag_start_position).manhattanLength() < QApplication.startDragDistance():
            return

        drag = QDrag(self)
        mime_data = QMimeData()
        file_url = QUrl.fromLocalFile(os.path.abspath(self.image_path))
        mime_data.setUrls([file_url])
        self.setup_mime_data(mime_data)
        drag.setMimeData(mime_data)
        
        preview_pixmap = self.pixmap().scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatio)
        drag.setPixmap(preview_pixmap)
        drag.setHotSpot(QPoint(int(preview_pixmap.width() / 2), int(preview_pixmap.height() / 2)))
        drag.exec(Qt.DropAction.CopyAction)

    def setup_mime_data(self, mime_data):
        mime_data.setData("application/x-imageviewer", QByteArray(self.image_path.encode()))        


class ViewerDraggableLabel(DraggableImageLabel):
    deleteRequested = Signal(str)

    def __init__(self, image_path, parent=None):
        super().__init__(image_path, parent)        
        self.setAcceptDrops(True)     
        self.thumbnail_size = 130   
        self.setFixedSize(self.thumbnail_size + 8, self.thumbnail_size + 8)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.showContextMenu)

    def setup_mime_data(self, mime_data):
        super().setup_mime_data(mime_data)
        mime_data.setData("application/x-image-sortable", QByteArray(self.image_path.encode()))
        
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasFormat("application/x-image-sortable"):
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasFormat("application/x-image-sortable"):
            source_path = event.mimeData().data("application/x-image-sortable").data().decode()
            target_path = self.image_path
            if source_path == target_path:
                event.ignore()
                return
            parent = self.parent()
            while parent:
                if isinstance(parent, CollectionWidget):
                    parent.swapImages(source_path, target_path)
                    event.acceptProposedAction()
                    break
                parent = parent.parent()
        else:
            event.ignore()

    def showContextMenu(self, position):
        context_menu = QMenu(self)
        delete_action = context_menu.addAction("削除")
        delete_action.triggered.connect(lambda: self.deleteRequested.emit(self.image_path))
        context_menu.exec(self.mapToGlobal(position))

    def mouseDoubleClickEvent(self, event):
        if self.image_path and os.path.exists(self.image_path):
            original_view = OriginalViewWindow(self.image_path)
            original_view.show()
            if not hasattr(QApplication.instance(), "_original_windows"):
                QApplication.instance()._original_windows = []
            QApplication.instance()._original_windows.append(original_view)
            original_view.originalWindowClosed.connect(
                lambda w: QApplication.instance()._original_windows.remove(w) if w in QApplication.instance()._original_windows else None
            )


class SliderPopup(QFrame):
    filter_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)
        self.setWindowFlags(Qt.WindowType.Popup)

        self.image_files = []
        self.current_index = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(0)
        layout.addWidget(self.slider)
        
        self.lbl_page = QLabel("0/0")
        self.lbl_page.setFont(QFont('SansSerif', 9, QFont.Weight.Bold))
        self.lbl_page.setMinimumWidth(60)
        self.lbl_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_page)
        
        # 【修正2】 Sフィルタチェックボックスをスライダ側に移動
        self.chk_filter = QCheckBox("フィルタ適用")
        self.chk_filter.setToolTip("テキストボックスに入力された条件でリストを絞り込みます")
        self.chk_filter.stateChanged.connect(lambda state: self.filter_changed.emit(state != 0))
        layout.addWidget(self.chk_filter)
        
        self.setFixedWidth(420)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        event.accept()

    def update_page_display(self, index, total):
        self.lbl_page.setText(f"{index}/{total}" if total > 0 else "0/0")


class FlowLayout(QLayout):    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContentsMargins(5, 5, 5, 5)
        self.setSpacing(5)
        self.items = []
    
    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)
    
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

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.do_layout(rect)
        
    def do_layout(self, rect):
        x, y, line_height, layout_spacing = rect.x(), rect.y(), 0, self.spacing()
        for item in self.items:
            next_x = x + item.sizeHint().width() + layout_spacing
            if next_x - layout_spacing > rect.right() and line_height > 0:
                x, y = rect.x(), y + line_height + layout_spacing
                next_x = x + item.sizeHint().width() + layout_spacing
                line_height = 0
            item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = next_x
            line_height = max(line_height, item.sizeHint().height())
        return y + line_height - rect.y()


class CollectionWidget(QWidget):
    image_selected = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.images = []
        self.thumbnails = []
        self.thumbnail_map = {}
        self.setMinimumWidth(170)
        self.init_ui()

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        toolbar_layout = QHBoxLayout()
        
        self.clear_button = QPushButton("クリア", self)
        self.clear_button.setFixedWidth(50)
        self.clear_button.clicked.connect(self.clear_collection)
        toolbar_layout.addWidget(self.clear_button)

        self.text_box = QLineEdit()
        self.text_box.setMinimumWidth(100)
        self.text_box.setPlaceholderText("メモ...")        
        toolbar_layout.addWidget(self.text_box)

        self.save_button = QPushButton("💾 保存", self)
        self.save_button.clicked.connect(self.save_collection)
        toolbar_layout.addWidget(self.save_button)

        self.load_button = QPushButton("📂 読込", self)
        self.load_button.clicked.connect(self.show_load_dialog)
        toolbar_layout.addWidget(self.load_button)

        toolbar_layout.addStretch(1)
        self.main_layout.addLayout(toolbar_layout)
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.scroll_content = QWidget()
        self.flow_layout = FlowLayout(self.scroll_content)
        self.scroll_content.setLayout(self.flow_layout)
        
        self.scroll_area.setWidget(self.scroll_content)
        self.main_layout.addWidget(self.scroll_area)
        self.setAcceptDrops(True)
    
    def add_image(self, image_path):
        if image_path in self.images or not os.path.exists(image_path):
            return
        self.images.append(image_path)
        thumbnail = ViewerDraggableLabel(image_path, self)
        pixmap = QPixmap(image_path)
        scaled_image = pixmap.scaled(thumbnail.thumbnail_size, thumbnail.thumbnail_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        thumbnail.setPixmap(scaled_image)
        thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumbnail.deleteRequested.connect(self.remove_image)
        
        self.thumbnails.append(thumbnail)
        self.thumbnail_map[image_path] = thumbnail
        self.flow_layout.addWidget(thumbnail)
        self.flow_layout.update()

    def remove_image(self, image_path):
        if image_path in self.images:
            self.images.remove(image_path)
            if image_path in self.thumbnail_map:
                thumbnail = self.thumbnail_map[image_path]
                self.thumbnails.remove(thumbnail)
                del self.thumbnail_map[image_path]
                thumbnail.setParent(None)
                self.flow_layout.update()

    def swapImages(self, source_path, target_path):
        if source_path in self.images and target_path in self.images:
            source_idx = self.images.index(source_path)
            target_idx = self.images.index(target_path)
            source_image = self.images.pop(source_idx)
            self.images.insert(target_idx, source_image)
            
            for thumbnail in self.thumbnails: thumbnail.setParent(None)
            for img_path in self.images:
                if img_path in self.thumbnail_map:
                    self.flow_layout.addWidget(self.thumbnail_map[img_path])
            self.flow_layout.update()

    def clear_collection(self):
        for thumbnail in self.thumbnails: thumbnail.setParent(None)
        self.thumbnails.clear()
        self.images.clear()
        self.flow_layout.update()
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith('.png'):
                    event.acceptProposedAction()
                    return
        event.ignore()
    
    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith('.png'):
                    self.add_image(url.toLocalFile())
            event.acceptProposedAction()

    def save_collection(self):
        if not self.images:
            QMessageBox.warning(self, "通知", "保存する画像がありません。")
            return
        memo = self.text_box.text().strip() or "Untitled"
        now = datetime.now()
        timestamp = now.strftime("%Y/%m/%d %H:%M")
        filename_ts = now.strftime("%Y%m%d_%H%M%S")
        
        data = {
            "memo": memo,
            "timestamp": timestamp,
            "images": self.images
        }
        filepath = os.path.join(COLLECTIONS_DIR, f"col_{filename_ts}.json")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "保存完了", f"「{memo}  {timestamp}」\nとして保存しました。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"保存に失敗しました: {e}")

    def show_load_dialog(self):
        dialog = CollectionLoadDialog(self)
        if dialog.exec():
            selected_images = dialog.get_selected_images()
            if selected_images:
                self.clear_collection()
                for img in selected_images:
                    self.add_image(img)
                if dialog.selected_memo:
                    self.text_box.setText(dialog.selected_memo)


class CollectionLoadDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("コレクションの読み込み")
        self.resize(450, 350)
        self.selected_images = []
        self.selected_memo = ""
        
        layout = QVBoxLayout(self)
        sort_layout = QHBoxLayout()
        sort_layout.addWidget(QLabel("ソート:"))
        self.combo_sort = QComboBox()
        self.combo_sort.addItems(["日時順", "名前順"])
        self.combo_sort.currentIndexChanged.connect(self.load_list)
        sort_layout.addWidget(self.combo_sort)
        sort_layout.addStretch()
        layout.addLayout(sort_layout)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self.accept_selection)
        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        btn_load = QPushButton("選択して開く")
        btn_load.clicked.connect(self.accept_selection)
        btn_cancel = QPushButton("キャンセル")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_load)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        self.load_list()

    def load_list(self):
        self.list_widget.clear()
        files = [os.path.join(COLLECTIONS_DIR, f) for f in os.listdir(COLLECTIONS_DIR) if f.endswith(".json")]
        
        items_data = []
        for fpath in files:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    items_data.append({
                        "path": fpath,
                        "memo": data.get("memo", "Untitled"),
                        "timestamp": data.get("timestamp", ""),
                        "images": data.get("images", [])
                    })
            except Exception:
                continue

        if self.combo_sort.currentIndex() == 0:
            items_data.sort(key=lambda x: x["timestamp"], reverse=True)
        else:
            items_data.sort(key=lambda x: x["memo"].lower())

        for item_d in items_data:
            list_item = QListWidgetItem(self.list_widget)
            list_item.setData(Qt.ItemDataRole.UserRole, item_d)
            
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(5, 2, 5, 2)
            
            lbl_text = QLabel(f"{item_d['memo']}   {item_d['timestamp']}")
            btn_del = QPushButton("削除")
            btn_del.setFixedSize(45, 24)
            btn_del.setStyleSheet("background-color: #d32f2f; color: white;")
            btn_del.clicked.connect(partial(self.delete_item, fpath, list_item))
            
            row_layout.addWidget(lbl_text)
            row_layout.addStretch()
            row_layout.addWidget(btn_del)
            
            list_item.setSizeHint(row_widget.sizeHint())
            self.list_widget.setItemWidget(list_item, row_widget)

    def delete_item(self, fpath, list_item):
        if QMessageBox.question(self, "確認", "このコレクションメモを削除しますか？") == QMessageBox.StandardButton.Yes:
            try:
                if os.path.exists(fpath): os.remove(fpath)
                row = self.list_widget.row(list_item)
                self.list_widget.takeItem(row)
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"削除できませんでした: {e}")

    def accept_selection(self):
        item = self.list_widget.currentItem()
        if item:
            data = item.data(Qt.ItemDataRole.UserRole)
            self.selected_images = data["images"]
            self.selected_memo = data["memo"]
            self.accept()

    def get_selected_images(self):
        return self.selected_images


class CollectionWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.collection_widget = CollectionWidget(self)
        self.setCentralWidget(self.collection_widget)
        self.setWindowTitle("画像コレクション")
        self.resize(700, 220)
        self.collection_widget.image_selected.connect(self.on_image_selected)

    def on_image_selected(self, image_path):
        print(f"選択された画像: {image_path}")
        
    def add_image(self, image_path):
        self.collection_widget.add_image(image_path)

    def resizeEvent(self, event):
        if hasattr(self, 'collection_widget') and hasattr(self.collection_widget, 'flow_layout'):
            self.collection_widget.flow_layout.update()
        super().resizeEvent(event)

    def closeEvent(self, event):
        if self.parent() and hasattr(self.parent(), 'remove_collection'):
            self.parent().remove_collection(self)
        super().closeEvent(event)


class OriginalViewWindow(QMainWindow):
    originalWindowClosed = Signal(object)

    def __init__(self, image_file, parent=None):
        super().__init__(parent)
        self.original_view = QWidget(self)
        self.setCentralWidget(self.original_view)
        self.layout = QVBoxLayout(self.original_view)
        self.setWindowTitle(f"オリジナルサイズ - {image_file}")
        
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMouseTracking(True)
        self.image_label.mouseDoubleClickEvent = lambda e: self.close()

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(self.image_label)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.layout.addWidget(self.scroll_area)

        self.dragging = False
        self.drag_position = None
        
        pixmap = QPixmap(image_file)
        self.image_label.setPixmap(pixmap)
        self.resize_window_to_image(pixmap)

    def resize_window_to_image(self, pixmap):
        screen_size = QGuiApplication.primaryScreen().availableGeometry().size()
        width = min(pixmap.width(), int(screen_size.width() * 0.85))
        height = min(pixmap.height(), int(screen_size.height() * 0.85))
        self.resize(width + 40, height + 30)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self.dragging:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self.originalWindowClosed.emit(self)
        super().closeEvent(event)


class ImageView(QWidget):
    image_loaded = Signal()
    area_resized = Signal(int)
    metaarea_changed = Signal()

    def __init__(self, set_id, parent=None):
        super().__init__(parent)        
        self.metadata = {}
        self.current_image_path = ""
        self.current_folder = ""
        self.current_index = 0
        self.set_id = set_id
        self.meta_tags = [
            "Prompt", "Negative prompt", "Steps", "Sampler", "CFG scale", 
            "Seed", "Size", "Model", "VAE", "Denoising strength", 
            "Variation seed", "Variation seed strength", "Clip skip"
        ]

        self.container = QWidget()
        layout = QVBoxLayout(self.container)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(self.splitter)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        
        self.image_label = DraggableImageLabel("", self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setText("ファイルをドラッグ&ドロップするか\n[Open] ボタンでフォルダを指定してください")
        self.image_label.setMouseTracking(True)
        self.image_label.mouseDoubleClickEvent = self.on_image_double_click

        scroll_area.setWidget(self.image_label)
        self.splitter.addWidget(scroll_area)
        scroll_area.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        scroll_area.customContextMenuRequested.connect(self.show_slider_popup)

        metadata_scroll = QScrollArea()
        metadata_scroll.setWidgetResizable(True)
        self.metadata_widget = QWidget()
        self.metadata_layout = QVBoxLayout(self.metadata_widget)
        metadata_scroll.setWidget(self.metadata_widget)
        metadata_scroll.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        metadata_scroll.customContextMenuRequested.connect(self.show_tagSelection_ContextMenu)
        self.splitter.addWidget(metadata_scroll)
        
        self.splitter.setSizes([500, 400])
        self.splitter.splitterMoved.connect(lambda: self.area_resized.emit(self.set_id))

        self.slider_popup = SliderPopup(self)
        self.slider_popup.slider.valueChanged.connect(self.on_slider_value_changed)
        # スライダのフィルタチェックが変わったら表示を更新
        self.slider_popup.filter_changed.connect(self.on_slider_filter_changed)

        self.toolbar = self.setup_toolbar()
        layout.insertLayout(0, self.toolbar)
        
        self.image_label.installEventFilter(self)
        self.container.setAcceptDrops(True)
        self.container.installEventFilter(self)
        self.open_button.new_folder.connect(self.on_new_folder)
        self.original_views = [] 

    def setup_toolbar(self):
        toolbar = QHBoxLayout()
        
        self.open_button = OpenNavigationButton()
        self.open_button.setText("Open")
        self.open_button.setFixedWidth(50)
        toolbar.addWidget(self.open_button)
        
        copy_seed_button = QPushButton("Copy")
        copy_seed_button.clicked.connect(self.copy_seed)
        copy_seed_button.setFixedWidth(45)
        toolbar.addWidget(copy_seed_button)

        self.combo_sort = QComboBox()
        self.combo_sort.addItems(["日付順", "名前順"])
        self.combo_sort.currentIndexChanged.connect(self.refresh_folder_view)
        toolbar.addWidget(self.combo_sort)

        self.chk_desc = QCheckBox("降順")
        self.chk_desc.stateChanged.connect(self.refresh_folder_view)
        toolbar.addWidget(self.chk_desc)

        # 検索ボックス（Enter押下時に text_entered を実行）
        self.text_box = QLineEdit()
        self.text_box.setMinimumWidth(120)
        self.text_box.setPlaceholderText("Filter ( - : neg prompt)")
        self.text_box.setClearButtonEnabled(True)
        self.text_box.editingFinished.connect(self.text_entered)
        toolbar.addWidget(self.text_box)

        toolbar.addStretch()

        self.lbl_page = QLabel("0/0")
        self.lbl_page.setFont(QFont('SansSerif', 10, QFont.Weight.Bold))
        self.lbl_page.setMinimumWidth(65)
        self.lbl_page.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        toolbar.addWidget(self.lbl_page)
 
        self.open_collection_button = QPushButton("CL")
        self.open_collection_button.setFixedWidth(35)
        toolbar.addWidget(self.open_collection_button)
        return toolbar        

    def get_sorted_image_files(self, apply_filter=False):
        if not self.current_folder or not os.path.exists(self.current_folder):
            return []
        
        files = [f for f in os.listdir(self.current_folder) if f.lower().endswith('.png')]
        
        if apply_filter and self.text_box.text().strip():
            query = self.text_box.text().strip()
            is_neg = query.startswith("-")
            pattern_str = query[1:].strip() if is_neg else query
            
            if pattern_str:
                try:
                    regex = re.compile(pattern_str, re.IGNORECASE)
                    filtered = []
                    for f in files:
                        meta = self.extract_png_metadata(os.path.join(self.current_folder, f))
                        target_text = meta.get("Negative prompt", "") if is_neg else meta.get("Prompt", "")
                        if regex.search(target_text):
                            filtered.append(f)
                    files = filtered
                except re.error:
                    pass

        is_desc = self.chk_desc.isChecked()
        if self.combo_sort.currentIndex() == 0:
            files.sort(key=lambda f: os.path.getmtime(os.path.join(self.current_folder, f)), reverse=is_desc)
        else:
            files.sort(key=lambda f: f.lower(), reverse=is_desc)
            
        return files

    def refresh_folder_view(self):
        if self.current_folder:
            # メイン画面の総数はスライダのチェック状態に連動させる
            #files = self.get_sorted_image_files(apply_filter=self.slider_popup.chk_filter.isChecked())
            files = self.get_sorted_image_files(True)
            if files:
                current_name = os.path.basename(self.current_image_path)
                if current_name in files:
                    self.current_index = files.index(current_name)
                else:
                    self.current_index = 0
                    self.load_image(os.path.join(self.current_folder, files[0]))
            self.update_page_display(len(files))

    def update_page_display(self, total_files=None):
        if total_files is None:
            files = self.get_sorted_image_files(apply_filter=self.slider_popup.chk_filter.isChecked())
            total_files = len(files)
        
        idx_display = self.current_index + 1 if total_files > 0 else 0
        self.lbl_page.setText(f"{idx_display}/{total_files}")
        self.slider_popup.update_page_display(idx_display, total_files)

    def on_slider_filter_changed(self):
        """スライダの「フィルタ適用」にチェックが入った・外れたときの処理"""
        self.refresh_folder_view()
        if self.slider_popup.isVisible():
            self.show_slider_popup(None)

    def show_tagSelection_ContextMenu(self, position):
        menu = QMenu()
        selectAction = QAction("項目を選択...", self)
        selectAction.triggered.connect(self.selectItems)
        menu.addAction(selectAction)
        menu.exec(self.metadata_widget.mapToGlobal(position))

    def on_slider_value_changed(self, index):
        if 0 <= index < len(self.slider_popup.image_files):
            self.current_index = index
            image_path = os.path.join(self.current_folder, self.slider_popup.image_files[index])
            self.load_image(image_path)

    def show_slider_popup(self, position):
        if not self.current_folder: return
        
        image_files = self.get_sorted_image_files(apply_filter=self.slider_popup.chk_filter.isChecked())
        if not image_files: return

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
            cursor_pos = QCursor.pos()
            popup_pos = cursor_pos + QPoint(-self.slider_popup.width() // 2, 10)
            screen_rect = QGuiApplication.primaryScreen().geometry()
            popup_pos.setX(max(screen_rect.left(), min(popup_pos.x(), screen_rect.right() - self.slider_popup.width())))
            self.slider_popup.move(popup_pos)
            self.slider_popup.show()

    def selectItems(self):
        dialog = CheckableListDialog(self.metadata.keys(), self)
        for checkbox in dialog.checkboxes:
            if checkbox.text() in self.meta_tags:
                checkbox.setChecked(True)
        if dialog.exec():
            self.meta_tags = dialog.getSelectedItems()
            self.display_metadata(self.metadata)    
            self.image_loaded.emit()

    def on_new_folder(self):
        self.current_folder = self.open_button.current_folder
        self.current_index = 0
        self.load_first_image()
        self.image_loaded.emit()

    def load_first_image(self):
        image_files = self.get_sorted_image_files(apply_filter=self.slider_popup.chk_filter.isChecked())
        if image_files:
            self.load_image(os.path.join(self.current_folder, image_files[0]))
        else:
            self.clear_view_area("No matching png files found")

    def load_image(self, image_path):
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            self.image_label.setPixmap(pixmap.scaled(self.image_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            self.current_image_path = image_path
            self.image_label.image_path = image_path
            
            files = self.get_sorted_image_files(apply_filter=self.slider_popup.chk_filter.isChecked())
            current_name = os.path.basename(image_path)
            if current_name in files:
                self.current_index = files.index(current_name)
            self.update_page_display(len(files))

            metadata = self.extract_png_metadata(image_path)
            self.display_metadata(metadata)
            self.metadata = metadata
        self.image_loaded.emit()

    def clear_view_area(self, text):
        self.image_label.setText(text)
        self.image_label.setPixmap(QPixmap())
        self.current_image_path = ""
        self.image_label.image_path = ""
        while self.metadata_layout.count():
            child = self.metadata_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()
        self.lbl_page.setText("0/0")

    def change_image(self, event):
        if not self.current_folder: return
        x = 0
        # スライダのフィルタがONの場合はすでに絞り込まれているリストを回す
        #if self.slider_popup.chk_filter.isChecked():
        if x:
            files = self.get_sorted_image_files(apply_filter=True)
            if not files: return
            current_name = os.path.basename(self.current_image_path)
            current_idx = files.index(current_name) if current_name in files else 0
            direction = -1 if event.angleDelta().y() > 0 else 1
            new_idx = (current_idx + direction) % len(files)
            self.load_image(os.path.join(self.current_folder, files[new_idx]))
        else:
            # スライダフィルタOFFでテキスト欄に入力がある場合は、従来の検索ジャンプ
            files = self.get_sorted_image_files(apply_filter=False)
            if not files: return
            current_name = os.path.basename(self.current_image_path)
            current_idx = files.index(current_name) if current_name in files else 0
            direction = -1 if event.angleDelta().y() > 0 else 1
            new_idx = (current_idx + direction) % len(files)

            if self.text_box.text().strip():
                query = self.text_box.text().strip()
                is_neg = query.startswith("-")
                pattern_str = query[1:].strip() if is_neg else query
                if pattern_str:
                    try:
                        regex = re.compile(pattern_str, re.IGNORECASE)
                        for _ in range(len(files)):
                            meta = self.extract_png_metadata(os.path.join(self.current_folder, files[new_idx]))
                            target_text = meta.get("Negative prompt", "") if is_neg else meta.get("Prompt", "")
                            if regex.search(target_text):
                                self.load_image(os.path.join(self.current_folder, files[new_idx]))
                                self.refresh_folder_view()
                                return
                            new_idx = (new_idx + direction) % len(files)
                        return # 見つからなければ移動しない
                    except re.error:
                        pass
            self.load_image(os.path.join(self.current_folder, files[new_idx]))

    def text_entered(self):
        """Enterキー確定時：従来の動作通り対象を検索して最初にヒットした画像へ遷移"""
        if not self.current_folder: return
        files = self.get_sorted_image_files(apply_filter=False)
        if not files: return
        
        current_name = os.path.basename(self.current_image_path)
        current_idx = files.index(current_name) if current_name in files else 0
        query = self.text_box.text().strip()
        
        if not query:
            self.refresh_folder_view()
            return

        is_neg = query.startswith("-")
        pattern_str = query[1:].strip() if is_neg else query
        if pattern_str:
            try:
                regex = re.compile(pattern_str, re.IGNORECASE)
                for _ in range(len(files)):
                    meta = self.extract_png_metadata(os.path.join(self.current_folder, files[current_idx]))
                    target_text = meta.get("Negative prompt", "") if is_neg else meta.get("Prompt", "")
                    if regex.search(target_text):
                        self.load_image(os.path.join(self.current_folder, files[current_idx]))
                        self.refresh_folder_view()
                        return
                    current_idx = (current_idx + 1) % len(files)
                self.clear_view_area("No matching images found")
            except re.error:
                pass

    def parse_metadata(self, text):
        metadata = {}
        neg_prompt_index = text.find("Negative prompt:")
        if neg_prompt_index == -1: neg_prompt_index = text.find("Steps:")

        if neg_prompt_index != -1:
            metadata["Prompt"] = text[:neg_prompt_index].strip()
            remaining_text = text[neg_prompt_index:]
            steps_index = remaining_text.find("Steps:")
            prompt = remaining_text[:steps_index].replace("Negative prompt:", "").strip()
            metadata["Negative prompt"] = prompt

            for param in remaining_text[steps_index:].split(","):
                if ":" in param:
                    key, value = param.split(":", 1)
                    metadata[key.strip()] = value.strip()
        return metadata

    def extract_comfy_metadata(self, value):
        try:
            metadata = json.loads(value)
            prompt, others = {}, {}
            prompt_tags = ["Prompt", "Negative prompt"]
            text_id = 0
            for values in metadata.values():
                inputs = values.get("inputs", {})
                if values.get("class_type") == "CLIPTextEncode":
                    if "text" in inputs and text_id < len(prompt_tags):
                        prompt[prompt_tags[text_id]] = str(inputs["text"])
                        text_id += 1
                else:
                    for k, v in inputs.items(): others[k] = str(v)
            return prompt | others
        except Exception:
            return {}

    def extract_png_metadata(self, image_path):
        try:
            with Image.open(image_path) as img:
                if isinstance(img, PngImageFile):
                    for key, value in img.info.items():
                        if key.lower() == 'parameters': return self.parse_metadata(value)
                        elif key.lower() == 'prompt': return self.extract_comfy_metadata(value)
            return {}
        except Exception as e:
            return {}
            
    def display_metadata(self, metadata, clear=True):
        if clear:
            while self.metadata_layout.count():
                child = self.metadata_layout.takeAt(0)
                if child.widget(): child.widget().deleteLater()

        for key in self.meta_tags:
            if key in metadata:
                label = MetadataLabel(key, metadata[key])
                self.metadata_layout.addWidget(label)
                label.r_button_clicked.connect(self.selectItems)

        filename = self.current_image_path.replace("\\", "/")
        self.metadata_layout.insertWidget(0, MetadataLabel("File", filename))
        self.metadata_layout.addStretch()

    def copy_seed(self):
        for i in range(self.metadata_layout.count()):
            item = self.metadata_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), MetadataLabel):
                if item.widget().label.lower() == "seed":
                    QGuiApplication.clipboard().setText(item.widget().value)
                    break

    def eventFilter(self, watched, event):
        # 【修正3】 QEvent.Type.Wheel / Qt.EventType.Wheel （どちらも安全に動作）
        if event.type() == QEvent.Type.Wheel and watched == self.image_label:
            self.change_image(event)
            return True
        elif event.type() == QEvent.Type.DragEnter and event.mimeData().hasUrls():
            event.acceptProposedAction()
            return True
        elif event.type() == QEvent.Type.Drop and watched == self.container:
            self.dropped_image(event)
            return True
        elif event.type() == QEvent.Type.MouseButtonPress:
            if self.slider_popup.isVisible() and not self.slider_popup.geometry().contains(event.globalPosition().toPoint()):
                self.slider_popup.hide()
                return True
        return super().eventFilter(watched, event)
    
    def dropped_image(self, event):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        if files and os.path.isfile(files[0]) and files[0].lower().endswith('.png'):
            self.current_folder = os.path.dirname(files[0])
            self.open_button.current_folder = self.current_folder
            self.load_image(files[0])

    def on_image_double_click(self, event):
        if self.current_image_path and os.path.exists(self.current_image_path):
            original_view = OriginalViewWindow(self.current_image_path)
            original_view.originalWindowClosed.connect(lambda w: self.original_views.remove(w) if w in self.original_views else None)    
            original_view.show()
            self.original_views.append(original_view)


class ImageViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Metadata Viewer (PySide6 Power-Up Edition)")
        self.setMinimumSize(850, 650)
        self.resize(850, 900)
        
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        
        self.tab_widget = QTabWidget()
        self.layout.addWidget(self.tab_widget)

        self.s_view = QWidget()
        layout_s = QVBoxLayout(self.s_view)
        self.m_view = ImageView(0)
        send_button = QPushButton("Send →")
        self.m_view.toolbar.addWidget(send_button)      
        send_button.clicked.connect(partial(self.send_to, 0, 1))
        send_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        send_button.customContextMenuRequested.connect(self.show_send_context_menu)
        layout_s.addWidget(self.m_view.container)
        self.tab_widget.addTab(self.s_view, "シングル")

        self.c_view = QWidget()
        layout_c = QHBoxLayout(self.c_view)
        self.l_view = ImageView(1)
        self.r_view = ImageView(2)

        send_button1 = QPushButton("←")
        send_button1.setFixedWidth(30)
        self.l_view.toolbar.addWidget(send_button1)      
        send_button1.clicked.connect(partial(self.send_to, 1, 0))
        send_button1.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        send_button1.customContextMenuRequested.connect(self.show_send_context_menu)
        layout_c.addWidget(self.l_view.container)
        
        send_button2 = QPushButton("←←")
        send_button2.setFixedWidth(30)
        self.r_view.toolbar.addWidget(send_button2)      
        send_button2.clicked.connect(partial(self.send_to, 2, 0))
        send_button2.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        send_button2.customContextMenuRequested.connect(self.show_send_context_menu)
        layout_c.addWidget(self.r_view.container)

        self.collection_windows = []
        self.collection_idx = 0

        self.l_view.image_loaded.connect(self.compare_metadata)
        self.r_view.image_loaded.connect(self.compare_metadata)
        self.l_view.metaarea_changed.connect(self.compare_metadata)
        self.r_view.metaarea_changed.connect(self.compare_metadata)

        self.tab_widget.addTab(self.c_view, "比較")
        self.tab_widget.currentChanged.connect(self.on_tab_changed)

        self.views = [self.m_view, self.l_view, self.r_view]
        self.cp_tags = [
            "Prompt", "Negative prompt", "Steps", "Sampler", "CFG scale", 
            "Seed", "Size", "Model", "VAE", "Denoising strength", 
            "Variation seed", "Variation seed strength", "Clip skip"
        ]

        for view in self.views:
            view.area_resized.connect(self.update_images)
            view.open_collection_button.clicked.connect(self.create_collection)

    def show_send_context_menu(self, pos):
        sender = self.sender()
        menu = QMenu()
        send_move = menu.addAction("送って移動")
        if sender.text() == "Send →":
            send_move.setEnabled(self.m_view.current_folder != "")
            send_move.triggered.connect(partial(self.send_and_move, 0, 1))
        elif sender.text() == "←":
            send_move.setEnabled(self.l_view.current_folder != "")
            send_move.triggered.connect(partial(self.send_and_move, 1, 0))
        elif sender.text() == "←←":
            send_move.setEnabled(self.r_view.current_folder != "")
            send_move.triggered.connect(partial(self.send_and_move, 2, 0))
        menu.exec(sender.mapToGlobal(pos))

    def send_and_move(self, source, target):
        self.send_to(source, target)
        self.tab_widget.setCurrentIndex(target)

    def compare_metadata(self):
        if self.l_view.current_image_path and self.r_view.current_image_path:
            left_metadata, right_metadata = self.l_view.metadata, self.r_view.metadata
            if not left_metadata or not right_metadata:
                self.l_view.display_metadata(self.l_view.metadata)
                self.r_view.display_metadata(self.r_view.metadata)
                return
        elif self.l_view.current_image_path:
            self.l_view.display_metadata(self.l_view.metadata)
            return
        elif self.r_view.current_image_path:
            self.r_view.display_metadata(self.r_view.metadata)
            return
        else:
            return

        left_layout, right_layout = self.l_view.metadata_layout, self.r_view.metadata_layout
        while left_layout.count():
            if child := left_layout.takeAt(0):
                if child.widget(): child.widget().deleteLater()
        while right_layout.count():
            if child := right_layout.takeAt(0):
                if child.widget(): child.widget().deleteLater()

        l_enable_tags, r_enable_tags = self.l_view.meta_tags, self.r_view.meta_tags
        all_tag = list(left_metadata.keys())
        for item in right_metadata.keys():
            if item not in all_tag: all_tag.append(item)        
        self.cp_tags = all_tag.copy()

        for key in self.cp_tags[0:2]:
            left_value = left_metadata.get(key, "")
            right_value = right_metadata.get(key, "")
            left_set = set([s.strip() for s in left_value.split(",") if s.strip()])
            right_set = set([s.strip() for s in right_value.split(",") if s.strip()])
            only_in_left, only_in_right = left_set - right_set, right_set - left_set

            if key in l_enable_tags:
                left_label = MetadataLabel(key, left_value)
                left_label.r_button_clicked.connect(self.l_view.selectItems)
                left_layout.addWidget(left_label)
                left_label.apply_highlight(only_in_left, "#ffff80")
            
            if key in r_enable_tags:
                right_label = MetadataLabel(key, right_value)
                right_label.r_button_clicked.connect(self.r_view.selectItems)
                right_layout.addWidget(right_label)
                right_label.apply_highlight(only_in_right, "#80ffff")

        for key in self.cp_tags[2:]:
            left_value, right_value = left_metadata.get(key, ""), right_metadata.get(key, "")
            if key in l_enable_tags and left_value:
                left_label = MetadataLabel(key, left_value)
                left_label.r_button_clicked.connect(self.l_view.selectItems)
                left_layout.addWidget(left_label)
            if key in r_enable_tags and right_value:
                right_label = MetadataLabel(key, right_value)
                right_label.r_button_clicked.connect(self.r_view.selectItems)
                right_layout.addWidget(right_label)
            
            if left_value != right_value:
                if key in l_enable_tags and left_value: left_label.update_text(highlight=True)
                if key in r_enable_tags and right_value: right_label.update_text(highlight=True)
        
        left_layout.addStretch()
        right_layout.addStretch()
        left_layout.insertWidget(0, MetadataLabel("File", self.l_view.current_image_path.replace("\\", "/")))
        right_layout.insertWidget(0, MetadataLabel("File", self.r_view.current_image_path.replace("\\", "/")))
            
    def send_to(self, source, target):
        self.views[target].current_folder = self.views[source].current_folder
        self.views[target].current_image_path = self.views[source].current_image_path
        self.views[target].image_label.image_path = self.views[source].current_image_path
        self.views[target].load_image(self.views[target].current_image_path)
        self.views[target].open_button.current_folder = self.views[source].current_folder
        self.resize_image(target)

    def resize_image(self, view_id):
        view = self.views[view_id]
        if os.path.isfile(view.current_image_path):
            sizes = view.splitter.sizes()
            img = QPixmap(view.current_image_path)
            view.image_label.setPixmap(img.scaled(view.image_label.width(), sizes[0], Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        elif view.current_folder and view.current_image_path:
            view.clear_view_area("png file deleted")

    def on_tab_changed(self, index):
        if index == 0: self.resize_image(self.m_view.set_id)
        elif index == 1:
            self.resize_image(self.l_view.set_id)
            self.resize_image(self.r_view.set_id)
            self.compare_metadata()

    def update_images(self, set_id):
        if set_id == 1:
            self.resize_image(1)
            sizes = self.l_view.splitter.sizes()
            if os.path.isfile(self.r_view.current_image_path):
                img2 = QPixmap(self.r_view.current_image_path)
                self.r_view.image_label.setPixmap(img2.scaled(self.l_view.image_label.width(), sizes[0], Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            elif self.r_view.current_folder and self.r_view.current_image_path:
                self.r_view.clear_view_area("png file deleted")
            self.r_view.splitter.setSizes(sizes)
        elif set_id == 2: self.resize_image(2)
        elif set_id == 0: self.resize_image(0)

    def create_collection(self):
        collection = CollectionWindow(self)
        collection.setGeometry(self.x() + int(self.width() / 2), 200, 700, 220)
        collection.setWindowTitle("Collection " + str(self.collection_idx))
        collection.show()
        self.collection_idx += 1
        self.collection_windows.append(collection)
        
    def remove_collection(self, collection):
        if collection in self.collection_windows:
            self.collection_windows.remove(collection)
    
    def resizeEvent(self, event):
        if self.tab_widget.currentIndex() == 0: self.resize_image(self.m_view.set_id)
        else:
            self.resize_image(self.l_view.set_id)
            self.resize_image(self.r_view.set_id)
        super().resizeEvent(event)


if __name__ == '__main__':
    app = QApplication([])
    app.setStyle("Fusion")
    viewer = ImageViewer()
    viewer.show()
    app.exec()