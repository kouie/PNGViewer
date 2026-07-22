from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QLabel, QSplitter, QPushButton, QTextEdit, 
                           QFileDialog, QTabWidget, QScrollArea, QFrame, QLineEdit, QLayout, qApp,
                           QDialog, QCheckBox, QMenu, QAction, QWidgetAction, QMessageBox, QSlider)
from PyQt5.QtCore import Qt, QSize, QRect, QEvent, pyqtSignal, QMimeData, QUrl, QPoint, QByteArray 
from PyQt5.QtGui import QPixmap, QDragEnterEvent, QDropEvent, QColor, QDrag, QCursor, QGuiApplication
from PyQt5.QtGui import QFont, QTextCharFormat, QTextCursor, QFontMetrics, QIcon, QTextDocument
import os
import re
import json
from pathlib import Path
from PIL import Image
from PIL.PngImagePlugin import PngImageFile
from functools import partial

class MetadataLabel(QLabel):
    r_button_clicked = pyqtSignal()

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
        # デフォルトのコンテキストメニューを作成
        menu = QMenu(self)
        
        # デフォルトのアクションを追加
        copyAction = menu.addAction("コピー")
        copyAction.triggered.connect(self.copy)
        
        selectAllAction = menu.addAction("項目の値をコピー")
        selectAllAction.triggered.connect(self.selectAll)
        
        # セパレーターを追加
        menu.addSeparator()
        
        # カスタムアクションを追加
        customAction = menu.addAction("項目を選択...")
        customAction.triggered.connect(self.on_r_mouse_clicked)
        
        # メニューを表示
        menu.exec_(event.globalPos())

    def on_r_mouse_clicked(self):
        self.r_button_clicked.emit()

    def copy(self):
        # テキストをクリップボードにコピー
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(self.selectedText())
    
    def selectAll(self):
#        raw = self.value.replace("\n","")
#        self.setSelection(len(self.label)+2, len(raw)-2)
        clipboard = QGuiApplication.clipboard()        
        clipboard.setText(self.value)


class CheckableListDialog(QDialog):
    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.setWindowTitle("項目選択")
        self.resize(150, 400)
        self.layout = QVBoxLayout(self)
        
        # チェックボックス付きのリスト
        self.checkboxes = []
        for item in items:
            checkbox = QCheckBox(item)
            self.checkboxes.append(checkbox)
            self.layout.addWidget(checkbox)
        
        # OKボタン
        self.okButton = QPushButton("OK")
        self.okButton.clicked.connect(self.accept)
        self.layout.addWidget(self.okButton)
    
    def getSelectedItems(self):
        selected = []
        for checkbox in self.checkboxes:
            if checkbox.isChecked():
                selected.append(checkbox.text())
        return selected
    
