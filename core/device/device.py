import uiautomator2 as u2
import time

class DeviceManager:
    def __init__(self, serial: str):
        """
        初始化设备管理器
        :param serial: 模拟器的地址，例如 "127.0.0.1:5555"
        """
        self.set_config(serial)
        self.d = None  # uiautomator2 的 device 对象
        
        # 初始化连接
        self._connect()
        
        # 配置 uiautomator2 的一些全局参数，提高稳定性
        self._configure_settings()

    def set_config(self, serial: str):
        self.serial = serial

    def check_connection(self):
        try:
            # 嘗試獲取設備信息，設置一個短的超時時間
            # 如果手機沒連上，這裡會報錯
            info = self.d.info
            print(f"連接成功: {info.get('model')}")
            return True
        except Exception as e:
            print(f"連接失敗: {e}")
            return False

    def _connect(self):
        """建立连接"""
        print(f"--> [Device] 正在连接设备: {self.serial}...")
        try:
            # u2.connect 会尝试连接 ADB，如果失败会抛出异常
            self.d = u2.connect(self.serial)
            # 获取设备信息以确认连接成功 (这是一次实际的通信)
            device_info = self.d.info
            print(f"    [Device] 连接成功: {device_info.get('model')} | Android {device_info.get('version')}")
            
            # 唤醒屏幕并解锁 (防止模拟器黑屏导致截图全黑)
            self.d.screen_on()
            
        except Exception as e:
            print(f"    [Device] 致命错误: 连接失败 - {e}")
            print("    请检查模拟器是否启动，或 adb 端口是否正确。")
            raise e

    def _configure_settings(self):
        """配置 u2 的全局设置以优化性能"""
        if not self.d:
            return
            
        # 设置全局元素查找等待时间 (秒)
        # 如果找不到元素，最多等 3 秒，而不是默认的 20 秒，提高检测失败时的响应速度
        self.d.implicitly_wait(3.0)
        
        # 禁用点击后的默认延迟 (默认可能会等待几百毫秒)
        self.d.settings['operation_delay'] = (0, 0)
        self.d.settings['operation_delay_methods'] = []

    def restart_app(self, package_name):
        """
        强制冷启动应用 (先停止再启动)
        这是检测更新最稳妥的方式，确保应用从头加载
        """
        print(f"--> [App] 正在重启应用: {package_name}")
        try:
            # 启动
            self.d.app_start(package_name)
            
            # 等待应用在前台，最多等 10 秒
            # 如果应用启动很慢，这个等待很有必要
            if not self.d.app_wait(package_name, timeout=10):
                print(f"    [警告] 应用 {package_name} 启动似乎超时")
                return False
            else:
                print(f"    [App] 应用已在前台")
                return True
                
        except Exception as e:
            print(f"    [App] 启动失败: {e}")

    def get_current_app(self):
        """获取当前运行的 App 包名"""
        return self.d.app_current().get('package')

    def screenshot_cv2(self):
        """
        获取 OpenCV 格式的截图 (供 OCR 使用)
        :return: numpy array 图像数据
        """
        return self.d.screenshot(format='opencv')

    def click(self, x, y):
        """执行点击"""
        self.d.click(x, y)

    def app_install(self, apk_path: str):
        """
        安装本地 APK 文件
        :param apk_path: APK 文件的绝对路径
        """
        print(f"--> [Device] 正在安装 APK: {apk_path}")
        try:
            # uiautomator2 的 app_install 支持从本地路径安装
            self.d.app_install(apk_path)
            print(f"    [Device] APK 安装成功: {apk_path}")
            return True
        except Exception as e:
            print(f"    [Device] APK 安装失败: {e}")
            return False