import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import sys
import os
import yaml 
from datetime import datetime
import queue
import time
from main import core, get_third_party_apps, init, set_config

try:
    import pyi_splash
    pyi_splash.update_text('UI Loaded...')
    pyi_splash.close()
except (ImportError, RuntimeError):
    pass

# 默认配置，防止文件不存在时报错
DEFAULT_CONFIG = {
    'emulator': {'serial': '127.0.0.1:7555'},
    'detection': {
        'timeout': 60,
        'click_wait': 5,
        'skip_keywords': ["完成", "关闭", "取消", "同意", "知道了", "关闭应用", "去开启", "下一步", "确定", "允许"],
        'download_keywords': ["立即升级", "继续安装", "立即更新", "立即安装", "去更新", "下载更新", "更新"],
        'update_keywords': ["更新"]
    },
    'filter_packages': [],  # 新增：过滤包名列表
    'istest': 1,
    'loop_enabled': True,
    'loop_interval': 300,
    'sftp': {
        'host': '192.168.80.151', 'port': 22, 'user': 'root', 'password': 'yangfei@123', 'remote_dir': '/home/down/emulator'
    },
    'redis': {
        'host': 'localhost', 'port': 6379, 'db': 0
    },
    'api': {'url': "http://fees.5156xz.com/api/apk/localTask/apkUpdate"}
}

class TextRedirector:
    """将print输出重定向到UI的日志区域"""
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

class ApkUpdaterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("APK 自动化更新机器人 v2.0")
        self.root.geometry("1000x750")
        self.root.configure(bg="#1e1e1e")
        
        # 运行状态
        self.is_running = False
        self.worker_thread = None
        self.config_file = "settings.yaml"
        
        # 样式设置
        self.setup_styles()
        
        # 变量存储字典
        self.vars = {}
        
        # 加载配置
        self.current_config = self.load_config()
        
        # 初始化界面
        self.setup_ui()
        self.setup_redirector()
        self.update_log_display()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        
        # 配置 Notebook 样式
        style.configure("TNotebook", background="#1e1e1e", borderwidth=0)
        style.configure("TNotebook.Tab", background="#2d2d2d", foreground="#e0e0e0", padding=[15, 5], font=("Microsoft YaHei UI", 10))
        style.map("TNotebook.Tab", background=[("selected", "#00a67e")], foreground=[("selected", "white")])
        
        # 配置 Frame
        style.configure("TFrame", background="#1e1e1e")
        
        # 配置 LabelFrame
        style.configure("TLabelframe", background="#1e1e1e", foreground="#00d4ff")
        style.configure("TLabelframe.Label", background="#1e1e1e", foreground="#00d4ff", font=("Microsoft YaHei UI", 10, "bold"))

    def load_config(self):
        """加载YAML配置"""
        if not os.path.exists(self.config_file):
            return DEFAULT_CONFIG
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or DEFAULT_CONFIG
                # 确保新字段存在
                if 'filter_packages' not in config:
                    config['filter_packages'] = []
                return config
        except Exception as e:
            messagebox.showerror("配置错误", f"加载配置文件失败: {e}")
            return DEFAULT_CONFIG

    def save_config_file(self):
        """从UI变量收集数据并保存到YAML"""
        try:
            # 构建配置字典
            new_config = {
                'emulator': {'serial': self.vars['serial'].get()},
                'detection': {
                    'timeout': int(self.vars['timeout'].get()),
                    'click_wait': int(self.vars['click_wait'].get()),
                    # 从文本框中获取，按换行符分割
                    'skip_keywords': [x.strip() for x in self.vars['skip_keywords'].get('1.0', tk.END).strip().split('\n') if x.strip()],
                    'download_keywords': [x.strip() for x in self.vars['download_keywords'].get('1.0', tk.END).strip().split('\n') if x.strip()],
                    'update_keywords': [x.strip() for x in self.vars['update_keywords'].get('1.0', tk.END).strip().split('\n') if x.strip()],
                },
                'filter_packages': [x.strip() for x in self.vars['filter_packages'].get('1.0', tk.END).strip().split('\n') if x.strip()],
                'istest': self.vars['istest'].get(),
                'loop_enabled': self.vars['loop_enabled'].get(),
                'loop_interval': int(self.vars['loop_interval'].get()),
                'sftp': {
                    'host': self.vars['sftp_host'].get(),
                    'port': int(self.vars['sftp_port'].get()),
                    'user': self.vars['sftp_user'].get(),
                    'password': self.vars['sftp_pass'].get(),
                    'remote_dir': self.vars['sftp_dir'].get(),
                    'remote_screenshots_dir': self.vars['sftp_screenhots_dir'].get(),
                },
                'redis': {
                    'host': self.vars['redis_host'].get(),
                    'port': int(self.vars['redis_port'].get()),
                    'db': int(self.vars['redis_db'].get()),
                },
                'api': {
                    'url': self.vars['api_url'].get()
                }
            }
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                yaml.dump(new_config, f, allow_unicode=True, sort_keys=False)
            
            # 同步更新 watcher.yaml 中的 redis 配置
            watcher_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'watcher.yaml')
            if os.path.exists(watcher_path):
                try:
                    with open(watcher_path, 'r', encoding='utf-8') as f:
                        watcher_cfg = yaml.safe_load(f) or {}
                    
                    if 'redis' not in watcher_cfg:
                        watcher_cfg['redis'] = {}
                    
                    watcher_cfg['redis'].update(new_config['redis'])
                    
                    with open(watcher_path, 'w', encoding='utf-8') as f:
                        yaml.dump(watcher_cfg, f, allow_unicode=True, sort_keys=False)
                    print(">>> watcher.yaml 中的 Redis 配置已同步更新")
                except Exception as e:
                    print(f">>> 同步更新 watcher.yaml 失败: {e}")

            set_config(new_config)
            self.current_config = new_config
            print(">>> 配置文件已保存！")
            messagebox.showinfo("成功", "配置已保存到 settings.yaml")
            return True
        except Exception as e:
            messagebox.showerror("保存失败", f"无法保存配置: {e}")
            return False

    def setup_ui(self):
        # 主容器 - Notebook 分页
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # tab 1: 运行监控
        self.tab_monitor = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_monitor, text="  🖥️ 运行监控  ")
        self.setup_monitor_tab(self.tab_monitor)
        
        # tab 2: 参数设置
        self.tab_settings = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_settings, text="  ⚙️ 参数设置  ")
        self.setup_settings_tab(self.tab_settings)
        
        # tab 3: 应用管理
        self.tab_apps = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_apps, text="  📱 应用管理  ")
        self.setup_apps_tab(self.tab_apps)

    def setup_monitor_tab(self, parent):
        """设置监控页面（原有的界面逻辑）"""
        # 标题栏
        title_frame = tk.Frame(parent, bg="#1e1e1e")
        title_frame.pack(fill=tk.X, pady=(15, 15))
        
        tk.Label(title_frame, text="📱 APK 自动化更新机器人", font=("Microsoft YaHei UI", 20, "bold"), fg="#00d4ff", bg="#1e1e1e").pack()

        # 控制面板
        control_frame = tk.Frame(parent, bg="#2d2d2d")
        control_frame.pack(fill=tk.X, padx=15, pady=5)
        
        # 状态
        status_frame = tk.Frame(control_frame, bg="#2d2d2d")
        status_frame.pack(side=tk.LEFT, padx=20, pady=15)
        tk.Label(status_frame, text="状态:", font=("Microsoft YaHei UI", 11), fg="#e0e0e0", bg="#2d2d2d").pack(side=tk.LEFT)
        self.status_label = tk.Label(status_frame, text="● 待机中", font=("Microsoft YaHei UI", 11, "bold"), fg="#808080", bg="#2d2d2d")
        self.status_label.pack(side=tk.LEFT, padx=5)

        # 按钮
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

        # 快捷信息显示（只读）
        info_frame = tk.Frame(parent, bg="#1e1e1e")
        info_frame.pack(fill=tk.X, padx=15, pady=10)
        
        # 使用绑定的变量，这样在设置页修改后，这里也会变
        self.vars['loop_enabled'] = tk.BooleanVar(value=self.current_config.get('loop_enabled', True))
        self.vars['loop_interval'] = tk.IntVar(value=self.current_config.get('loop_interval', 300))
        self.vars['istest'] = tk.IntVar(value=self.current_config.get('istest', 1)) 

        # 简单显示当前配置摘要
        tk.Label(info_frame, text="当前配置摘要:", fg="#00d4ff", bg="#1e1e1e", font=("Microsoft YaHei UI", 10)).pack(anchor="w")
        summary_frame = tk.Frame(info_frame, bg="#1e1e1e")
        summary_frame.pack(anchor="w", pady=5)
        
        self.lbl_interval = tk.Label(summary_frame, text="", fg="#aaaaaa", bg="#1e1e1e")
        self.lbl_interval.pack(side=tk.LEFT)
        self.update_summary_label() # 初始化显示

        # 日志区域
        log_frame = tk.Frame(parent, bg="#2d2d2d")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 15))
        
        tk.Label(log_frame, text="📋 运行日志", font=("Microsoft YaHei UI", 10, "bold"), fg="#e0e0e0", bg="#2d2d2d", anchor="w").pack(fill=tk.X, padx=10, pady=5)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, font=("Consolas", 10), bg="#1a1a1a", fg="#e0e0e0", relief=tk.FLAT, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 日志颜色配置
        self.log_text.tag_config("info", foreground="#00d4ff")
        self.log_text.tag_config("success", foreground="#00e676")
        self.log_text.tag_config("error", foreground="#ff5252")
        self.log_text.tag_config("warning", foreground="#ffd600")

    def update_summary_label(self, *args):
        # 1. 获取循环状态
        loop_state = "开启" if self.vars['loop_enabled'].get() else "关闭"
        
        # 2. 获取间隔
        interval = self.vars['loop_interval'].get()
        
        is_test_val = self.vars['istest'].get()

        is_test_str = '是' if is_test_val else '否'

        # 更新标签文字
        self.lbl_interval.config(text=f"循环: {loop_state} | 间隔: {interval}秒 | 测试模式: {is_test_str}")

    def create_labeled_entry(self, parent, label_text, var, width=20, is_password=False):
        """辅助函数：创建标签和输入框"""
        frame = tk.Frame(parent, bg="#1e1e1e")
        frame.pack(fill=tk.X, pady=5)
        tk.Label(frame, text=label_text, width=15, anchor="e", fg="#e0e0e0", bg="#1e1e1e").pack(side=tk.LEFT, padx=(0, 10))
        entry = tk.Entry(frame, textvariable=var, width=width, bg="#333333", fg="white", insertbackground="white", show="*" if is_password else "")
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        return entry

    def create_labeled_textbox(self, parent, label_text, height=6):
        """辅助函数：创建标签和多行文本框"""
        frame = tk.Frame(parent, bg="#1e1e1e")
        frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # 标签在顶部
        tk.Label(frame, text=label_text, anchor="w", fg="#e0e0e0", bg="#1e1e1e", font=("Microsoft YaHei UI", 9, "bold")).pack(fill=tk.X, pady=(0, 5))
        
        # 文本框
        text_widget = tk.Text(frame, height=height, bg="#333333", fg="white", insertbackground="white", 
                              font=("Consolas", 10), wrap=tk.WORD, relief=tk.FLAT, padx=5, pady=5)
        
        # 添加滚动条
        scrollbar = tk.Scrollbar(frame, command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        return text_widget

    def setup_settings_tab(self, parent):
        """设置配置页面"""
        # 创建可滚动的 Canvas (防止设置项太多屏幕放不下)
        canvas = tk.Canvas(parent, bg="#1e1e1e", highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg="#1e1e1e")

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, padx=20, pady=20)
        scrollbar.pack(side="right", fill="y")

        # === 1. 通用设置 ===
        group_gen = ttk.LabelFrame(scrollable_frame, text="通用设置", padding=10)
        group_gen.pack(fill=tk.X, pady=10)

        # Is Test
        self.vars['istest'] = tk.IntVar(value=self.current_config.get('istest', 1))
        tk.Checkbutton(group_gen, text="开启测试模式 (isTest)", variable=self.vars['istest'], 
                       bg="#1e1e1e", fg="#e0e0e0", selectcolor="#2d2d2d", activebackground="#1e1e1e").pack(anchor="w")

        # Loop Enabled (复用 setup_monitor_tab 中创建的变量)
        tk.Checkbutton(group_gen, text="启用循环检测", variable=self.vars['loop_enabled'], command=self.update_summary_label,
                       bg="#1e1e1e", fg="#e0e0e0", selectcolor="#2d2d2d", activebackground="#1e1e1e").pack(anchor="w", pady=5)

        # Loop Interval
        self.vars['istest'].trace("w", self.update_summary_label)

        self.vars['loop_interval'].trace("w", self.update_summary_label) # 监听变化
        self.create_labeled_entry(group_gen, "循环间隔(秒):", self.vars['loop_interval'])

        # === 2. 模拟器设置 ===
        group_emu = ttk.LabelFrame(scrollable_frame, text="模拟器配置", padding=10)
        group_emu.pack(fill=tk.X, pady=10)
        
        self.vars['serial'] = tk.StringVar(value=self.current_config['emulator'].get('serial', ''))
        self.create_labeled_entry(group_emu, "Serial/地址:", self.vars['serial'])

        # === 3. 包名过滤 ===
        group_filter = ttk.LabelFrame(scrollable_frame, text="包名过滤", padding=10)
        group_filter.pack(fill=tk.BOTH, expand=True, pady=10)
        
        tk.Label(group_filter, text="需要过滤的包名 (每行一个)", fg="#aaaaaa", bg="#1e1e1e", 
                font=("Microsoft YaHei UI", 8)).pack(anchor="w")
        
        filter_packages = self.current_config.get('filter_packages', [])
        self.vars['filter_packages'] = self.create_labeled_textbox(group_filter, "📦 过滤包名列表:", height=5)
        self.vars['filter_packages'].insert('1.0', '\n'.join(filter_packages))

        # === 4. 检测参数 ===
        group_det = ttk.LabelFrame(scrollable_frame, text="检测参数", padding=10)
        group_det.pack(fill=tk.BOTH, expand=True, pady=10)
        
        det_conf = self.current_config.get('detection', {})
        self.vars['timeout'] = tk.IntVar(value=det_conf.get('timeout', 60))
        self.vars['click_wait'] = tk.IntVar(value=det_conf.get('click_wait', 5))
        
        self.create_labeled_entry(group_det, "超时时间(秒):", self.vars['timeout'])
        self.create_labeled_entry(group_det, "点击等待(秒):", self.vars['click_wait'])
        
        # 关键字列表 - 使用大文本框
        tk.Label(group_det, text="关键字配置 (每行一个关键字)", fg="#aaaaaa", bg="#1e1e1e", 
                font=("Microsoft YaHei UI", 8)).pack(anchor="w", pady=(10, 0))
        
        # 跳过关键字
        skip_kw = det_conf.get('skip_keywords', [])
        self.vars['skip_keywords'] = self.create_labeled_textbox(group_det, "⏭️ 跳过关键字:", height=5)
        self.vars['skip_keywords'].insert('1.0', '\n'.join(skip_kw))
        
        # 下载关键字
        download_kw = det_conf.get('download_keywords', [])
        self.vars['download_keywords'] = self.create_labeled_textbox(group_det, "⬇️ 下载关键字:", height=4)
        self.vars['download_keywords'].insert('1.0', '\n'.join(download_kw))
        
        # 更新关键字
        update_kw = det_conf.get('update_keywords', [])
        self.vars['update_keywords'] = self.create_labeled_textbox(group_det, "🔄 更新关键字:", height=3)
        self.vars['update_keywords'].insert('1.0', '\n'.join(update_kw))

        # === 5. SFTP 设置 ===
        group_sftp = ttk.LabelFrame(scrollable_frame, text="SFTP 服务器", padding=10)
        group_sftp.pack(fill=tk.X, pady=10)
        
        sftp_conf = self.current_config.get('sftp', {})
        self.vars['sftp_host'] = tk.StringVar(value=sftp_conf.get('host', ''))
        self.vars['sftp_port'] = tk.IntVar(value=sftp_conf.get('port', 22))
        self.vars['sftp_user'] = tk.StringVar(value=sftp_conf.get('user', 'root'))
        self.vars['sftp_pass'] = tk.StringVar(value=sftp_conf.get('password', ''))
        self.vars['sftp_dir'] = tk.StringVar(value=sftp_conf.get('remote_dir', '/'))
        self.vars['sftp_screenhots_dir'] = tk.StringVar(value=sftp_conf.get('remote_screenshots_dir', '/'))
        
        self.create_labeled_entry(group_sftp, "主机 IP:", self.vars['sftp_host'])
        self.create_labeled_entry(group_sftp, "端口:", self.vars['sftp_port'])
        self.create_labeled_entry(group_sftp, "用户名:", self.vars['sftp_user'])
        self.create_labeled_entry(group_sftp, "密码:", self.vars['sftp_pass'], is_password=True)
        self.create_labeled_entry(group_sftp, "远程目录:", self.vars['sftp_dir'])
        self.create_labeled_entry(group_sftp, "远程截图目录:", self.vars['sftp_screenhots_dir'])

        # === 6. Redis 设置 ===
        group_redis = ttk.LabelFrame(scrollable_frame, text="Redis 配置", padding=10)
        group_redis.pack(fill=tk.X, pady=10)
        
        redis_conf = self.current_config.get('redis', {'host': 'localhost', 'port': 6379, 'db': 0})
        self.vars['redis_host'] = tk.StringVar(value=redis_conf.get('host', 'localhost'))
        self.vars['redis_port'] = tk.IntVar(value=redis_conf.get('port', 6379))
        self.vars['redis_db'] = tk.IntVar(value=redis_conf.get('db', 0))
        
        self.create_labeled_entry(group_redis, "Redis 主机:", self.vars['redis_host'])
        self.create_labeled_entry(group_redis, "Redis 端口:", self.vars['redis_port'])
        self.create_labeled_entry(group_redis, "Redis 数据库:", self.vars['redis_db'])

        # === 7. API 设置 ===
        group_api = ttk.LabelFrame(scrollable_frame, text="API 接口", padding=10)
        group_api.pack(fill=tk.X, pady=10)
        
        self.vars['api_url'] = tk.StringVar(value=self.current_config.get('api', {}).get('url', ''))
        self.create_labeled_entry(group_api, "回调 URL:", self.vars['api_url'], width=40)

        # === 底部保存按钮 ===
        save_btn = tk.Button(scrollable_frame, text="💾 保存配置", font=("Microsoft YaHei UI", 12, "bold"), 
                             bg="#0288d1", fg="white", padx=20, pady=10, border=0, cursor="hand2",
                             command=self.save_config_file)
        save_btn.pack(pady=20)

    def setup_apps_tab(self, parent):
        """设置应用管理页面"""
        # 顶部标题和操作栏
        header_frame = tk.Frame(parent, bg="#1e1e1e")
        header_frame.pack(fill=tk.X, padx=15, pady=(15, 10))
        
        tk.Label(header_frame, text="📱 第三方应用管理", font=("Microsoft YaHei UI", 16, "bold"), 
                fg="#00d4ff", bg="#1e1e1e").pack(side=tk.LEFT)
        
        # 操作按钮
        btn_container = tk.Frame(header_frame, bg="#1e1e1e")
        btn_container.pack(side=tk.RIGHT)
        
        tk.Button(btn_container, text="🔄 刷新列表", font=("Microsoft YaHei UI", 10, "bold"), 
                 bg="#00a67e", fg="white", border=0, padx=20, pady=6, cursor="hand2",
                 command=self.refresh_app_list).pack(side=tk.LEFT, padx=5)
        
        tk.Button(btn_container, text="▶️ 更新测试", font=("Microsoft YaHei UI", 10), 
                 bg="#0288d1", fg="white", border=0, padx=20, pady=6, cursor="hand2",
                 command=self.launch_selected_app).pack(side=tk.LEFT, padx=5)
        
        tk.Button(btn_container, text="🗑️ 卸载应用", font=("Microsoft YaHei UI", 10), 
                 bg="#d32f2f", fg="white", border=0, padx=20, pady=6, cursor="hand2",
                 command=self.uninstall_selected_app).pack(side=tk.LEFT, padx=5)
        
        # 搜索框
        search_frame = tk.Frame(parent, bg="#1e1e1e")
        search_frame.pack(fill=tk.X, padx=15, pady=5)
        
        tk.Label(search_frame, text="🔍 搜索:", fg="#e0e0e0", bg="#1e1e1e", 
                font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(0, 10))
        
        self.search_var = tk.StringVar()
        self.search_var.trace("w", lambda *args: self.filter_app_list())
        search_entry = tk.Entry(search_frame, textvariable=self.search_var, 
                               bg="#333333", fg="white", insertbackground="white", 
                               font=("Microsoft YaHei UI", 10), width=40)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # 应用列表区域
        list_frame = tk.Frame(parent, bg="#2d2d2d")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(10, 15))
        
        # 创建 Treeview 表格
        columns = ("package", "version", "code")
        self.app_tree = ttk.Treeview(list_frame, columns=columns, show="tree headings", height=20)
        
        # 定义列
        self.app_tree.heading("#0", text="序号")
        self.app_tree.heading("package", text="包名")
        self.app_tree.heading("version", text="版本名称")
        self.app_tree.heading("code", text="版本号")
        
        # 设置列宽
        self.app_tree.column("#0", width=60, anchor="center")
        self.app_tree.column("package", width=300, anchor="w")
        self.app_tree.column("version", width=200, anchor="w")
        self.app_tree.column("code", width=100, anchor="center")
        
        # 配置样式
        style = ttk.Style()
        style.configure("Treeview", 
                       background="#1a1a1a", 
                       foreground="#e0e0e0", 
                       fieldbackground="#1a1a1a",
                       borderwidth=0)
        style.configure("Treeview.Heading", 
                       background="#2d2d2d", 
                       foreground="#00d4ff", 
                       font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Treeview", background=[("selected", "#00a67e")])
        
        # 滚动条
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.app_tree.yview)
        hsb = ttk.Scrollbar(list_frame, orient="horizontal", command=self.app_tree.xview)
        self.app_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        
        # 布局
        self.app_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)
        
        # 状态栏
        status_frame = tk.Frame(parent, bg="#2d2d2d")
        status_frame.pack(fill=tk.X, padx=15, pady=(0, 10))
        
        self.app_status_label = tk.Label(status_frame, text="就绪", 
                                         font=("Microsoft YaHei UI", 9), 
                                         fg="#aaaaaa", bg="#2d2d2d", anchor="w")
        self.app_status_label.pack(side=tk.LEFT, padx=10, pady=5)
        
        self.app_count_label = tk.Label(status_frame, text="应用数: 0", 
                                        font=("Microsoft YaHei UI", 9), 
                                        fg="#aaaaaa", bg="#2d2d2d", anchor="e")
        self.app_count_label.pack(side=tk.RIGHT, padx=10, pady=5)
        
        # 存储原始应用列表
        self.all_apps = []
        
        # 双击事件 - 启动应用
        self.app_tree.bind("<Double-1>", lambda e: self.launch_selected_app())
    
    def refresh_app_list(self):
        """刷新应用列表"""
        try:
            self.app_status_label.config(text="正在获取应用列表...", fg="#ffd600")
            self.root.update()
            
            # 从 main.py 获取第三方应用
            apps = get_third_party_apps()
            
            if apps is None:
                self.app_status_label.config(text="获取失败：无法连接模拟器", fg="#ff5252")
                messagebox.showerror("错误", "无法连接到模拟器，请检查模拟器是否启动")
                return
            
            # 清空现有列表
            for item in self.app_tree.get_children():
                self.app_tree.delete(item)
            
            # 存储原始数据
            self.all_apps = apps
            
            # 添加到列表
            for idx, app in enumerate(apps, 1):
                package = app.get('package', 'N/A')
                name = app.get('version', 'Unknown')
                version = app.get('code', 'N/A')
                
                self.app_tree.insert("", tk.END, text=str(idx), 
                                    values=(package, name, version))
            
            # 更新状态
            self.app_count_label.config(text=f"应用数: {len(apps)}")
            self.app_status_label.config(text=f"刷新成功，共 {len(apps)} 个应用", fg="#00e676")
            
        except Exception as e:
            self.app_status_label.config(text=f"刷新失败：{str(e)}", fg="#ff5252")
            messagebox.showerror("错误", f"刷新应用列表失败：{str(e)}")
    
    def filter_app_list(self):
        """根据搜索框过滤应用列表"""
        search_text = self.search_var.get().lower()
        
        # 清空现有显示
        for item in self.app_tree.get_children():
            self.app_tree.delete(item)
        
        # 过滤并重新添加
        filtered_count = 0
        for idx, app in enumerate(self.all_apps, 1):
            package = app.get('package', '').lower()
            name = app.get('name', '').lower()
            
            if search_text in package or search_text in name:
                self.app_tree.insert("", tk.END, text=str(idx), 
                                    values=(app.get('package', 'N/A'), 
                                           app.get('name', 'Unknown'), 
                                           app.get('version', 'N/A')))
                filtered_count += 1
        
        self.app_count_label.config(text=f"显示: {filtered_count} / {len(self.all_apps)}")
    
    def get_selected_app(self):
        """获取选中的应用"""
        selection = self.app_tree.selection()
        if not selection:
            return None
        
        item = selection[0]
        values = self.app_tree.item(item, "values")
        
        if values:
            return {
                'package': values[0],
                'name': values[1],
                'version': values[2]
            }
        return None
    
    def launch_selected_app(self):
        """启动选中的应用"""
        app = self.get_selected_app()
        if not app:
            messagebox.showwarning("警告", "请先选择一个应用")
            return
        
        try:
            self.stop_process()
            self.start_process(app['package'])
        except Exception as e:
            self.app_status_label.config(text=f"更新检测失败：{str(e)}", fg="#ff5252")
            messagebox.showerror("错误", f"更新检测失败：{str(e)}")
    
    def uninstall_selected_app(self):
        """卸载选中的应用"""
        app = self.get_selected_app()
        if not app:
            messagebox.showwarning("警告", "请先选择一个应用")
            return
        
        # 二次确认
        confirm = messagebox.askyesno(
            "确认卸载", 
            f"确定要卸载以下应用吗？\n\n包名: {app['package']}\n版本: {app['version']}\n\n卸载后将自动添加到过滤包名列表"
        )
        
        if not confirm:
            return
        
        try:
            import subprocess
            package = app['package']
            serial = self.vars['serial'].get()
            
            self.app_status_label.config(text=f"正在卸载 {app['name']}...", fg="#ffd600")
            self.root.update()
            
            # 使用 adb 卸载应用
            cmd = f"adb -s {serial} uninstall {package}"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode == 0 and "Success" in result.stdout:
                self.app_status_label.config(text=f"已卸载: {app['name']}", fg="#00e676")
                print(f">>> 已卸载应用: {app['name']} ({package})")
                
                # 添加到过滤包名列表
                current_filters = self.vars['filter_packages'].get('1.0', tk.END).strip()
                filter_list = [x.strip() for x in current_filters.split('\n') if x.strip()]
                
                # 如果包名不在列表中，则添加
                if package not in filter_list:
                    filter_list.append(package)
                    
                    # 更新文本框
                    self.vars['filter_packages'].delete('1.0', tk.END)
                    self.vars['filter_packages'].insert('1.0', '\n'.join(filter_list))
                    
                    # 保存到配置文件
                    if self.save_config_file():
                        print(f">>> 已将 {package} 添加到过滤列表")
                
                # 刷新列表
                self.refresh_app_list()
            else:
                raise Exception(result.stderr or result.stdout or "卸载失败")
                
        except Exception as e:
            self.app_status_label.config(text=f"卸载失败：{str(e)}", fg="#ff5252")
            messagebox.showerror("错误", f"卸载应用失败：{str(e)}")

    def setup_redirector(self):
        self.redirector = TextRedirector(self.log_text)
        sys.stdout = self.redirector
        sys.stderr = self.redirector
        
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
        if "成功" in message or "完成" in message: tag = "success"
        elif "失败" in message or "错误" in message: tag = "error"
        elif "警告" in message or "等待" in message: tag = "warning"
        
        self.log_text.insert(tk.END, message + "\n", tag)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def clear_log(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def start_process(self, app = None):
        if self.is_running: return
        
        # 启动前从UI获取当前配置
        current_ui_config = {
             'emulator': {'serial': self.vars['serial'].get()},
             'detection': {
                 'timeout': int(self.vars['timeout'].get()),
                 'click_wait': int(self.vars['click_wait'].get()),
                 'skip_keywords': [x.strip() for x in self.vars['skip_keywords'].get('1.0', tk.END).strip().split('\n') if x.strip()],
                 'download_keywords': [x.strip() for x in self.vars['download_keywords'].get('1.0', tk.END).strip().split('\n') if x.strip()],
                 'update_keywords': [x.strip() for x in self.vars['update_keywords'].get('1.0', tk.END).strip().split('\n') if x.strip()],
             },
             'filter_packages': [x.strip() for x in self.vars['filter_packages'].get('1.0', tk.END).strip().split('\n') if x.strip()],
             'istest': self.vars['istest'].get(),
             'loop_enabled': self.vars['loop_enabled'].get(),
             'loop_interval': int(self.vars['loop_interval'].get()),
             'sftp': {
                 'host': self.vars['sftp_host'].get(),
                 'port': int(self.vars['sftp_port'].get()),
                 'user': self.vars['sftp_user'].get(),
                 'password': self.vars['sftp_pass'].get(),
                 'remote_dir': self.vars['sftp_dir'].get(),
             },
             'api': {'url': self.vars['api_url'].get()}
        }

        self.is_running = True
        self.start_btn.configure(state=tk.DISABLED, bg="#606060")
        self.stop_btn.configure(state=tk.NORMAL, bg="#d32f2f")
        self.status_label.configure(text="● 运行中", fg="#00e676")
        
        print(f"=== 正在启动任务 (循环: {current_ui_config['loop_enabled']}) ===")
        
        self.worker_thread = threading.Thread(
            target=self.run_main_process, 
            args=(current_ui_config, app), 
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
    
    def run_main_process(self, config_data, app):
        try:
            # 传入配置和停止回调
            core(lambda: not self.is_running, app)
        except Exception as e:
            print(f"错误: {str(e)}")
        finally:
            if self.is_running:
                self.root.after(0, self.stop_process)

def start_init():
    worker_thread = threading.Thread(
                target=init, 
                daemon=True
        )
    worker_thread.start()

def main():
  
    root = tk.Tk()
    app = ApkUpdaterGUI(root)
    start_init()
    root.mainloop()

if __name__ == "__main__":
    main()