class OpenNavigationButtan(QPushButton):
    new_folder = pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.current_folder = ""
        self.pinned_folders = []
        self.folder_history = []
        self.history_index = -1

        self.clicked.connect(self.open_folder)
        self.customContextMenuRequested.connect(self.show_context_menu)        

    def create_pinned_folder_widget(self, folder):
        """ピン留めフォルダ用のウィジェットを作成（チェックボックス付き）"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(20, 0, 5, 0)

        # スペースを追加してインデント効果を作る
        indent_label = QLabel("")  # 全角スペースを使用
    
        # フォルダ名だけを表示
        folder_name = os.path.basename(folder)
        if not folder_name:  # フォルダがルートの場合
            folder_name = folder
        
        label = QLabel(folder_name)
        label.setToolTip(folder)  # フルパスをツールチップに表示
    
        # 削除ボタン
        delete_button = QPushButton()
        delete_button.setIcon(QIcon.fromTheme("edit-delete"))
        delete_button.setIconSize(QSize(16, 16))
        delete_button.setFixedSize(20, 20)
        delete_button.setToolTip("ピン留め解除")
        delete_button.clicked.connect(lambda: self.unpin_folder(folder))
    
        layout.addWidget(indent_label)
        layout.addWidget(label)
        layout.addStretch()
        layout.addWidget(delete_button)
    
        # ウィジェット全体をクリック可能にする設定
        widget.setMouseTracking(True)
        widget.setCursor(Qt.PointingHandCursor)  # マウスカーソルを手の形に
    
        return widget
    
    def handle_pinned_folder_click(self, event, folder):
        """ピン留めフォルダウィジェットのクリックを処理"""
        # 削除ボタンのクリック以外の場合はフォルダに移動
        if event.button() == Qt.LeftButton:
            # クリックがウィジェット内の削除ボタンでなければフォルダを開く
            child_widget = self.childAt(event.pos())
            if not isinstance(child_widget, QPushButton):
                self.navigate_to_folder(folder)

    def navigate_to_folder(self, folder):
        """指定されたフォルダに移動する"""
        if not os.path.exists(folder):
            QMessageBox.warning(self, "エラー", f"フォルダが見つかりません: {folder}")
            return
            
        # 履歴に追加
        if self.current_folder:
            # 現在位置より先の履歴を削除
            if self.history_index < len(self.folder_history) - 1:
                self.folder_history = self.folder_history[:self.history_index + 1]
            
            self.folder_history.append(self.current_folder)
            self.history_index = len(self.folder_history) - 1
            
        self.current_folder = folder
        self.new_folder.emit()

    def unpin_folder(self, folder):
        """指定されたフォルダのピン留めを解除"""
        if folder in self.pinned_folders:
            self.pinned_folders.remove(folder)

    def show_context_menu(self, pos):
        menu = QMenu(self)
        menu.setMinimumWidth(100)
        m_next = menu.addAction("次のフォルダ")
        m_next.setEnabled(self.current_folder !="" )
        m_next.triggered.connect( partial(self.move_folder, 1) )
        m_prev = menu.addAction("前のフォルダ")
        m_prev.setEnabled(self.current_folder !="" )
        m_prev.triggered.connect( partial(self.move_folder, -1) )
        pinning = menu.addAction("ピン留めする")  
        pinning.setEnabled(self.current_folder !="" and self.current_folder not in self.pinned_folders)
        pinning.triggered.connect(self.pin_current_folder)

        if self.pinned_folders:
            menu.addSeparator()       

            # ピン留めフォルダをメニューに追加
            for folder in self.pinned_folders:
                widget = self.create_pinned_folder_widget(folder)
                widget_action = QWidgetAction(menu)
                widget_action.setDefaultWidget(widget)
            
                # クリック可能なウィジェットを作成
                widget.mouseReleaseEvent = lambda event, f=folder: self.handle_pinned_folder_click(event, f)
            
                menu.addAction(widget_action)
        
        menu.exec_(self.mapToGlobal(pos))

    def pin_current_folder(self):
        """現在のフォルダをピン留め"""
        if not self.current_folder:
            return
            
        # 既にピン留めされていないか確認
        if self.current_folder not in self.pinned_folders:
            self.pinned_folders.append(self.current_folder)
#            print(f"フォルダをピン留めしました: {self.current_folder}")

    def open_folder(self):
        if self.current_folder == "":
            folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        else:
            folder = QFileDialog.getExistingDirectory(self, "Select Folder", self.current_folder)

        if folder:
            self.current_folder = folder
            self.new_folder.emit()

    def move_folder(self, direction):
        parent_folder = Path(self.current_folder).parent
        folders = [f for f in os.listdir(parent_folder) if os.path.isdir(parent_folder / f)]

        if len(folders) == 0:
            return

        foldername = Path(self.current_folder).name
        current_index = folders.index(foldername)
        
        new_index = (current_index + direction) % len(folders)
        new_folder_name = parent_folder / folders[new_index]
        self.current_folder = str(new_folder_name).replace("\\", "/")
        self.new_folder.emit()
            
class DraggableImageLabel(QLabel):
    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.image_path = image_path  # 元の画像ファイルパスを保持
        self.setPixmap(QPixmap(image_path))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.pixmap() is None:
                return
            self.drag_start_position = event.pos()

    def mouseMoveEvent(self, event):
        if self.pixmap() is None:
            return
        if not (event.buttons() & Qt.LeftButton):
            return
        if (event.pos() - self.drag_start_position).manhattanLength() < QApplication.startDragDistance():
            return

        drag = QDrag(self)
        mime_data = QMimeData()
        
        # 実際のファイルパスをURLとして設定
        file_url = QUrl.fromLocalFile(os.path.abspath(self.image_path))
        mime_data.setUrls([file_url])
        self.setup_mime_data(mime_data)

        drag.setMimeData(mime_data)
        
        # ドラッグ時のプレビュー表示用
        pixmap = self.pixmap()

        preview_pixmap = pixmap.scaled(100, 100, Qt.KeepAspectRatio)
        drag.setPixmap(preview_pixmap)

        hot_x = int(preview_pixmap.width() / 2)
        hot_y = int(preview_pixmap.height() / 2)
        drag.setHotSpot(QPoint(hot_x, hot_y))

        drag.exec_(Qt.CopyAction)

    def setup_mime_data(self, mime_data):
        """MIMEデータをセットアップ（サブクラスでオーバーライド可能）"""
        # 基底クラスでは基本的なMIMEタイプのみ設定
        mime_data.setData("application/x-imageviewer", QByteArray(self.image_path.encode()))        


class ViewerDraggableLabel(DraggableImageLabel):
    deleteRequested = pyqtSignal(str)

    def __init__(self, image_path, parent=None):
        super().__init__(image_path, parent)        
        self.setAcceptDrops(True)  # ドロップも受け付けるように変更     
        self.thumbnail_size = 150   
        
        # 固定サイズを設定（パディングを考慮）
        padding = 8  # ボーダーとパディングの合計
        self.setFixedSize(self.thumbnail_size + padding, self.thumbnail_size + padding)
        
        # コンテキストメニュー（右クリックメニュー）を有効化
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.showContextMenu)

    def setup_mime_data(self, mime_data):
        """コレクション用のMIMEデータをセットアップ"""
        super().setup_mime_data(mime_data)
        # コレクション内での順序変更用のデータを追加
        mime_data.setData("application/x-image-sortable", QByteArray(self.image_path.encode()))
        
    def dragEnterEvent(self, event):
        """ドラッグがサムネイル上に入ったときの処理（サムネイル入れ替え用）"""
        if event.mimeData().hasFormat("application/x-image-sortable"):
            # 内部ドラッグの場合は受け入れる
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dropEvent(self, event):
        """ドロップされたときの処理（サムネイル入れ替え用）"""
        if event.mimeData().hasFormat("application/x-image-sortable"):
            # ドロップされた画像のパスを取得
            source_path = event.mimeData().data("application/x-image-sortable").data().decode()
            target_path = self.image_path
            
            # 自分自身へのドロップの場合は無視
            if source_path == target_path:
                event.ignore()
                return
            
            # 親ウィジェット（CollectionWidget）に順序変更を通知
            parent = self.parent()

            # 親をたどってCollectionWidgetを探す
            while parent:
                if isinstance(parent, CollectionWidget):
                    collection_widget = parent
                    break
                parent = parent.parent()

            # CollectionWidgetが見つかったら順序変更を通知
            if collection_widget and hasattr(collection_widget, 'swapImages'):
                collection_widget.swapImages(source_path, target_path)
                event.acceptProposedAction()
            else:
                print("CollectionWidget not found or swapImages method not available")
                event.ignore()
        else:
            event.ignore()

    def showContextMenu(self, position):
        """右クリックメニューを表示"""
        context_menu = QMenu(self)
        
        # 削除アクション
        delete_action = context_menu.addAction("削除")
        delete_action.triggered.connect(lambda: self.deleteRequested.emit(self.image_path))
        
        # メニューを表示
        context_menu.exec_(self.mapToGlobal(position))

class SliderPopup(QFrame):
    def __init__(self, folder, index, parent=None):
        super().__init__(parent)
        # フレームのスタイルを設定
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setWindowFlags(Qt.Popup)  # ポップアップウィンドウとして設定

        self.image_folder = folder
        self.image_files = []
        self.current_index = index

        # レイアウト設定
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # スライダーの作成
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(0)
        layout.addWidget(self.slider)
        
        # 幅を設定
        self.setFixedWidth(300)

    def mousePressEvent(self, event):
        # スライダー内でのクリックイベントは親に伝搬しない
        super().mousePressEvent(event)
        event.accept()

class FlowLayout(QLayout):    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(5)
        
        self.items = []  # レイアウトアイテムのリスト
    
    def __del__(self):
        # アイテムを削除
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)
    
    def addItem(self, item):
        self.items.append(item)
    
    def count(self):
        return len(self.items)
    
    def itemAt(self, index):
        if 0 <= index < self.count():
            return self.items[index]
        return None
    
    def takeAt(self, index):
        if 0 <= index < self.count():
            return self.items.pop(index)
        return None
    
    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))  # 拡張方向なし
    
    def hasHeightForWidth(self):
        return True
    
    def heightForWidth(self, width):
        return self.do_layout(QRect(0, 0, width, 0))

    def sizeHint(self):
        return self.minimumSize()
    
    def minimumSize(self):
        size = QSize()
        
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
            
        margin = self.contentsMargins()
        size += QSize(margin.left() + margin.right(), margin.top() + margin.bottom())
        return size

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.do_layout(rect)
        
    def do_layout(self, rect):
        x = rect.x()
        y = rect.y()
        line_height = 0
        layout_spacing = 10
        
        for item in self.items:
            next_x = x + item.sizeHint().width() + layout_spacing
            if next_x - layout_spacing > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + layout_spacing
                next_x = x + item.sizeHint().width() + layout_spacing
                line_height = 0

            item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = next_x
            line_height = max(line_height, item.sizeHint().height())
        
        return y + line_height - rect.y()

class CollectionWidget(QWidget):
    """画像コレクションを表示するウィジェット"""
    
    # 画像が選択されたときのシグナル（パスを送信）
    image_selected = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.images = []  # 画像パスのリスト
        self.thumbnail_size = 150
        self.thumbnails = []  # サムネイルウィジェットのリスト
        self.thumbnail_map = {}
        self.setMinimumWidth(170)

    def init_ui(self):
        # ウィジェットのレイアウト設定
        self.main_layout = QVBoxLayout(self)
        
        # ツールバー用のレイアウト
        toolbar_layout = QHBoxLayout()
        
        # クリアボタン
        self.clear_button = QPushButton("クリア", self)
        self.clear_button.setFixedWidth(40)
        self.clear_button.clicked.connect(self.clear_collection)
        toolbar_layout.addWidget(self.clear_button)

        text_box = QLineEdit()
        text_box.setMinimumWidth(100)
        text_box.setPlaceholderText(" メモ...")        
        toolbar_layout.addWidget(text_box)

        toolbar_layout.addStretch(1)
        
        # メインレイアウトにツールバーを追加
        self.main_layout.addLayout(toolbar_layout)
        
        # スクロール可能なエリア
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setFrameShape(QFrame.NoFrame)

        # コンテンツウィジェット
        self.scroll_content = QWidget()
        
        # カスタムのフローレイアウトを使用
        self.flow_layout = FlowLayout(self.scroll_content)
        
        # コンテンツウィジェットにフローレイアウトを設定
        self.scroll_content.setLayout(self.flow_layout)
        
        self.scroll_area.setWidget(self.scroll_content)
        self.main_layout.addWidget(self.scroll_area)
        
        # ドラッグ&ドロップを受け付ける設定
        self.setAcceptDrops(True)
    
    def add_image(self, image_path):
        """コレクションに画像を追加"""
        if image_path in self.images:
            return  # 既に追加済みの場合はスキップ
        
        # 画像パスをリストに追加
        self.images.append(image_path)
        
        # 画像サムネイルの作成
        thumbnail = ViewerDraggableLabel("", self)
        pixmap = QPixmap(image_path)
        scaled_image = pixmap.scaled(self.thumbnail_size, self.thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        thumbnail.setPixmap(scaled_image)

        thumbnail.setAlignment(Qt.AlignCenter)
        thumbnail.setFixedSize(self.thumbnail_size, self.thumbnail_size)
        thumbnail.image_path = image_path
        
        # クリックイベントの処理
        # mousePressEventを上書きするのではなく、クリックシグナルを接続
        thumbnail.mouseClicked = lambda img_path: self.image_selected.emit(img_path)

        # 削除リクエストのシグナルを接続
        thumbnail.deleteRequested.connect(self.remove_image)

        # サムネイルをリストに追加
        self.thumbnails.append(thumbnail)
        
        # パスからサムネイルへのマッピングを更新
        self.thumbnail_map[image_path] = thumbnail

        # フローレイアウトに追加
        self.flow_layout.addWidget(thumbnail)
        
        # レイアウトを更新
        self.flow_layout.update()

    def remove_image(self, image_path):
        """特定の画像をコレクションから削除"""
        if image_path in self.images:
            # リストから画像パスを削除
            self.images.remove(image_path)
            
            # サムネイルを取得して削除
            if image_path in self.thumbnail_map:
                thumbnail = self.thumbnail_map[image_path]
                self.thumbnails.remove(thumbnail)
                del self.thumbnail_map[image_path]
                
                # ウィジェットをレイアウトと親から削除
                thumbnail.setParent(None)
                
                # レイアウトを更新
                self.flow_layout.update()

    def swapImages(self, source_path, target_path):
        """画像の順序を入れ替える"""
        if source_path in self.images and target_path in self.images:
            # 現在のインデックスを取得
            source_idx = self.images.index(source_path)
            target_idx = self.images.index(target_path)
            
            # リスト内での順序を入れ替え
            # 相互に入替
#            self.images[source_idx], self.images[target_idx] = self.images[target_idx], self.images[source_idx]
            source_image = self.images.pop(source_idx)  # ドロップ位置に挿入
            self.images.insert(target_idx, source_image)
            
            # 一度すべてのサムネイルをレイアウトから削除
            for thumbnail in self.thumbnails:
                thumbnail.setParent(None)
            
            # 新しい順序でウィジェットを追加し直す
            for image_path in self.images:
                if image_path in self.thumbnail_map:
                    thumbnail = self.thumbnail_map[image_path]
                    self.flow_layout.addWidget(thumbnail)
            
            # レイアウトを更新
            self.flow_layout.update()

    def clear_collection(self):
        """コレクションをクリア"""
        # フローレイアウトからすべてのウィジェットを削除
        for thumbnail in self.thumbnails:
            thumbnail.setParent(None)
        
        # サムネイルと画像リストをクリア
        self.thumbnails.clear()
        self.images.clear()
        
        # レイアウトを更新
        self.flow_layout.update()
    
    # _on_thumbnail_clicked メソッドは削除
    # 代わりに DraggableLabel クラスの mousePressEvent 内でクリックを処理
    
    def dragEnterEvent(self, event):
        """ドラッグがウィジェット上に入ったときのイベント"""
        mime_data = event.mimeData()
        
        # URLのドラッグを受け付ける（ファイルのドラッグ）
        if mime_data.hasUrls():
            for url in mime_data.urls():
                if url.isLocalFile():
                    file_path = url.toLocalFile()
                    ext = os.path.splitext(file_path)[1].lower()
                    if ext in ['.png']:
                        event.acceptProposedAction()
                        return
        
        event.ignore()
    
    def dropEvent(self, event):
        """ドロップイベントの処理"""
        mime_data = event.mimeData()
        
        if mime_data.hasUrls():
            for url in mime_data.urls():
                if url.isLocalFile():
                    file_path = url.toLocalFile()
                    ext = os.path.splitext(file_path)[1].lower()
                    if ext in ['.png']:
                        self.add_image(file_path)
            
            event.acceptProposedAction()

class CollectionWindow(QMainWindow):
    """コレクションを表示するウィンドウ"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.collection_widget = CollectionWidget(self)
        self.setCentralWidget(self.collection_widget)
        
        self.setWindowTitle("画像コレクション")
        self.resize(700, 200)
        
        # メインウィンドウとの連携用シグナル
        self.collection_widget.image_selected.connect(self.on_image_selected)

        # ウィンドウサイズが変更されたら、レイアウトを更新
        self.resizeEvent = self.on_resize

    def on_image_selected(self, image_path):
        """画像が選択されたときのスロット（必要に応じてメインウィンドウに通知）"""
        # ここでメインウィンドウに通知したりできます
        print(f"選択された画像: {image_path}")
        
    def add_image(self, image_path):
        """コレクションに画像を追加するメソッド（外部からも呼び出し可能）"""
        self.collection_widget.add_image(image_path)

    def on_resize(self, event):
        """ウィンドウサイズ変更時のイベント"""
        # サイズ変更時にフローレイアウトを更新
        if hasattr(self, 'collection_widget') and hasattr(self.collection_widget, 'flow_layout'):
            self.collection_widget.flow_layout.update()
        
        # 通常のリサイズイベント処理も実行
        super().resizeEvent(event)

    def closeEvent(self, event):
        # 親クラスに自分自身を認識させる方法で通知
        if self.parent() and hasattr(self.parent(), 'remove_collection'):
            self.parent().remove_collection(self)

        # 標準のcloseEvent処理を呼び出す
        super().closeEvent(event)

