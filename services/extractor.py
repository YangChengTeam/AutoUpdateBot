import os
import shutil

from utils.utils import get_local_path

class ApkExtractor:
    def __init__(self, device_manager, storage_dir):
        """
        :param device_manager: core.device.DeviceManager 实例
        :param storage_dir: 本地存放APK的路径
        """
        self.d = device_manager.d
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)

    def pull(self, package_name):
        """
        获取已安装应用的APK文件
        :return: 本地APK的完整路径 or None
        """
        print(f"--> [提取] 正在定位 {package_name}...")
        
        # 1. 获取 Android 内部路径
        try:
            path_output = self.d.shell(f"pm path {package_name}").output.strip()
            if not path_output.startswith("package:"):
                print(f"    [错误] 应用未安装: {package_name}")
                return None
            remote_path = path_output.split(":")[1]
        except Exception as e:
            print(f"    [错误] 获取路径失败: {e}")
            return None

        # 2. 构建本地文件名
        local_path = get_local_path(package_name, self.storage_dir)


        # 3. 拉取文件
        print(f"    [下载] 从模拟器拉取中...")
        try:
            # uiautomator2 的 push/pull 有时不如原生 adb 稳定，可以用 d.pull
            self.d.pull(remote_path, local_path)
            
            # 校验一下文件是否真的存在
            if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
                print(f"    [成功] 已保存至: {local_path}")
                return local_path
            else:
                print("    [失败] 文件下载后为空或不存在")
                return None
        except Exception as e:
            print(f"    [异常] 拉取文件出错: {e}")
            return None