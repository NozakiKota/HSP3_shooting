"""
Windows Activity Logger - Core Module
アクティブウィンドウを監視してCSVに記録する
"""
import csv
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Windows環境でのみ pywin32 / psutil を使用
try:
    import psutil
    import win32gui
    import win32process
    WINDOWS = True
except ImportError:
    WINDOWS = False


@dataclass
class ActivityRecord:
    timestamp: str
    app_name: str
    window_title: str
    duration_sec: float
    category: str = ""


def _get_active_window_info() -> tuple[str, str]:
    """現在のアクティブウィンドウのアプリ名とタイトルを返す"""
    if not WINDOWS:
        # 開発・テスト用モック
        return "MockApp", "Mock Window Title"

    try:
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        proc = psutil.Process(pid)
        app_name = proc.name().replace(".exe", "")
        return app_name, title
    except Exception:
        return "Unknown", ""


def _categorize(app_name: str, title: str) -> str:
    """アプリ名からカテゴリを推定する"""
    app_lower = app_name.lower()
    title_lower = title.lower()

    categories = {
        "browser": ["chrome", "firefox", "edge", "safari", "opera"],
        "communication": ["teams", "slack", "zoom", "outlook", "thunderbird", "discord"],
        "development": ["code", "pycharm", "idea", "vim", "notepad++", "sublime", "cursor"],
        "office": ["excel", "word", "powerpoint", "onenote", "libreoffice"],
        "file_manager": ["explorer", "finder"],
        "terminal": ["cmd", "powershell", "terminal", "bash", "wsl"],
        "meeting": ["teams", "zoom", "webex", "meet"],
    }

    for category, keywords in categories.items():
        if any(k in app_lower or k in title_lower for k in keywords):
            return category

    return "other"


class ActivityLogger:
    """
    バックグラウンドでアクティブウィンドウを監視し、
    操作ログをメモリと CSV ファイルに記録する。
    """

    DEFAULT_INTERVAL = 5  # 秒ごとにポーリング

    def __init__(self, output_dir: str = "logs", interval: int = DEFAULT_INTERVAL):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.interval = interval

        self._records: list[ActivityRecord] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._csv_path = self._new_csv_path()
        self._init_csv()

    # ------------------------------------------------------------------
    # 公開 API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """ロギングを開始する"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """ロギングを停止する"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self.interval + 2)

    def get_records(self) -> list[ActivityRecord]:
        """収集済みのレコードをコピーして返す"""
        with self._lock:
            return list(self._records)

    def get_csv_path(self) -> Path:
        return self._csv_path

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ------------------------------------------------------------------
    # 内部処理
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        prev_app = ""
        prev_title = ""
        prev_time = datetime.now()

        while not self._stop_event.is_set():
            app_name, title = _get_active_window_info()
            now = datetime.now()

            # ウィンドウが切り替わったときだけ記録
            if app_name != prev_app or title != prev_title:
                if prev_app:
                    duration = (now - prev_time).total_seconds()
                    record = ActivityRecord(
                        timestamp=prev_time.strftime("%Y-%m-%d %H:%M:%S"),
                        app_name=prev_app,
                        window_title=prev_title,
                        duration_sec=round(duration, 1),
                        category=_categorize(prev_app, prev_title),
                    )
                    self._save_record(record)

                prev_app = app_name
                prev_title = title
                prev_time = now

            self._stop_event.wait(self.interval)

    def _save_record(self, record: ActivityRecord) -> None:
        with self._lock:
            self._records.append(record)

        with open(self._csv_path, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                record.timestamp,
                record.app_name,
                record.window_title,
                record.duration_sec,
                record.category,
            ])

    def _new_csv_path(self) -> Path:
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.output_dir / f"activity_{date_str}.csv"

    def _init_csv(self) -> None:
        with open(self._csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "app_name", "window_title", "duration_sec", "category"])