class originalViewWindow(QMainWindow):
    """原寸ビューを表示するウィンドウ"""
    originalWindowClosed = pyqtSignal(object)

    def __init__(self, image_file, parent=None):
        super().__init__(parent)

        self.original_view = QWidget(self)
        self.setCentralWidget(self.original_view)
        self.layout = QVBoxLayout(self.original_view)

        self.setWindowTitle(f"オリジナルサイズ - {image_file}")
        
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)

        self.image_label.setMouseTracking(True)
        self.image_label.mouseDoubleClickEvent = self.on_image_double_click

        self.pixmap = QPixmap(image_file)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(self.image_label)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.layout.addWidget(self.scroll_area)

        # ウィンドウ移動関連の変数を初期化
        self.dragging = False
        self.drag_position = None
        
        # 画像を表示
        pixmap = QPixmap(image_file)
        self.image_label.setPixmap(pixmap)
        self.resize_window_to_image(pixmap)

    def resize_window_to_image(self, pixmap):
        """ウィンドウサイズを画像サイズに合わせて調整（画面サイズを考慮）"""
        screen_size = QApplication.primaryScreen().availableSize()
        img_width = pixmap.width()
        img_height = pixmap.height()
        
        # 画面サイズの80%を超える場合は制限
        max_width = int(screen_size.width() * 0.8)
        max_height = int(screen_size.height() * 0.8)
        
        width = min(img_width, max_width)
        height = min(img_height, max_height)
        
        self.resize(width + 40, height + 30)  # スクロールバーのスペースを考慮

    def mousePressEvent(self, event):
        """マウスボタンが押されたときの処理"""
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        """マウスが移動したときの処理"""
        if event.buttons() == Qt.LeftButton and self.dragging:
            self.move(event.globalPos() - self.drag_position)
            event.accept()
    
    def mouseReleaseEvent(self, event):
        """マウスボタンが離されたときの処理"""
        if event.button() == Qt.LeftButton:
            self.dragging = False
            event.accept()

    def on_image_double_click(self, event):
        self.close()

    def closeEvent(self, event):
        # 親クラスに自分自身を認識させる方法で通知
