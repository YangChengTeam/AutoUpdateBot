from operator import is_
import time
from turtle import update
from core.ocr.rapid_ocr import OcrEngine

class UpdateService:
    def __init__(self, device_manager, config=None):
        """
        :param device_manager: core.device.DeviceManager 实例
        :param config: 全局配置字典 (可选)
        """
        self.device = device_manager # 封装后的管理器 (用于截图、重启APP)
        self.d = device_manager.d    # 底层 u2 对象 (用于原生元素查找)
        #self.ocr = OcrEngine()       # OCR 单例
        self.has_updated = False
        self.has_downloaded = False
        self.set_config(config)

    def set_config(self, config):
        # 加载配置，如果没有则使用默认值
        if config and 'detection' in config:
            self.skip_keywords = config['detection']['skip_keywords']
            self.download_keywords = config['detection']['download_keywords']
            self.update_keywords = config['detection']['update_keywords']
            self.click_wait = config['detection']['click_wait']
            self.timeout = config['detection']['timeout']

    def stop_watchers(self):
        self.d.watcher.stop()
        print("\n=== 正在停止所有 watcher ===")

    def start_watchers(self, screenhots = None, get_pkg_name = None):
        """
        配置所有监听器
        :param device: Device 对象封装 (这里假设你有一个 wrapper 类，或者直接传 d)
        """
        d = self.d  # 方便后续调用
        _screenhots = screenhots
        _get_pkg_name = get_pkg_name
        # --- 1. 定义回调函数 ---
        def handle_download_action():
            """
            通用的下载弹窗处理逻辑
            """
            print("【Watcher】检测到下载相关弹窗，正在处理...")
            if self.has_downloaded:
                print(f"【Watcher】已下载，跳过")
                return
            # 尝试点击常见的下载按钮文案
            # 这里做一个遍历检查，哪个存在点哪个
            pkg_name = ""
            if _get_pkg_name:
                pkg_name = _get_pkg_name()
            print(f"【Watcher】发现包名: {pkg_name}")
            for kw in self.download_keywords:
                target_text = kw # 默认点击目标就是关键字本身
                # 1. 尝试分割
                parts = kw.split("|")
                
                # 2. 判断逻辑
                if len(parts) > 1:
                    # 如果分割后长度大于1，说明是 "包名:关键字" 的格式
                    if parts[0] == pkg_name:
                        # 包名匹配，目标文字改为冒号后面的部分
                        target_text = parts[1]
                    else:
                        continue
                # 3. 执行查找与点击
                if self.d(text=target_text).exists:
                    if _screenhots:
                        _screenhots()
                    time.sleep(2)
                    self.d(text=target_text).click()
                    print(f"【Watcher】下载已点击: {pkg_name}: {target_text}")
                    self.has_downloaded = True
                    break

        def handle_update_action():
            """
            通用的更新弹窗处理逻辑
            """
            print("【Watcher】检测到更新相关弹窗，正在处理...")
            
            
            # 尝试点击常见的更新按钮文案
            # 这里做一个遍历检查，哪个存在点哪个
            for kw in  self.update_keywords:
                if d(text=kw).exists:
                    d(text=kw).click()
                    print(f"【Watcher】更新已点击: {kw}")
                    self.has_updated = True
                    break
            
        def handle_permission_source():
            """
            处理 '允许来自此来源的应用' 的特殊逻辑 (点击开关 -> 返回)
            """
            print("【Watcher】检测到安装权限设置...")
            target_text = "允许来自此来源的应用"
            
            if d(text=target_text).exists:
                d(text=target_text).click()
                print(f"【Watcher】已点击: {target_text}")
                time.sleep(self.click_wait) # 等待开关动画
                d.press("back")
                print("【Watcher】已返回上一页")

        def handle_skip_action():
            """
            通用的跳过弹窗处理逻辑
            """
            print("【Watcher】检测到跳过相关弹窗，正在处理...")
            
            # 尝试点击常见的更新按钮文案
            # 这里做一个遍历检查，哪个存在点哪个
            for kw in self.skip_keywords:
                if d(text=kw).exists:
                    d(text=kw).click()
                    print(f"【Watcher】跳过已点击: {kw}")
                    break

        # --- 2. 注册复杂逻辑的 Watcher (带回调) ---
        
        # 只要出现 "更新"，都调用同一个处理函数
        for kw in self.update_keywords:
            d.watcher.when(kw).call(handle_update_action)

        for kw in self.download_keywords:
            parts = kw.split("|")
                # 2. 判断逻辑
            if len(parts) > 1:
                d.watcher.when(parts[1]).call(handle_download_action)
                continue

            d.watcher.when(kw).call(handle_download_action)
        
        # 特殊权限处理
        d.watcher.when("允许来自此来源的应用").call(handle_permission_source)

        # --- 3. 注册简单点击的 Watcher (批量处理) ---
        
        # 只需要无脑点击的关键词列表
        for text_kw in self.skip_keywords:
            d.watcher.when(text_kw).call(handle_skip_action)

        # --- 4. 注册模糊匹配 (XPath) ---
        
        # 使用 XPath: //*[contains(@text, "下载(")]
        d.watcher.when(xpath='//*[contains(@text, "下载()")]').click()
        d.watcher.when(xpath='//*[contains(@text, "更新(")]').click()
        d.watcher.when(xpath='//*[contains(@text, "同意")]').click()
        # --- 5. 启动监听 ---
        print("正在启动所有 Watchers...")
        d.watcher.start()

    def is_app_foreground(self, package_name):
        """
        判断指定包名的应用是否在前台
        :param device: u2 连接对象
        :param package_name: 目标包名 (例如 com.tencent.mm)
        :return: bool
        """
        try:
            # 获取当前前台应用的信息
            # 返回格式示例: {'package': 'com.tencent.mm', 'activity': '.ui.LauncherUI'}
            current_app = self.d.app_current()
            
            # 比较当前包名是否等于目标包名
            if current_app.get("package") == package_name:
                return True
            else:
                return False
        except Exception as e:
            print(f"[检测出错] {e}")
            return False