from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QLabel, QSplitter, QPushButton, QTextEdit,
                           QFileDialog, QTabWidget, QScrollArea, QFrame)
from PyQt5.QtCore import Qt, QSize, QRect, QEvent 
from PyQt5.QtGui import QPixmap, QDragEnterEvent, QDropEvent, QColor
from PyQt5.QtGui import QFont, QTextCharFormat, QTextCursor, QFontMetrics
import os
import re
from PIL import Image
from PIL.PngImagePlugin import PngImageFile

class PromptLabel(QTextEdit):
    def __init__(self, textedit="", value="", parent=None):
        super().__init__(parent)
        self.textedit = textedit
#        self.setFont(QFont('SansSerif', 12))
#        self.setTextFormat(Qt.RichText)
#        self.setWordWrap(True) 
#        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setFrameStyle(0)  # 枠線を非表示
        self.setReadOnly(True)  # 編集不可
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # スクロールバー非表示
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("background: transparent;")

    def apply_highlight(self, words_to_highlight, color):
        doc = self.document()  # QTextDocument を取得
        format = QTextCharFormat()
        format.setBackground(color)

        for word in words_to_highlight:
            cursor = QTextCursor(doc)  # 新しいカーソルを作成（ドキュメントの先頭）
            while True:
                cursor = doc.find(word, cursor)  # `word` を検索
                if cursor.isNull():  # 見つからなければ終了
                    break
                cursor.mergeCharFormat(format)  # ハイライト適用

    def adjust_text_edit_height(self):
        """QTextEdit の高さをテキスト内容に応じて自動調整"""
        document = self.document()
        document.setTextWidth(self.viewport().width())
        height = int(document.size().height())
        height = QFontMetrics(document().defaultFont()).boundingRect(document).height() 
        self.setFixedHeight(height + 5)  # 余白分を加味

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

class MyLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        # マウスイベントを追跡
        self.setMouseTracking(True)
    
    def wheelEvent(self, event):
        self.parent().parent().parent().parent().parent().parent().parent().parent().wheelEvent1(event)
        event.accept()
        """
        # ラベル上でのホイールイベントを直接処理
        if event.angleDelta().y() > 0:
            self.parent().showNextImage()  # 親ウィジェットのメソッド呼び出し
        else:
            self.parent().showPrevImage()
        event.accept()
        """

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
        
        self.single_view = QWidget()
        self.setup_single_view()
        self.tab_widget.addTab(self.single_view, "Single View")
        
        self.compare_view = QWidget()
        self.setup_compare_view()
        self.tab_widget.addTab(self.compare_view, "Compare View")
        
#        self.setup_toolbar()
        
        self.current_folder = ""
        self.current_image_path = ""

        self.setAcceptDrops(True) 
        self.image_label.installEventFilter(self)
        self.left_view["image_label"].installEventFilter(self)
        self.right_view["image_label"].installEventFilter(self)
        
    def setup_single_view(self):
        layout = QVBoxLayout(self.single_view)

        toolbar = self.setup_toolbar1()
        send_button = QPushButton()
        toolbar.addWidget(send_button)
        layout.addLayout(toolbar)
        
        self.splitter = QSplitter(Qt.Vertical)
        layout.addWidget(self.splitter)
        
        # 画像表示用のスクロールエリア
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
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
        self.splitter.splitterMoved.connect(self.update_images)

    def setup_compare_view(self):
        layout = QHBoxLayout(self.compare_view)
        
        self.left_view = self.create_image_view()
        self.right_view = self.create_image_view()
        
        layout.addWidget(self.left_view["container"])
        layout.addWidget(self.right_view["container"])
        
    def create_image_view(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        toolbar = self.setup_toolbar1()
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Vertical)
        layout.addWidget(splitter)
        
        # 画像表示用のスクロールエリア
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        
        image_label = QLabel()
        image_label.setAlignment(Qt.AlignCenter)
        scroll_area.setWidget(image_label)
        splitter.addWidget(scroll_area)

        # メタデータ表示用のスクロールエリア
        metadata_scroll = QScrollArea()
        metadata_scroll.setWidgetResizable(True)
        metadata_widget = QWidget()
        metadata_layout = QVBoxLayout(metadata_widget)
        metadata_scroll.setWidget(metadata_widget)
        splitter.addWidget(metadata_scroll)
        
        # スプリッターの初期サイズ設定
        splitter.setSizes([400, 500])
        splitter.splitterMoved.connect(self.update_images)

        return {"container": container, 
                "image_label": image_label,
                "metadata_widget": metadata_widget,
                "metadata_layout": metadata_layout,
                "splitter": splitter,
                "current_folder": "",
                "current_image_path": ""}