#        if self.parent() and hasattr(self.parent(), 'remove_originalView'):
#            self.parent().remove_originalView(self)

        self.originalWindowClosed.emit(self)

        # 標準のcloseEvent処理を呼び出す
        super().closeEvent(event)

class ImageView(QWidget):
    image_loaded = pyqtSignal()
    area_resized = pyqtSignal(int)
    mouse_clicked = pyqtSignal(QPoint)
    metaarea_changed = pyqtSignal()
    image_double_clicked = pyqtSignal()

    def __init__(self, set_id, parent=None):
        super().__init__(parent)        

        self.metadata = {}
        self.current_image_path = ""
        self.current_folder = ""
        self.current_index = 0
        self.set_id = set_id
        self.meta_tags = ["Prompt", "Negative prompt", "Steps", "Sampler", "CFG scale", 
                   "Seed", "Size", "Model", "VAE", 
                   "Denoising strength", "Variation seed", "Variation seed strength", "Clip skip"]

        self.container = QWidget()
        layout = QVBoxLayout(self.container)
        self.splitter = QSplitter(Qt.Vertical)
        layout.addWidget(self.splitter)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)

#        self.image_label = QLabel()
        self.image_label = DraggableImageLabel("", self)
        
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setText("ファイルをドラッグ&ドロップするか\n左上のボタンをクリックしてフォルダを指定してください")
        self.image_label.setMouseTracking(True)
        self.image_label.mouseDoubleClickEvent = self.on_image_double_click

        scroll_area.setWidget(self.image_label)
        self.splitter.addWidget(scroll_area)

        scroll_area.setContextMenuPolicy(Qt.CustomContextMenu)
        scroll_area.customContextMenuRequested.connect(self.show_slider_popup)

        # メタデータ表示用のスクロールエリア
        metadata_scroll = QScrollArea()
        metadata_scroll.setWidgetResizable(True)
        self.metadata_widget = QWidget()
        self.metadata_layout = QVBoxLayout(self.metadata_widget)
        metadata_scroll.setWidget(self.metadata_widget)
        metadata_scroll.setContextMenuPolicy(Qt.CustomContextMenu)
        metadata_scroll.customContextMenuRequested.connect(self.show_tagSelection_ContextMenu)
        self.splitter.addWidget(metadata_scroll)
        
        # スプリッターの初期サイズ設定
        self.splitter.setSizes([500, 400])
        self.splitter.splitterMoved.connect(self.on_area_resized)

        self.toolbar = self.setup_toolbar()
        layout.insertLayout(0,self.toolbar)

        self.slider_popup = SliderPopup(self.current_folder, self.current_index, self)
        self.slider_popup.slider.valueChanged.connect(self.on_slider_value_changed)
        
        self.image_label.installEventFilter(self)
        self.container.setAcceptDrops(True)
        self.container.installEventFilter(self)

        self.open_button.new_folder.connect(self.on_new_folder)

        self.original_views = [] 

    def setup_toolbar(self):
        toolbar = QHBoxLayout()
        
        self.open_button = OpenNavigationButtan("Open")
