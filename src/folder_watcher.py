"""
文件夹监听模块 - 自动监测指定文件夹中的新PDF，自动解析并追加到Excel
使用 watchdog 库实现文件系统事件监听
"""
import os
import time
import json
import threading
from pathlib import Path
from datetime import datetime
from typing import Callable, Optional, Set, List, Dict

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


# 已处理文件的记录文件
PROCESSED_LOG = "data/processed_files.json"


class PDFHandler(FileSystemEventHandler):
    """PDF文件事件处理器"""

    def __init__(self, callback: Callable, extensions: tuple = (".pdf",)):
        self.callback = callback
        self.extensions = extensions
        self._pending: Set[str] = set()  # 正在处理中的文件，避免重复触发

    def on_created(self, event):
        """文件创建事件"""
        if not event.is_directory and self._should_process(event.src_path):
            filepath = event.src_path
            if filepath not in self._pending:
                self._pending.add(filepath)
                # 延迟100ms确保文件写入完成
                threading.Timer(0.1, self._handle, args=[filepath]).start()

    def on_moved(self, event):
        """文件移动事件（某些程序写入文件的方式是先写临时文件再move）"""
        if not event.is_directory and self._should_process(event.dest_path):
            filepath = event.dest_path
            if filepath not in self._pending:
                self._pending.add(filepath)
                threading.Timer(0.1, self._handle, args=[filepath]).start()

    def _should_process(self, filepath: str) -> bool:
        """判断文件是否需要处理"""
        # 忽略临时文件
        basename = os.path.basename(filepath)
        if basename.startswith("~") or basename.startswith("."):
            return False
        # 只处理指定扩展名
        ext = os.path.splitext(filepath)[1].lower()
        return ext in self.extensions

    def _handle(self, filepath: str):
        """延迟处理文件"""
        try:
            time.sleep(0.3)  # 再等300ms确保文件完全写入
            self.callback(filepath)
        finally:
            self._pending.discard(filepath)


class FolderWatcher:
    """文件夹监听器"""

    def __init__(
        self,
        watch_folder: str,
        on_new_file: Callable,
        output_excel: Optional[str] = None,
        processed_log: str = PROCESSED_LOG,
    ):
        """
        Args:
            watch_folder: 要监听的文件夹路径
            on_new_file: 新文件回调函数，参数为文件路径，返回解析结果
            output_excel: 自动追加的Excel文件路径
            processed_log: 已处理文件记录
        """
        self.watch_folder = Path(watch_folder)
        self.on_new_file = on_new_file
        self.output_excel = output_excel
        self.processed_log = Path(processed_log)

        self.observer: Optional[Observer] = None
        self._running = False
        self._lock = threading.Lock()

        # 已处理的文件集合（用于去重）
        self.processed_files: Set[str] = self._load_processed()

        # 处理日志（最近的事件）
        self.event_log: List[Dict] = []

        # 确保文件夹存在
        self.watch_folder.mkdir(parents=True, exist_ok=True)
        self.processed_log.parent.mkdir(parents=True, exist_ok=True)

    def _load_processed(self) -> Set[str]:
        """加载已处理文件列表"""
        try:
            if self.processed_log.exists():
                data = json.loads(self.processed_log.read_text(encoding="utf-8"))
                return set(data.get("files", []))
        except Exception:
            pass
        return set()

    def _save_processed(self):
        """保存已处理文件列表"""
        data = {
            "files": list(self.processed_files),
            "last_updated": datetime.now().isoformat(),
        }
        self.processed_log.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _mark_processed(self, filepath: str):
        """标记文件为已处理"""
        # 使用绝对路径作为key，避免重复
        abs_path = str(Path(filepath).resolve())
        self.processed_files.add(abs_path)
        # 也记录文件名+大小，防止同一文件改名后重复处理
        try:
            stat = os.stat(filepath)
            name_key = f"{os.path.basename(filepath)}:{stat.st_size}"
            self.processed_files.add(name_key)
        except OSError:
            pass
        self._save_processed()

    def is_processed(self, filepath: str) -> bool:
        """检查文件是否已经处理过"""
        abs_path = str(Path(filepath).resolve())
        if abs_path in self.processed_files:
            return True
        try:
            stat = os.stat(filepath)
            name_key = f"{os.path.basename(filepath)}:{stat.st_size}"
            return name_key in self.processed_files
        except OSError:
            return False

    def add_log(self, level: str, message: str):
        """添加事件日志"""
        with self._lock:
            self.event_log.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "level": level,  # info, success, error
                "message": message,
            })
            # 只保留最近200条
            if len(self.event_log) > 200:
                self.event_log = self.event_log[-200:]

    def _handle_new_file(self, filepath: str):
        """处理新到达的PDF文件"""
        filename = os.path.basename(filepath)

        # 检查是否已处理
        if self.is_processed(filepath):
            return

        self.add_log("info", f"📄 检测到新文件: {filename}")

        try:
            # 调用回调函数处理
            result = self.on_new_file(filepath)

            if result and result.get("success"):
                order_count = result.get("order_count", 0)
                self.add_log(
                    "success",
                    f"✅ {filename} → 提取 {order_count} 个运单 [{result.get('method', '')}]",
                )
                self._mark_processed(filepath)
            else:
                error = result.get("error", "未知错误") if result else "解析返回空"
                self.add_log("error", f"❌ {filename} → {error}")

        except Exception as e:
            self.add_log("error", f"❌ {filename} → {str(e)}")

    def scan_existing(self):
        """扫描文件夹中已存在的PDF文件并处理"""
        if not self.watch_folder.exists():
            return

        pdf_files = sorted(self.watch_folder.glob("*.pdf"))
        new_count = 0
        for pdf_path in pdf_files:
            if not self.is_processed(str(pdf_path)):
                new_count += 1

        if new_count > 0:
            self.add_log("info", f"🔍 发现 {new_count} 个未处理的PDF文件，开始处理...")
            for pdf_path in pdf_files:
                if not self.is_processed(str(pdf_path)):
                    self._handle_new_file(str(pdf_path))
                    time.sleep(0.5)  # 短暂间隔避免资源争抢

    def start(self, scan_existing: bool = True):
        """启动监听"""
        if self._running:
            return

        self.add_log("info", f"👁️ 开始监听文件夹: {self.watch_folder}")

        # 先扫描已有文件
        if scan_existing:
            self.scan_existing()

        # 启动 watchdog observer
        event_handler = PDFHandler(callback=self._handle_new_file)
        self.observer = Observer()
        self.observer.schedule(event_handler, str(self.watch_folder), recursive=False)
        self.observer.start()
        self._running = True
        self.add_log("info", "✅ 监听已启动，等待新PDF...")

    def stop(self):
        """停止监听"""
        if not self._running:
            return

        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=3)
            self.observer = None

        self._running = False
        self.add_log("info", "⏸️ 监听已停止")

    @property
    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> Dict:
        """获取当前状态"""
        return {
            "running": self._running,
            "watch_folder": str(self.watch_folder),
            "processed_count": len(self.processed_files),
            "output_excel": self.output_excel,
        }