#       return container
        
    def setup_toolbar(self):
        toolbar = QHBoxLayout()
        self.layout.insertLayout(0, toolbar)
        
        open_button = QPushButton("Open Folder")
        open_button.clicked.connect(self.open_folder)
        toolbar.addWidget(open_button)
        
        copy_seed_button = QPushButton("Copy Seed")
        copy_seed_button.clicked.connect(self.copy_seed)
        toolbar.addWidget(copy_seed_button)
        
        toolbar.addStretch()

    def setup_toolbar1(self):
        toolbar = QHBoxLayout()
#        layout.insertLayout(0, toolbar)
        
        open_button = QPushButton("Open Folder")
        open_button.clicked.connect(self.open_folder)
        toolbar.addWidget(open_button)
        
        copy_seed_button = QPushButton("Copy Seed")
        copy_seed_button.clicked.connect(self.copy_seed)
        toolbar.addWidget(copy_seed_button)
        
        toolbar.addStretch()
 
        return toolbar

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

            # パラメータを正規表現で抽出
#            pattern = r"([^:,]+):\s*([^,]+?)(?=(?:[^:,]+:|$))"
#            matches = re.finditer(pattern, remaining_text)
            
#            for match in matches:
#                key = match.group(1).strip()
#                value = match.group(2).strip()
#                metadata[key] = value

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
            
    def display_metadata(self, metadata, layout, clear=True):
        if clear:
            # 既存のウィジェットをクリア
            while layout.count():
                child = layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
        
        # メタデータを表示
        for key in ["Prompt", "Negative prompt", "Steps", "Sampler", "CFG scale", 
                   "Seed", "Size", "Model", "VAE", 
                   "Denoising strength", "Clip skip"]:
            if key in metadata:
                label = MetadataLabel(key, metadata[key])
                layout.addWidget(label)
        
        layout.addStretch()
        
    def compare_metadata(self, left_metadata, right_metadata):
        # 両方のメタデータウィジェットをクリア
        left_layout = self.left_view["metadata_layout"]
        right_layout = self.right_view["metadata_layout"]
        
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
        
    def load_image(self, image_path, target=None):
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            if target is None:  # Single view
                scaled_pixmap = self.scale_pixmap(pixmap, self.image_label.size())
                self.image_label.setPixmap(scaled_pixmap)
                self.current_image_path = image_path
                
                # メタデータを読み込んで表示
                metadata = self.extract_png_metadata(image_path)
                self.display_metadata(metadata, self.metadata_layout)
            else:  # Compare view
                scaled_pixmap = self.scale_pixmap(pixmap, target["image_label"].size())
                target["image_label"].setPixmap(scaled_pixmap)
                target["current_image_path"] = image_path
                
                # メタデータを読み込む
                metadata = self.extract_png_metadata(image_path)
                self.display_metadata(metadata, target["metadata_layout"])
                target["current_path"] = image_path

                # 両方の画像が読み込まれている場合は比較表示
                if (self.left_view["image_label"].pixmap() and self.right_view["image_label"].pixmap()):
                    left_metadata = self.extract_png_metadata(self.left_view.get("current_path", ""))
                    right_metadata = self.extract_png_metadata(self.right_view.get("current_path", ""))

                    self.compare_metadata(left_metadata, right_metadata)
                  
    def scale_pixmap(self, pixmap, size):
        return pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            
    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.current_folder = folder
            self.load_first_image()
            
    def load_first_image(self):
        image_files = [f for f in os.listdir(self.current_folder) 
                      if f.lower().endswith(('.png'))]
        if image_files:
            if self.tab_widget.currentIndex() == 0:  # Single view
                self.load_image(os.path.join(self.current_folder, image_files[0]))
            else:  # Compare view
                # 左側に最初の画像を読み込む
                self.load_image(os.path.join(self.current_folder, image_files[0]), 
                              self.left_view)
                # 2枚目の画像があれば右側に読み込む
                if len(image_files) > 1:
                    self.load_image(os.path.join(self.current_folder, image_files[1]), 
                                  self.right_view)
        else:
            self.image_label.setText("no png files found")
            self.current_image_path = ""
            while self.metadata_layout.count():
                child = self.metadata_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

    def copy_seed(self):
        # 現在のタブに応じてSeedをクリップボードにコピー
        if self.tab_widget.currentIndex() == 0:  # Single view
            for i in range(self.metadata_layout.count()):
                item = self.metadata_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if isinstance(widget, MetadataLabel) and widget.label == "Seed":
                        QApplication.clipboard().setText(widget.value)
                        break
        else:  # Compare view
            # アクティブな方のSeedをコピー
            # TODO: 必要に応じて左右どちらのSeedをコピーするか選択できるように改善
            for i in range(self.left_view["metadata_layout"].count()):
                item = self.left_view["metadata_layout"].itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if isinstance(widget, MetadataLabel) and widget.label == "Seed":
                        QApplication.clipboard().setText(widget.value)
                        break

    def wheelEvent1(self, event):
        if self.current_folder and self.tab_widget.currentIndex() == 0:  # Single view
            image_files = sorted([f for f in os.listdir(self.current_folder) 
                                if f.lower().endswith(('.png'))])
            if image_files == []:
                return
            
            current_index = image_files.index(os.path.basename(self.current_image_path))
            
            if event.angleDelta().y() > 0:
                new_index = (current_index - 1) % len(image_files)
            else:
                new_index = (current_index + 1) % len(image_files)
                
            self.load_image(os.path.join(self.current_folder, image_files[new_index]))

    def wheelEvent2(self, event, cview):
        if self.tab_widget.currentIndex() != 0:  # multi vew

            if cview["current_folder"] == "":
                return
                 
            image_files = sorted([f for f in os.listdir(cview["current_folder"]) 
                            if f.lower().endswith(('.png'))])
            current_index = image_files.index(os.path.basename(cview["current_image_path"]))
            
            if event.angleDelta().y() > 0:
                new_index = (current_index - 1) % len(image_files)
            else:
                new_index = (current_index + 1) % len(image_files)
            
            self.load_image(os.path.join(cview["current_folder"], image_files[new_index]), cview)



    def eventFilter(self, watched, event):
        if event.type() == QEvent.Wheel:
            # ホイールイベント処理
            if watched == self.image_label:
                self.wheelEvent1(event)
            elif watched == self.left_view["image_label"]:
                self.wheelEvent2(event, self.left_view)
            elif watched == self.right_view["image_label"]:
                self.wheelEvent2(event, self.right_view)

        return super().eventFilter(watched, event)
    

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            
    def dropEvent(self, event: QDropEvent):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        if files:
            if os.path.isfile(files[0]) and files[0].lower().endswith('.png'):
                if self.tab_widget.currentIndex() == 0:  # Single view
                    self.load_image(files[0])
                    self.current_folder = os.path.dirname(files[0])
                else:  # Compare view
                    pos = event.pos()
                    if self.left_view["container"].geometry().contains(pos):
                        self.load_image(files[0], self.left_view)
                        self.left_view["current_folder"] = os.path.dirname(files[0])
                    elif self.right_view["container"].geometry().contains(pos):
                        self.load_image(files[0], self.right_view)
                        self.right_view["current_folder"] = os.path.dirname(files[0])

    def update_images(self):
        """スプリッターのサイズに応じて画像をリサイズ"""
        if self.tab_widget.currentIndex() == 0:  # Single view
            if self.current_folder:
                sizes = self.splitter.sizes()  # 各ウィジェットのサイズを取得
                img1 = QPixmap(self.current_image_path)

                # 各ラベルのサイズに合わせて画像をリサイズ
                self.image_label.setPixmap(img1.scaled(self.image_label.width(), sizes[0], Qt.KeepAspectRatio, Qt.SmoothTransformation))

        else:
            sender = self.sender()
            if sender == self.left_view["splitter"]:
                sizes = self.left_view["splitter"].sizes()  # 各ウィジェットのサイズを取得

                img1 = QPixmap(self.left_view["current_image_path"])
                self.left_view["image_label"].setPixmap(img1.scaled(self.left_view["image_label"].width(), sizes[0], Qt.KeepAspectRatio, Qt.SmoothTransformation))

                img2 = QPixmap(self.right_view["current_image_path"])
                self.right_view["image_label"].setPixmap(img2.scaled(self.left_view["image_label"].width(), sizes[0], Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.right_view["splitter"].setSizes(sizes)

            elif sender == self.right_view["splitter"]:
                sizes = self.right_view["splitter"].sizes()  # 各ウィジェットのサイズを取得
                img1 = QPixmap(self.right_view["current_image_path"])
                self.right_view["image_label"].setPixmap(img1.scaled(self.right_view["image_label"].width(), sizes[0], Qt.KeepAspectRatio, Qt.SmoothTransformation))

            else:
                if self.current_folder:
                    sizes1 = self.left_view["splitter"].sizes()  # 各ウィジェットのサイズを取得
                    img1 = QPixmap(self.left_view["current_image_path"])
                    self.left_view["image_label"].setPixmap(img1.scaled(self.left_view["image_label"].width(), sizes1[0], Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    sizes2 = self.right_view["splitter"].sizes()  # 各ウィジェットのサイズを取得
                    img2 = QPixmap(self.right_view["current_image_path"])
                    self.right_view["image_label"].setPixmap(img2.scaled(self.right_view["image_label"].width(), sizes2[0], Qt.KeepAspectRatio, Qt.SmoothTransformation))


    def resizeEvent(self, event):
        """ウィンドウリサイズ時にも画像を更新"""
        self.update_images()
        super().resizeEvent(event)

if __name__ == '__main__':
    app = QApplication([])
    viewer = ImageViewer()
    viewer.show()
    app.exec_()
    