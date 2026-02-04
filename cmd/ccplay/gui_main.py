import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import sys
import os
import yaml
from datetime import datetime
import queue
import time
import logging
import copy

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from ccplay_main import run_ccplay
from utils.utils import load_config

try:
    import pyi_splash
    pyi_splash.update_text('UI Loaded...')
    pyi_splash.close()
except (ImportError, RuntimeError):
    pass

# Default config if file doesn't exist
DEFAULT_CONFIG = {
    'emulator': {'serial': '127.0.0.1:7555'},
    'api': {
        'url': 'http://fees.5156xz.com/api/apk/localTask/apkUpdate',
        'share_url': 'http://fees.5156xz.com/api/pick/callback/appUrl'
    }
}

class TextRedirector:
    """Redirects stdout/logging to the UI log area"""
    def __init__(self, text_widget, tag="stdout"):
        self.text_widget = text_widget
        self.tag = tag
        self.queue = queue.Queue()
        
    def write(self, message):
        if message.strip():
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.queue.put(f"[{timestamp}] {message}")
    
    def flush(self):
        pass

class CCPlayGUIV2:
    def __init__(self, root):
        self.root = root
        self.root.title("CCPlay 自动化采集助手 v1.0")
        self.root.geometry("1000x750")
        self.root.configure(bg="#1e1e1e")
        
        self.is_running = False
        self.worker_thread = None
        
        # 基础路径：打包后优先读取 EXE 所在目录
        self.base_dir = self.get_base_path()
        self.config_file = os.path.join(self.base_dir, 'settings.yaml')
        self.log_dir = os.path.join(self.base_dir, 'logs')
        
        self.setup_styles()
        self.vars = {}
        self.current_config = self._load_current_settings()
        
        self.setup_ui()
        self.setup_redirector()
        self.update_log_display()

    def get_base_path(self):
        """获取基础目录（打包后为 EXE 所在目录）"""
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        else:
            return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TNotebook", background="#1e1e1e", borderwidth=0)
        style.configure("TNotebook.Tab", background="#2d2d2d", foreground="#e0e0e0", padding=[15, 5], font=("Microsoft YaHei UI", 10))
        style.map("TNotebook.Tab", background=[("selected", "#00a67e")], foreground=[("selected", "white")])
        style.configure("TFrame", background="#1e1e1e")
        style.configure("TLabelframe", background="#1e1e1e", foreground="#00d4ff")
        style.configure("TLabelframe.Label", background="#1e1e1e", foreground="#00d4ff", font=("Microsoft YaHei UI", 10, "bold"))

    def _load_current_settings(self):
        """从文件加载配置，并合并默认值"""
        config = copy.deepcopy(DEFAULT_CONFIG)
        
        # 调试信息：输出基础路径和配置文件路径
        print(f">>> 基础路径: {self.base_dir}")
        print(f">>> 尝试加载配置文件: {self.config_file}")

        if os.path.exists(self.config_file):
            try:
                # 调用 utils.load_config (全局)
                loaded = load_config(self.config_file)
                if loaded:
                    # 合并字典
                    for key, value in loaded.items():
                        if isinstance(value, dict) and key in config:
                            config[key].update(value)
                        else:
                            config[key] = value
                    print(">>> 配置文件加载成功")
            except Exception as e:
                print(f"加载配置文件失败: {e}")
        return config

    def _sync_config_to_file(self, config):
        """将当前配置字典同步到 settings.yaml 文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, sort_keys=False)
            print(">>> settings.yaml 已自动同步更新")
        except Exception as e:
            print(f">>> 自动同步配置文件失败: {e}")

    def get_default_min_date(self):
        """获取默认的起始日期（优先使用最新日志日期，无日志则用今天）"""
        today = datetime.now().strftime("%Y-%m-%d")
        if not os.path.exists(self.log_dir):
            return today
            
        try:
            log_files = [f for f in os.listdir(self.log_dir) if f.endswith('.log')]
            # 过滤出 YYYY-MM-DD.log 格式
            date_logs = [f for f in log_files if len(f) == 14 and f[4] == '-' and f[7] == '-']
            if date_logs:
                # 按名称排序获取最新的
                latest_log = sorted(date_logs)[-1]
                log_date = latest_log.replace('.log', '')
                return log_date
        except Exception as e:
            print(f"读取日志目录失败: {e}")
            
        return today

    def save_config_file(self):
        try:
            # Build partial config to overlay or overwrite
            # For simplicity in this bot, we manage emulator and api sections
            new_config = self.current_config.copy()
            new_config['emulator'] = {'serial': self.vars['serial'].get()}
            new_config['api'] = {'share_url': self.vars['share_url'].get()}
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                yaml.dump(new_config, f, allow_unicode=True, sort_keys=False)
            
            self.current_config = new_config
            print(">>> 配置文件已保存 到 settings.yaml")
            messagebox.showinfo("成功", "配置已保存")
            return True
        except Exception as e:
            messagebox.showerror("保存失败", f"无法保存配置: {e}")
            return False

    def setup_ui(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Tab 1: Monitor
        self.tab_monitor = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_monitor, text="  🖥️ 运行监控  ")
        self.setup_monitor_tab(self.tab_monitor)
        
        # Tab 2: Settings
        self.tab_settings = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_settings, text="  ⚙️ 参数设置  ")
        self.setup_settings_tab(self.tab_settings)

    def setup_monitor_tab(self, parent):
        title_frame = tk.Frame(parent, bg="#1e1e1e")
        title_frame.pack(fill=tk.X, pady=(15, 15))
        tk.Label(title_frame, text="📱 CCPlay 自动化采集助手", font=("Microsoft YaHei UI", 20, "bold"), fg="#00d4ff", bg="#1e1e1e").pack()

        control_frame = tk.Frame(parent, bg="#2d2d2d")
        control_frame.pack(fill=tk.X, padx=15, pady=5)
        
        status_frame = tk.Frame(control_frame, bg="#2d2d2d")
        status_frame.pack(side=tk.LEFT, padx=20, pady=15)
        tk.Label(status_frame, text="状态:", font=("Microsoft YaHei UI", 11), fg="#e0e0e0", bg="#2d2d2d").pack(side=tk.LEFT)
        self.status_label = tk.Label(status_frame, text="● 待机中", font=("Microsoft YaHei UI", 11, "bold"), fg="#808080", bg="#2d2d2d")
        self.status_label.pack(side=tk.LEFT, padx=5)

        btn_frame = tk.Frame(control_frame, bg="#2d2d2d")
        btn_frame.pack(side=tk.RIGHT, padx=20)
        
        self.start_btn = tk.Button(btn_frame, text="▶ 启动", font=("Microsoft YaHei UI", 11, "bold"), bg="#00a67e", fg="white", 
                                   border=0, padx=25, pady=8, command=self.start_process)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        
        self.stop_btn = tk.Button(btn_frame, text="■ 停止", font=("Microsoft YaHei UI", 11, "bold"), bg="#d32f2f", fg="white", 
                                  border=0, padx=25, pady=8, state=tk.DISABLED, command=self.stop_process)
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        
        tk.Button(btn_frame, text="🗑 清空日志", font=("Microsoft YaHei UI", 11), bg="#424242", fg="white", 
                  border=0, padx=15, pady=8, command=self.clear_log).pack(side=tk.LEFT, padx=5)

        log_frame = tk.Frame(parent, bg="#2d2d2d")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 15))
        tk.Label(log_frame, text="📋 运行日志", font=("Microsoft YaHei UI", 10, "bold"), fg="#e0e0e0", bg="#2d2d2d", anchor="w").pack(fill=tk.X, padx=10, pady=5)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, font=("Consolas", 10), bg="#1a1a1a", fg="#e0e0e0", relief=tk.FLAT, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.log_text.tag_config("info", foreground="#00d4ff")
        self.log_text.tag_config("success", foreground="#00e676")
        self.log_text.tag_config("error", foreground="#ff5252")
        self.log_text.tag_config("warning", foreground="#ffd600")

    def setup_settings_tab(self, parent):
        canvas = tk.Canvas(parent, bg="#1e1e1e", highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg="#1e1e1e")
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=20, pady=20)
        scrollbar.pack(side="right", fill="y")

        # Emulator
        group_emu = ttk.LabelFrame(scrollable_frame, text="模拟器配置", padding=10)
        group_emu.pack(fill=tk.X, pady=10)
        self.vars['serial'] = tk.StringVar(value=self.current_config.get('emulator', {}).get('serial', '127.0.0.1:7555'))
        self.create_labeled_entry(group_emu, "Serial/地址:", self.vars['serial'])

        # API
        group_api = ttk.LabelFrame(scrollable_frame, text="API 接口", padding=10)
        group_api.pack(fill=tk.X, pady=10)
        api_conf = self.current_config.get('api', {})
        self.vars['share_url'] = tk.StringVar(value=api_conf.get('share_url', ''))
        self.create_labeled_entry(group_api, "采集上报 URL:", self.vars['share_url'], width=50)

        save_btn = tk.Button(scrollable_frame, text="💾 保存配置", font=("Microsoft YaHei UI", 12, "bold"), 
                             bg="#0288d1", fg="white", padx=20, pady=10, border=0, cursor="hand2",
                             command=self.save_config_file)
        save_btn.pack(pady=20)

    def create_labeled_entry(self, parent, label_text, var, width=20):
        frame = tk.Frame(parent, bg="#1e1e1e")
        frame.pack(fill=tk.X, pady=5)
        tk.Label(frame, text=label_text, width=15, anchor="e", fg="#e0e0e0", bg="#1e1e1e").pack(side=tk.LEFT, padx=(0, 10))
        entry = tk.Entry(frame, textvariable=var, width=width, bg="#333333", fg="white", insertbackground="white")
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        return entry

    def setup_redirector(self):
        self.redirector = TextRedirector(self.log_text)
        # Handle both stdout and logging
        sys.stdout = self.redirector
        sys.stderr = self.redirector
        
        # Capture logging as well
        class LogHandler(logging.Handler):
            def __init__(self, redirector):
                super().__init__()
                self.redirector = redirector
            def emit(self, record):
                msg = self.format(record)
                self.redirector.write(msg)
        
        handler = LogHandler(self.redirector)
        handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))
        logging.getLogger().addHandler(handler)

    def update_log_display(self):
        try:
            while True:
                message = self.redirector.queue.get_nowait()
                self.append_log(message)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.update_log_display)
    
    def append_log(self, message):
        self.log_text.configure(state=tk.NORMAL)
        tag = "info"
        if "【成功】" in message or "完成" in message: tag = "success"
        elif "失败" in message or "错误" in message: tag = "error"
        elif "警告" in message or "等待" in message: tag = "warning"
        
        self.log_text.insert(tk.END, message + "\n", tag)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def clear_log(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def start_process(self):
        if self.is_running: return
        self.is_running = True
        self.start_btn.configure(state=tk.DISABLED, bg="#606060")
        self.stop_btn.configure(state=tk.NORMAL, bg="#d32f2f")
        self.status_label.configure(text="● 运行中", fg="#00e676")
        
        print("=== 正在启动 CCPlay 采集任务 ===")
        self.worker_thread = threading.Thread(
            target=self.run_worker,
            daemon=True
        )
        self.worker_thread.start()
    
    def stop_process(self):
        if not self.is_running: return
        self.is_running = False
        self.start_btn.configure(state=tk.NORMAL, bg="#00a67e")
        self.stop_btn.configure(state=tk.DISABLED, bg="#606060")
        self.status_label.configure(text="● 已停止", fg="#ff5252")
        print("=== 正在停止任务... ===")
    
    def run_worker(self):
        try:
            run_ccplay(stop_func=lambda: not self.is_running)
        except Exception as e:
            print(f"核心运行错误: {str(e)}")
        finally:
            self.root.after(0, self.stop_process)

if __name__ == "__main__":
    root = tk.Tk()
    gui = CCPlayGUIV2(root)
    root.mainloop()
