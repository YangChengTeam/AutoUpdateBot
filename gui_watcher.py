import tkinter as tk
from tkinter import scrolledtext, ttk
import threading
import subprocess
import os
import sys
import queue

try:
    import pyi_splash
    pyi_splash.update_text('UI Loaded...')
    pyi_splash.close()
except (ImportError, RuntimeError):
    pass

class WatcherGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("AutoUpdateBot - 服务管理器")
        self.root.geometry("900x600")
        
        # 进程管理
        self.processes = {
            "Watcher": {"cmd": [sys.executable, "cmd/watcher/main.py"], "proc": None, "thread": None},
            "API": {"cmd": [sys.executable, "api/main.py"], "proc": None, "thread": None}
        }
        
        self.log_queue = queue.Queue()
        self.setup_ui()
        self.root.after(100, self.update_logs)

    def setup_ui(self):
        # 顶部控制栏
        control_frame = ttk.Frame(self.root, padding="10")
        control_frame.pack(fill=tk.X)

        for name, info in self.processes.items():
            btn_frame = ttk.LabelFrame(control_frame, text=name, padding="5")
            btn_frame.pack(side=tk.LEFT, padx=10)
            
            start_btn = ttk.Button(btn_frame, text=f"启动 {name}", 
                                  command=lambda n=name: self.start_service(n))
            start_btn.pack(side=tk.LEFT, padx=2)
            info["start_btn"] = start_btn
            
            stop_btn = ttk.Button(btn_frame, text=f"停止 {name}", 
                                 command=lambda n=name: self.stop_service(n), state=tk.DISABLED)
            stop_btn.pack(side=tk.LEFT, padx=2)
            info["stop_btn"] = stop_btn

        # 日志显示区
        log_frame = ttk.LabelFrame(self.root, text="实时日志", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.log_area = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, state=tk.DISABLED, 
                                                font=("Consolas", 10), bg="#1e1e1e", fg="#d4d4d4")
        self.log_area.pack(fill=tk.BOTH, expand=True)
        
        # 标签颜色配置
        self.log_area.tag_config("INFO", foreground="#4ec9b0")
        self.log_area.tag_config("ERROR", foreground="#f44747")
        self.log_area.tag_config("WARNING", foreground="#dcdcaa")
        self.log_area.tag_config("SYSTEM", foreground="#569cd6")

    def log(self, message, level="INFO"):
        self.log_queue.put((message, level))

    def update_logs(self):
        try:
            while True:
                msg, level = self.log_queue.get_nowait()
                self.log_area.config(state=tk.NORMAL)
                
                # 根据内容自动判断级别（如果是进程输出）
                if "[INFO]" in msg: level = "INFO"
                elif "[ERROR]" in msg: level = "ERROR"
                elif "[WARNING]" in msg: level = "WARNING"
                
                self.log_area.insert(tk.END, msg + "\n", level)
                self.log_area.see(tk.END)
                self.log_area.config(state=tk.DISABLED)
        except queue.Empty:
            pass
        self.root.after(100, self.update_logs)

    def start_service(self, name):
        if self.processes[name]["proc"]:
            return

        info = self.processes[name]
        info["start_btn"].config(state=tk.DISABLED)
        info["stop_btn"].config(state=tk.NORMAL)
        
        self.log(f"正在启动 {name} 服务...", "SYSTEM")
        
        # 启动进程
        try:
            env = os.environ.copy()
            # 确保当前目录在 PYTHONPATH
            env["PYTHONPATH"] = os.getcwd()
            
            proc = subprocess.Popen(
                info["cmd"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                universal_newlines=True,
                env=env,
                cwd=os.getcwd()
            )
            info["proc"] = proc
            
            # 启动日志读取线程
            thread = threading.Thread(target=self.read_output, args=(name, proc), daemon=True)
            thread.start()
            info["thread"] = thread
            
        except Exception as e:
            self.log(f"启动 {name} 失败: {str(e)}", "ERROR")
            self.stop_service(name)

    def read_output(self, name, proc):
        for line in iter(proc.stdout.readline, ""):
            if line:
                self.log(f"[{name}] {line.strip()}")
        
        proc.stdout.close()
        return_code = proc.wait()
        self.log(f"{name} 服务已退出 (退出码: {return_code})", "SYSTEM")
        self.root.after(0, lambda: self.reset_ui(name))

    def stop_service(self, name):
        info = self.processes[name]
        if info["proc"]:
            self.log(f"正在停止 {name} 服务...", "SYSTEM")
            # Windows 下的安全终止
            subprocess.call(['taskkill', '/F', '/T', '/PID', str(info["proc"].pid)])
            info["proc"] = None
        self.reset_ui(name)

    def reset_ui(self, name):
        info = self.processes[name]
        info["start_btn"].config(state=tk.NORMAL)
        info["stop_btn"].config(state=tk.DISABLED)
        info["proc"] = None

if __name__ == "__main__":
    root = tk.Tk()
    gui = WatcherGUI(root)
    
    # 退出时清理进程
    def on_closing():
        for name in gui.processes:
            gui.stop_service(name)
        root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
