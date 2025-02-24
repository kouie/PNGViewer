from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QLabel, QSplitter, QPushButton, QTextEdit,
                           QFileDialog, QTabWidget, QScrollArea, QFrame, QLineEdit)
from PyQt5.QtCore import Qt, QSize, QRect, QEvent, pyqtSignal 
from PyQt5.QtGui import QPixmap, QDragEnterEvent, QDropEvent, QColor
from PyQt5.QtGui import QFont, QTextCharFormat, QTextCursor, QFontMetrics
import os
import re
from PIL import Image
from PIL.PngImagePlugin import PngImageFile
from functools import partial

class MetadataLabel(QLabel):
    def __init__(self, label="", value="", parent=None):
        super().__init__(parent)
        self.label = label
        self.value = value
        self.setFont(QFont('SansSerif', 12))
        self.setTextFormat(Qt.RichText)
        self.setWordWrap(True) 
        self.update_text()
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    def update_text(self, highlight=False):
        if highlight:
            self.setText(f"<b>{self.label}:</b> <span style='background-color: #FFEB3B'>{self.value}</span>")
        else:
            self.setText(f"<b>{self.label}:</b> {self.value}")

    def apply_highlight(self, words_to_highlight, color):
        all_text = self.value 
        for word in words_to_highlight:
            htext = '<span style="background-color: '+color+';">'+word+'</span>'
            all_text = all_text.replace(word, htext)

        self.setText(f"<b>{self.label}:</b> {all_text}")

