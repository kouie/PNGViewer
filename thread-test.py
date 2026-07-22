import sys
from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, 
    QPushButton, QSpinBox, QLabel, QLineEdit
)

class WorkerThread(QThread):
    # メインスレッド（UI）へ状態やメッセージを送るシグナル
    log_signal = Signal(str)

    def __init__(self, initial_params, parent=None):
        super().__init__(parent)
        self._params = initial_params.copy()
        self._mutex = QMutex()
        self._is_running = True

    def update_params(self, new_params):
        """UIスレッド側から呼ばれる：新しいパラメータを安全に格納する"""
        with QMutexLocker(self._mutex):
            self._params = new_params.copy()
        self.log_signal.emit(f"［システム］ 次のループ向けにパラメータを更新しました: {new_params}")

    def stop(self):
        """UIスレッド側から呼ばれる：ループの停止を要求する"""
        with QMutexLocker(self._mutex):
            self._is_running = False

    def run(self):
        self.log_signal.emit("［スレッド］ ループ処理を開始します。")
        
        while True:
            # 1. ループ先頭：Mutexをかけて継続フラグとパラメータを安全に取り出す（スナップショット）
            self._mutex.lock()
            is_running = self._is_running
            current_params = self._params.copy()
            self._mutex.unlock()

            # 停止が要求されていたらループを抜ける
            if not is_running:
                break

            # 2. 取り出した値（最初の値 or 前回更新された値）を使って1回分のループ処理を行う
            self.log_signal.emit(f"［スレッド］ ★ ループ実行中 (適用値: {current_params})")
            
            # --- 1分程度かかる処理のシミュレーション ---
            # ※1分間の重い処理やスリープを行う場合、停止ボタンの反応を良くするために
            # 細かく分割して _is_running をチェックするのがベストプラクティスです。
            for _ in range(5): # デモ用：1秒 × 5回 = 5秒
                self.msleep(1000)
                
                # 処理の途中でも停止ボタンが押されたらすぐ抜けるためのチェック
                self._mutex.lock()
                if not self._is_running:
                    self._mutex.unlock()
                    break
                self._mutex.unlock()

        self.log_signal.emit("［スレッド］ ループ処理が完全に停止しました。")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("パラメータ動的反映ループのデモ")
        self.resize(400, 300)

        # UI要素の構築
        self.widget = QWidget()
        self.layout = QVBoxLayout(self.widget)

        self.label_info = QLabel("ループ中にも値変更可能です（次回ループで適用）：")
        self.layout.addWidget(self.label_info)

        # 変更対象のUI要素例
        self.spin_box = QSpinBox()
        self.spin_box.setRange(1, 100)
        self.spin_box.setValue(10)
        self.layout.addWidget(self.spin_box)

        self.line_edit = QLineEdit("テストデータ")
        self.layout.addWidget(self.line_edit)

        # 開始・停止ボタン
        self.btn_start = QPushButton("処理開始")
        self.btn_stop = QPushButton("処理停止")
        self.btn_stop.setEnabled(False)
        self.layout.addWidget(self.btn_start)
        self.layout.addWidget(self.btn_stop)

        # ログ表示用
        self.label_log = QLabel("待機中...")
        self.label_log.setWordWrap(True)
        self.layout.addWidget(self.label_log)

        self.setCentralWidget(self.widget)

        # ワーカースレッドの保持用
        self.worker = None

        # シグナル・スロットの接続
        self.btn_start.clicked.connect(self.start_processing)
        self.btn_stop.clicked.connect(self.stop_processing)
        
        # UIの値が変更されたら、リアルタイムでスレッドに伝える
        self.spin_box.valueChanged.connect(self.on_ui_changed)
        self.line_edit.textChanged.connect(self.on_ui_changed)

    def get_current_ui_params(self):
        """現在のUIの値を辞書にまとめる"""
        return {
            "speed": self.spin_box.value(),
            "text": self.line_edit.text()
        }

    def start_processing(self):
        # 最初の一歩：その時点のUIパラメータを取得してスレッドを作成
        initial_params = self.get_current_ui_params()
        self.worker = WorkerThread(initial_params)
        
        # シグナル接続
        self.worker.log_signal.connect(self.label_log.setText)
        self.worker.finished.connect(self.on_thread_finished)

        # UI状態の切り替え
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

        self.worker.start()

    def stop_processing(self):
        if self.worker and self.worker.isRunning():
            self.label_log.setText("［システム］ 停止処理中...")
            self.worker.stop()
            self.btn_stop.setEnabled(False)

    def on_ui_changed(self):
        """ループ中にUIの値が変わった時の処理"""
        if self.worker and self.worker.isRunning():
            new_params = self.get_current_ui_params()
            # スレッド側の更新メソッドを安全に呼ぶ
            self.worker.update_params(new_params)

    def on_thread_finished(self):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.worker = None


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())