#        self.open_button.clicked.connect(self.open_folder)
        self.open_button.setFixedWidth(40)
        toolbar.addWidget(self.open_button)
        
        copy_seed_button = QPushButton("Copy")
        copy_seed_button.clicked.connect(self.copy_seed)
        copy_seed_button.setFixedWidth(40)
        toolbar.addWidget(copy_seed_button)

        # テキスト入力ボックスを追加
#        f_label = QLabel(" Filter:")
        self.text_box = QLineEdit()
        self.text_box.setMinimumWidth(180)
        self.text_box.setPlaceholderText(" filter by prompt text...")
        self.text_box.setClearButtonEnabled(True)
        self.text_box.editingFinished.connect(self.text_entered)
#        toolbar.addWidget(f_label)
        toolbar.addWidget(self.text_box)

        toolbar.addStretch()
 
        self.open_collection_button = QPushButton("CL")
        self.open_collection_button.setFixedWidth(40)
        toolbar.addWidget(self.open_collection_button)

        return toolbar        

    def show_tagSelection_ContextMenu(self, position):
        menu = QMenu()
        selectAction = QAction("項目を選択...", self)
        selectAction.triggered.connect(self.selectItems)
        menu.addAction(selectAction)
        menu.exec_(self.metadata_widget.mapToGlobal(position))

    def on_slider_value_changed(self, index):
        if 0 <= index < len(self.slider_popup.image_files):
            self.current_index = index
            image_path = os.path.join(self.current_folder, self.slider_popup.image_files[index])

        self.load_image(image_path)

    def show_slider_popup(self, position):
        # 画像がない場合は何もしない
        if self.current_folder == "":
            return
        
        # カーソル位置を取得
        cursor_pos = QCursor.pos()

        # スライダーを適切な位置に配置
        # カーソル位置の少し下に表示
        popup_pos = cursor_pos + QPoint(-self.slider_popup.width() // 2, 10)
        
        # ウィンドウ範囲を超えないように調整
        screen_rect = QApplication.desktop().screenGeometry()
        if popup_pos.x() < screen_rect.left():
            popup_pos.setX(screen_rect.left())
        if popup_pos.x() + self.slider_popup.width() > screen_rect.right():
            popup_pos.setX(screen_rect.right() - self.slider_popup.width())
        
        self.slider_popup.image_folder = self.current_folder
        self.slider_popup.current_index = self.current_index
        self.load_images_from_folder()

        self.slider_popup.move(popup_pos)
        self.slider_popup.show()

    def load_images_from_folder(self):

        self.slider_popup.slider.blockSignals(True)
        # 画像ファイルのみをフィルタリング
        valid_extensions = ['.png']
        image_files = [f for f in os.listdir(self.current_folder) 
                          if os.path.isfile(os.path.join(self.current_folder, f)) and 
                          os.path.splitext(f)[1].lower() in valid_extensions]
        image_files.sort()  # ファイル名でソート
        
        # スライダーの設定を更新
        if image_files:
            self.slider_popup.slider.setMaximum(len(image_files) - 1)
            self.slider_popup.image_files = image_files.copy()
            self.slider_popup.slider.setValue(self.current_index)
            
        self.slider_popup.slider.blockSignals(False)

    def selectItems(self):
        meta_all = self.metadata.keys()
        dialog = CheckableListDialog(meta_all, self)
        
        # 既に選択済みの項目にチェックを入れる
        for i, checkbox in enumerate(dialog.checkboxes):
            if checkbox.text() in self.meta_tags:
                checkbox.setChecked(True)
        
        if dialog.exec_():
            self.meta_tags = dialog.getSelectedItems()
            self.display_metadata(self.metadata)    
            self.image_loaded.emit()

    def on_area_resized(self):
        self.area_resized.emit(self.set_id)

    def on_new_folder(self):
        self.current_folder = self.open_button.current_folder
        self.current_index = 0
        self.slider_popup.slider.setValue(0)
        self.load_first_image()
        self.image_loaded.emit()

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
            self.image_label.image_path = ""
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
            self.image_label.image_path = image_path
            
            image_files = sorted([f for f in os.listdir(self.current_folder) 
                            if f.lower().endswith(('.png'))])
            self.current_index = image_files.index(os.path.basename(self.current_image_path))

            # メタデータを読み込んで表示
            metadata = self.extract_png_metadata(image_path)
            self.display_metadata(metadata)
            self.metadata = metadata

        self.image_loaded.emit()
 
    def scale_pixmap(self, pixmap, size):
        return pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def clear_view_area(self, text):
        self.image_label.setText(text)
        while self.metadata_layout.count():
            child = self.metadata_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def change_image(self, event):
        if self.current_folder:
            image_files = sorted([f for f in os.listdir(self.current_folder) 
                            if f.lower().endswith(('.png'))])
            try:
                current_index = image_files.index(os.path.basename(self.current_image_path))
            except:
                if image_files:
                    current_index = (self.current_index - 1) % len(image_files)
                else:
                    self.clear_view_area("no files found")
                    return
            
            new_index = ""
            for idx in range(len(image_files)):
                
                if event.angleDelta().y() > 0:
                    next_index = (current_index - 1) % len(image_files)
                else:
                    next_index = (current_index + 1) % len(image_files)

                next_file = os.path.join(self.current_folder, image_files[next_index])
                metadata = self.extract_png_metadata(next_file)

                query = self.text_box.text()
                if query:
                    if metadata:
                        query = self.text_box.text()
                        prompts = metadata["Prompt"]
                        if re.search(query, prompts):
                            new_index = next_index
                            break
                else:
                    new_index = next_index  
                    break

                if event.angleDelta().y() > 0:
                    current_index = (current_index - 1) % len(image_files)
                else:
                    current_index = (current_index + 1) % len(image_files)

            if new_index == "":
                self.clear_view_area("no files matched ")
                self.metadata.clear()
                self.current_image_path = ""
                return
            
            self.load_image(os.path.join(self.current_folder, image_files[new_index]))

    def text_entered(self):
        if self.current_folder:
            image_files = sorted([f for f in os.listdir(self.current_folder) 
                            if f.lower().endswith(('.png'))])
            try:
                current_index = image_files.index(os.path.basename(self.current_image_path))
            except:
                return
            
            new_index = ""
            for idx in range(len(image_files)):
                next_file = os.path.join(self.current_folder, image_files[current_index])
                metadata = self.extract_png_metadata(next_file)

                if metadata:
                    query = self.text_box.text()
                    prompts = metadata["Prompt"]
                    if re.search(query, prompts):                        
                        new_index = current_index
                        break

                current_index = (current_index + 1) % len(image_files)

            if new_index == "":
                self.image_label.setText("no files found ")
                self.metadata.clear()
                self.current_image_path = ""                
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

    def extract_comfy_metadata(self, value):
        metadata = json.loads(value)
        prompt = {}
        others = {}
        prompt_tags = ["Prompt", "Negative prompt"]
        text_id = 0
        for id, values in metadata.items():
            inputs = values["inputs"]
            class_type = values["class_type"]

            for key, value in inputs.items():
                if class_type == "CLIPTextEncode":
                    if key != "text":
                        continue
                    key_id = key + str(text_id)
#                    if key_id in prompt:
                    if prompt_tags[text_id] in prompt:
                        text_id += 1
                        key_id = key + str(text_id)
#                    prompt[key_id] = str(value)
                    prompt_key = prompt_tags[text_id]
                    prompt[prompt_key] = str(value)
                else:
                    others[key] = str(value)
            
        meta = prompt | others

        return meta



    def extract_png_metadata(self, image_path):
        try:
            with Image.open(image_path) as img:
                if isinstance(img, PngImageFile):
                    # メタデータを検索
                    for key, value in img.info.items():
                        if key.lower() in ['parameters']:
                            return self.parse_metadata(value)
                        elif key.lower() in ['prompt']:
                            meta = self.extract_comfy_metadata(value)
                            return meta
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
        for key in self.meta_tags:
            if key in metadata:
                label = MetadataLabel(key, metadata[key])
                self.metadata_layout.addWidget(label)
                label.r_button_clicked.connect(self.selectItems)

        filename = self.current_image_path.replace("\\","/")
        self.metadata_layout.insertWidget(0, MetadataLabel("File",f"{filename}"))
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
                if isinstance(widget, MetadataLabel):
                    if widget.label == "Seed" or widget.label == "seed":
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
                self.dropped_image(event)
                return True

            return True

        elif event.type() == QEvent.MouseButtonPress:
            # スライダーポップアップが表示されている場合
            if self.slider_popup.isVisible():
                # クリック位置がスライダーの外にある場合
                if not self.slider_popup.geometry().contains(event.globalPos()):
                    self.slider_popup.hide()
                    return True

        return super().eventFilter(watched, event)
    
    def dropped_image(self, event):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        if files:
            if os.path.isfile(files[0]) and files[0].lower().endswith('.png'):
                self.current_folder = os.path.dirname(files[0])
                self.load_image(files[0])
                self.open_button.current_folder = self.current_folder

                # スライダーの設定を更新
#                self.load_images_from_folder()

    def on_image_double_click(self, event):
        """ダブルクリック時に元サイズ表示ウィンドウを開く"""
        if self.current_image_path:
            original_view = originalViewWindow(self.current_image_path)
            original_view.originalWindowClosed.connect(self.remove_originalView)    
            original_view.show()

            self.original_views.append(original_view)

    def remove_originalView(self, original):
        if original in self.original_views:
            self.original_views.remove(original)
#        print(len(self.original_views))     

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
        send_button = QPushButton("Send →")
        self.m_view.toolbar.addWidget(send_button)      
        send_button.clicked.connect( partial(self.send_to, 0, 1) )
        send_button.setContextMenuPolicy(Qt.CustomContextMenu)
        send_button.customContextMenuRequested.connect(self.show_send_context_menu)
        layout.addWidget(self.m_view.container)
        self.tab_widget.addTab(self.s_view, "ｼﾝｸﾞﾙ")

        self.c_view = QWidget()
        layout = QHBoxLayout(self.c_view)
        self.l_view = ImageView(1)
        self.r_view = ImageView(2)

        send_button1 = QPushButton("←")
        send_button1.setFixedWidth(30)
        self.l_view.toolbar.addWidget(send_button1)      
        send_button1.clicked.connect( partial(self.send_to, 1, 0) )
        send_button1.setContextMenuPolicy(Qt.CustomContextMenu)
        send_button1.customContextMenuRequested.connect(self.show_send_context_menu)
        layout.addWidget(self.l_view.container)
        send_button2 = QPushButton("←←")
        send_button2.setFixedWidth(30)
        self.r_view.toolbar.addWidget(send_button2)      
        send_button2.clicked.connect( partial(self.send_to, 2, 0) )
        send_button2.setContextMenuPolicy(Qt.CustomContextMenu)
        send_button2.customContextMenuRequested.connect(self.show_send_context_menu)
        layout.addWidget(self.r_view.container)

        self.collection_windows = []
        self.collection_idx = 0

        self.l_view.image_loaded.connect(self.compare_metadata)
        self.r_view.image_loaded.connect(self.compare_metadata)

        self.l_view.metaarea_changed.connect(self.compare_metadata)
        self.r_view.metaarea_changed.connect(self.compare_metadata)

        self.tab_widget.addTab(self.c_view, "比較")
        self.tab_widget.currentChanged.connect(self.on_tab_changed)

        self.views = [self.m_view, self.l_view, self.r_view]
        self.cp_tags = ["Prompt", "Negative prompt", "Steps", "Sampler", "CFG scale", 
                   "Seed", "Size", "Model", "VAE", 
                   "Denoising strength", "Variation seed", "Variation seed strength", "Clip skip"]

        for view in self.views:
            view.area_resized.connect(self.update_images)
            view.open_collection_button.clicked.connect(self.create_collection)

    def show_send_context_menu(self, pos):
        sender = self.sender()
        menu = QMenu()
        send_move = menu.addAction("送って移動")
        if sender.text() == "Send →":
            send_move.setEnabled(self.m_view.current_folder !="" )
            send_move.triggered.connect( partial(self.send_and_move, 0, 1) )
        elif sender.text() == "←":
            send_move.setEnabled(self.l_view.current_folder !="" )
            send_move.triggered.connect( partial(self.send_and_move, 1, 0) )
        elif sender.text() == "←←":
            send_move.setEnabled(self.r_view.current_folder !="" )
            send_move.triggered.connect( partial(self.send_and_move, 2, 0) )

        menu.exec_(sender.mapToGlobal(pos))

    def send_and_move(self, source, target):
        self.send_to(source, target)
        self.tab_widget.setCurrentIndex(target)


    def compare_metadata(self):
        if self.l_view.current_image_path and self.r_view.current_image_path:
            left_metadata = self.l_view.metadata
            right_metadata = self.r_view.metadata
            if len(left_metadata) == 0 or len(right_metadata) == 0:
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

        l_enable_tags = self.l_view.meta_tags
        r_enable_tags = self.r_view.meta_tags

        left_tags = list(left_metadata.keys())
        right_tags = list(right_metadata.keys())

        all_tag = left_tags.copy()
        for item in right_tags:
            if item not in all_tag:  # 結果リストに存在しない要素のみ追加
                all_tag.append(item)        

        self.cp_tags = all_tag.copy()

        for key in self.cp_tags[0:2]:
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

            if key in l_enable_tags:
                left_label = MetadataLabel(key, left_value)
                left_label.r_button_clicked.connect(self.l_view.selectItems)
                left_layout.addWidget(left_label)
                left_label.apply_highlight(only_in_left, "#ffff80")
            
            # 右側のメタデータを表示
            if key in r_enable_tags:
                right_label = MetadataLabel(key, right_value)
                right_label.r_button_clicked.connect(self.r_view.selectItems)
                right_layout.addWidget(right_label)
                right_label.apply_highlight(only_in_right, "#80ffff")


        # メタデータを比較しながら表示
        for key in self.cp_tags[2:]:
            left_value = left_metadata.get(key, "")
            right_value = right_metadata.get(key, "")
            
            # 左側のメタデータを表示
            if key in l_enable_tags:
                left_label = MetadataLabel(key, left_value)
                left_label.r_button_clicked.connect(self.l_view.selectItems)
                if left_value:
                    left_layout.addWidget(left_label)
            
            # 右側のメタデータを表示
            if key in r_enable_tags:
                right_label = MetadataLabel(key, right_value)
                right_label.r_button_clicked.connect(self.r_view.selectItems)
                if right_value:
                    right_layout.addWidget(right_label)
            
            # 値が異なる場合はハイライト
            if left_value != right_value:
                if key in l_enable_tags:
                    left_label.update_text(highlight=True)
                if key in r_enable_tags:
                    right_label.update_text(highlight=True)
        
        left_layout.addStretch()
        right_layout.addStretch()

        left_file = self.l_view.current_image_path.replace("\\", "/")
        right_file = self.r_view.current_image_path.replace("\\", "/")
        left_layout.insertWidget(0, MetadataLabel("File",f"{left_file}"))
        right_layout.insertWidget(0, MetadataLabel("File",f"{right_file}"))

    def scale_pixmap(self, pixmap, size):
        return pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            
    def send_to(self, source, target):
        self.views[target].current_folder = self.views[source].current_folder
        self.views[target].current_image_path = self.views[source].current_image_path
        self.views[target].image_label.image_path = self.views[source].current_image_path
        self.views[target].load_image(self.views[target].current_image_path)
        self.views[target].open_button.current_folder = self.views[source].current_folder
        self.resize_image(target)

    def dropped_image(self, event, view):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        if files:
            if os.path.isfile(files[0]) and files[0].lower().endswith('.png'):
                view.load_image(files[0])
                view.current_folder = os.path.dirname(files[0])

    def resize_image(self, view_id):
        view = self.views[view_id]
        if os.path.isfile(view.current_image_path):
            sizes = view.splitter.sizes()  # 各ウィジェットのサイズを取得
            img = QPixmap(view.current_image_path)
            view.image_label.setPixmap(img.scaled(view.image_label.width(), sizes[0], Qt.KeepAspectRatio, Qt.SmoothTransformation))

        else:
            if view.current_folder and view.current_image_path:
                view.clear_view_area("png file deleted")
                view.current_image_path = ""
#                view.metadata.clear()

    def on_tab_changed(self, index):
        if index == 0:
            self.resize_image(self.m_view.set_id)
        elif index == 1:
            self.resize_image(self.l_view.set_id)
            self.resize_image(self.r_view.set_id)
            self.compare_metadata()

    def update_images(self, set_id):
        """スプリッターのサイズに応じて画像をリサイズ"""
        if set_id == 1:
            self.resize_image(1)

            # 右側の画像も左のスプリッターに合わせてリサイズ
            sizes = self.l_view.splitter.sizes()
            if os.path.isfile(self.r_view.current_image_path):
                img2 = QPixmap(self.r_view.current_image_path)
                self.r_view.image_label.setPixmap(img2.scaled(self.l_view.image_label.width(), sizes[0], Qt.KeepAspectRatio, Qt.SmoothTransformation))

            else:
                if self.r_view.current_folder and self.r_view.current_image_path:
                    self.r_view.clear_view_area("png file deleted")
                    self.r_view.current_image_path = ""

            self.r_view.splitter.setSizes(sizes)

        elif set_id == 2:
            self.resize_image(2)

        elif set_id == 0:
            self.resize_image(0)

    def create_collection(self):
        """新しいコレクションウィンドウを作成"""
        collection = CollectionWindow(self)
#        pos_y = 200 * ((len(self.collection_windows) + 1) % int(qApp.desktop().screenGeometry().height() / 200))
        collection.setGeometry(self.x() + int(self.width()/2), 200, 700, 200)
        collection.setWindowTitle("Collection " + str(self.collection_idx))
        collection.show()
        self.collection_idx += 1
        
        # コレクションウィンドウのリストに追加
        self.collection_windows.append(collection)
        
    def remove_collection(self, collection):
        """コレクションウィンドウがクローズされたときに呼ばれる"""
        if collection in self.collection_windows:
            self.collection_windows.remove(collection)
    
    def resizeEvent(self, event):
        """ウィンドウリサイズ時にも画像を更新"""
        if self.tab_widget.currentIndex() == 0:
            self.resize_image(self.m_view.set_id)
        else:
            self.resize_image(self.l_view.set_id)
            self.resize_image(self.r_view.set_id)

        super().resizeEvent(event)

if __name__ == '__main__':
    app = QApplication([])
    viewer = ImageViewer()
    viewer.show()
    app.exec_()
    