class ImageView(QWidget):
    image_loaded = pyqtSignal()
    area_resized = pyqtSignal(int)

    def __init__(self, set_id, parent=None):
        super().__init__(parent)        

        self.container = QWidget()
        layout = QVBoxLayout(self.container)
        self.splitter = QSplitter(Qt.Vertical)
        layout.addWidget(self.splitter)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setText("ファイルをドラッグ&ドロップするか\n左上のボタンをクリックしてフォルダを指定してください")
        scroll_area.setWidget(self.image_label)
        self.splitter.addWidget(scroll_area)

        # メタデータ表示用のスクロールエリア
        metadata_scroll = QScrollArea()
        metadata_scroll.setWidgetResizable(True)
        self.metadata_widget = QWidget()
        self.metadata_layout = QVBoxLayout(self.metadata_widget)
        metadata_scroll.setWidget(self.metadata_widget)
        self.splitter.addWidget(metadata_scroll)
        
        # スプリッターの初期サイズ設定
        self.splitter.setSizes([400, 500])
        self.splitter.splitterMoved.connect(self.on_area_resized)

        self.toolbar = self.setup_toolbar()
        layout.insertLayout(0,self.toolbar)

        self.image_label.installEventFilter(self)
        self.container.setAcceptDrops(True)
        self.container.installEventFilter(self)
        
        self.metadata = {}
        self.current_image_path = ""
        self.current_folder = ""
        self.set_id = set_id

    def setup_toolbar(self):
        toolbar = QHBoxLayout()
        
        open_button = QPushButton("Open Folder")
        open_button.clicked.connect(self.open_folder)
        toolbar.addWidget(open_button)
        
        copy_seed_button = QPushButton("Copy Seed")
        copy_seed_button.clicked.connect(self.copy_seed)
        toolbar.addWidget(copy_seed_button)

        # テキスト入力ボックスを追加
        f_label = QLabel(" Filter:")
        self.text_box = QLineEdit()
        self.text_box.setPlaceholderText(" prompt...")
        toolbar.addWidget(f_label)
        toolbar.addWidget(self.text_box)

        toolbar.addStretch()
 
        return toolbar        

    def on_area_resized(self):
        self.area_resized.emit(self.set_id)

    def open_folder(self):
        if self.current_image_path == "":
            folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        else:
            folder = QFileDialog.getExistingDirectory(self, "Select Folder", self.current_folder)

        if folder:
            self.current_folder = folder
            self.load_first_image()

    def load_first_image(self):
        current_folder = self.current_folder
        image_files = [f for f in os.listdir(current_folder) 
                      if f.lower().endswith(('.png'))]
        if image_files:
            self.image_label.setText(image_files[0])
            image_file = os.path.join(current_folder, image_files[0])
            self.load_image(image_file)
        else:
            self.image_label.setText("no png files found")
            self.current_image_path = ""
            while self.metadata_layout.count():
                child = self.metadata_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

    def load_image(self, image_path):
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            scaled_pixmap = self.scale_pixmap(pixmap, self.image_label.size())
            self.image_label.setPixmap(scaled_pixmap)
            self.current_image_path = image_path
                
            # メタデータを読み込んで表示
            metadata = self.extract_png_metadata(image_path)
            self.display_metadata(metadata)
            self.metadata_layout.insertWidget(0, MetadataLabel("File",f"{image_path}"))
            self.metadata = metadata

            self.image_loaded.emit()
 
    def scale_pixmap(self, pixmap, size):
        return pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def change_image(self, event):
        if self.current_folder:
            image_files = sorted([f for f in os.listdir(self.current_folder) 
                            if f.lower().endswith(('.png'))])
            try:
                current_index = image_files.index(os.path.basename(self.current_image_path))
            except:
                return
            
            new_index = ""
            for idx in range(len(image_files)):
                
                if event.angleDelta().y() > 0:
                    next_index = (current_index - 1) % len(image_files)
                else:
                    next_index = (current_index + 1) % len(image_files)

                next_file = os.path.join(self.current_folder, image_files[next_index])
                metadata = self.extract_png_metadata(next_file)

                if metadata:
                    filter = self.text_box.text()
                    prompts = metadata["Prompt"]
                    if filter in prompts:
                        new_index = next_index
                        break

                if event.angleDelta().y() > 0:
                    current_index = (current_index - 1) % len(image_files)
                else:
                    current_index = (current_index + 1) % len(image_files)

            if new_index == "":
                self.image_label.setText("no png files found ")
                while self.metadata_layout.count():
                    child = self.metadata_layout.takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()
                return
            
            self.load_image(os.path.join(self.current_folder, image_files[new_index]))

    def parse_metadata(self, text):
        metadata = {}

        # Negative promptの位置を見つける
        neg_prompt_index = text.find("Negative prompt:")
        if neg_prompt_index == -1:
            neg_prompt_index = text.find("Steps:")

        if neg_prompt_index != -1:
            # プロンプトを抽出
            prompt = text[:neg_prompt_index].strip()
            metadata["Prompt"] = prompt
            
            # Negative prompt以降を処理
            remaining_text = text[neg_prompt_index:]

            # Stepsの位置を見つける
            steps_index = remaining_text.find("Steps:")
            prompt = remaining_text[:steps_index]
            prompt = prompt.replace("Negative prompt:", "")

            metadata["Negative prompt"] = prompt.strip()

            # Steps以降を処理
            remaining_text = remaining_text[steps_index:]

            # パラメータを抽出
            params = remaining_text.split(",")
            for param in params:
                key, value = param.split(":",1)
                key = key.strip()
                value = value.strip()
                metadata[key] = value

        return metadata
        
    def extract_png_metadata(self, image_path):
        try:
            with Image.open(image_path) as img:
                if isinstance(img, PngImageFile):
                    # メタデータを検索
                    for key, value in img.info.items():
                        if key.lower() in ['parameters']:
                            return self.parse_metadata(value)
            return {}
        except Exception as e:
            print(f"Error extracting metadata: {e}")
            return {}
            
    def display_metadata(self, metadata, clear=True):
        if clear:
            # 既存のウィジェットをクリア
            while self.metadata_layout.count():
                child = self.metadata_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

        # メタデータを表示
        for key in ["Prompt", "Negative prompt", "Steps", "Sampler", "CFG scale", 
                   "Seed", "Size", "Model", "VAE", 
                   "Denoising strength", "Clip skip"]:
            if key in metadata:
                label = MetadataLabel(key, metadata[key])
                self.metadata_layout.addWidget(label)
        
        self.metadata_layout.addStretch()


    def update_image(self, image_path):
        self.image_data.full_path = image_path
        self.image_data.filename = os.path.basename(image_path)
        self.image_data.image = QPixmap(image_path)
        self.display_image()

    def display_image(self):
        self.label.setPixmap(self.image_data.image)

    def copy_seed(self):
        # 現在のタブに応じてSeedをクリップボードにコピー
        for i in range(self.metadata_layout.count()):
            item = self.metadata_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if isinstance(widget, MetadataLabel) and widget.label == "Seed":
                    QApplication.clipboard().setText(widget.value)
                    break

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Wheel:
            # ホイールイベント処理
            if watched == self.image_label:
                self.change_image(event)
                return True

        elif event.type() == QEvent.DragEnter:
            # ドラッグされたデータを受け入れるかどうかを判断
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
            return True
            
        elif event.type() == QEvent.DragMove:
            # 必要に応じてドラッグ中の位置をチェック
            event.acceptProposedAction()
            return True
        
        elif event.type() == QEvent.Drop:
            if watched == self.container:
                self.dropped_image_c(event)
                return True

            return True

        return super().eventFilter(watched, event)
    
    def dropped_image_c(self, event):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        if files:
            if os.path.isfile(files[0]) and files[0].lower().endswith('.png'):
                self.load_image(files[0])
                self.current_folder = os.path.dirname(files[0])


class ImageViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Metadata Viewer")
        self.setMinimumSize(800, 600)
        self.setGeometry(100,100, 800,900)
        
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        
        self.tab_widget = QTabWidget()
        self.layout.addWidget(self.tab_widget)

        self.s_view = QWidget()
        layout = QVBoxLayout(self.s_view)
        self.m_view = ImageView(0)
        send_button = QPushButton("Send Compare")
        self.m_view.toolbar.addWidget(send_button)      
        send_button.clicked.connect(self.send_to_cp_c)
        layout.addWidget(self.m_view.container)
        self.tab_widget.addTab(self.s_view, "Single View")

        self.c_view = QWidget()
        layout = QHBoxLayout(self.c_view)
        self.l_view = ImageView(1)
        self.r_view = ImageView(2)
        layout.addWidget(self.l_view.container)
        layout.addWidget(self.r_view.container)
        self.l_view.image_loaded.connect(self.compare_metadata_c)
        self.r_view.image_loaded.connect(self.compare_metadata_c)

        self.tab_widget.addTab(self.c_view, "Compare View")
        self.tab_widget.currentChanged.connect(self.update_images_c)

        self.views_c = [self.m_view, self.l_view, self.r_view]

        for view in self.views_c:
            view.area_resized.connect(self.update_images_c)

    def compare_metadata_c(self):
        if self.l_view.current_image_path and self.r_view.current_image_path:
            left_metadata = self.l_view.metadata
            right_metadata = self.r_view.metadata
        else:
            return

        # 両方のメタデータウィジェットをクリア
        left_layout = self.l_view.metadata_layout
        right_layout = self.r_view.metadata_layout
        
        while left_layout.count():
            child = left_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        while right_layout.count():
            child = right_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        for key in ["Prompt", "Negative prompt"]:
            left_value = left_metadata.get(key, "")
            right_value = right_metadata.get(key, "")

            # カンマ区切りでリスト化（余分なスペースを削除）
            list1 = [s.strip() for s in left_value.split(",") if s.strip()]
            list2 = [s.strip() for s in right_value.split(",") if s.strip()]

            # セット化して差分を取得
            left_set, right_set = set(list1), set(list2)
            only_in_left = left_set - right_set
            only_in_right = right_set - left_set

            # 左側のメタデータを表示
            left_label = MetadataLabel(key, left_value)
            left_layout.addWidget(left_label)

            left_label.apply_highlight(only_in_left, "yellow")
            
            # 右側のメタデータを表示
            right_label = MetadataLabel(key, right_value)
            right_layout.addWidget(right_label)

            right_label.apply_highlight(only_in_right, "cyan")


        # メタデータを比較しながら表示
        for key in ["Steps", "Sampler", "CFG scale", 
                   "Seed", "Size", "Model hash", "Model", "VAE hash", "VAE", 
                   "Denoising strength", "Clip skip", "Version"]:
            left_value = left_metadata.get(key, "")
            right_value = right_metadata.get(key, "")
            
            # 左側のメタデータを表示
            left_label = MetadataLabel(key, left_value)
            left_layout.addWidget(left_label)
            
            # 右側のメタデータを表示
            right_label = MetadataLabel(key, right_value)
            right_layout.addWidget(right_label)
            
            # 値が異なる場合はハイライト
            if left_value != right_value:
                left_label.update_text(highlight=True)
                right_label.update_text(highlight=True)
        
        left_layout.addStretch()
        right_layout.addStretch()

        left_layout.insertWidget(0, MetadataLabel("File",f"{self.l_view.current_image_path}"))
        right_layout.insertWidget(0, MetadataLabel("File",f"{self.r_view.current_image_path}"))        

    def scale_pixmap(self, pixmap, size):
        return pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            
    def send_to_cp_c(self):
        self.l_view.current_folder = self.m_view.current_folder
        self.l_view.current_image_path = self.m_view.current_image_path
        self.l_view.load_image(self.l_view.current_image_path)
        self.resize_image_c(1)


    def dropped_image_c(self, event, view):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        if files:
            if os.path.isfile(files[0]) and files[0].lower().endswith('.png'):
                view.load_image(files[0])
                view.current_folder = os.path.dirname(files[0])

    def resize_image_c(self, view_id):
        view = self.views_c[view_id]
        if view.current_image_path != "":
            sizes = view.splitter.sizes()  # 各ウィジェットのサイズを取得
            img = QPixmap(view.current_image_path)
            view.image_label.setPixmap(img.scaled(view.image_label.width(), sizes[0], Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def update_images_c(self, set_id):
        """スプリッターのサイズに応じて画像をリサイズ"""
        sender = self.sender()
        if set_id == 1:
            self.resize_image_c(1)

            sizes = self.l_view.splitter.sizes()  # 各ウィジェットのサイズを取得
            if self.r_view.current_image_path:
                img2 = QPixmap(self.r_view.current_image_path)
                self.r_view.image_label.setPixmap(img2.scaled(self.l_view.image_label.width(), sizes[0], Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.r_view.splitter.setSizes(sizes)

        elif set_id == 2:
            self.resize_image_c(2)

        elif set_id == 0:
            self.resize_image_c(0)

        else:
            for view in self.views_c:
                self.resize_image_c(view.set_id)

    def resizeEvent(self, event):
        """ウィンドウリサイズ時にも画像を更新"""
        self.update_images_c(3)
        super().resizeEvent(event)

if __name__ == '__main__':
    app = QApplication([])
    viewer = ImageViewer()
    viewer.show()
    app.exec_()
    