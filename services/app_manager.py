import os
import uiautomator2 as u2



class AppManager:
    def __init__(self, device_manager):
        """
        应用管理类
        :param device_manager: 包含 uiautomator2 对象 (d) 的管理器实例
        """
        self.d = device_manager.d

    def get_third_party_packages(self):
        """
        获取所有非系统应用（第三方应用）的包名列表
        :return: list of strings (e.g., ['com.tencent.mm', 'com.whatsapp'])
        """
        try:
            # 使用 shell 命令获取第三方应用列表
            # -3 表示仅筛选第三方应用
            output, exit_code = self.d.shell(["pm", "list", "packages", "-3"])
            
            if exit_code != 0:
                print("获取应用列表失败")
                return []

          
            packages = []
            if output:
                for line in output.splitlines():
                    line = line.strip()
                    if line.startswith("package:"):
                        # 去掉 'package:' 前缀
                        pkg_name = line.split("package:")[1]
                        packages.append(pkg_name)
            
            return packages

        except Exception as e:
            print(f"发生错误: {e}")
            return []

    def get_app_details(self, package_name):
        """
        获取单个应用的详细信息（可选功能）
        :param package_name: 包名
        :return: dict
        """
        try:
            # uiautomator2 提供了 app_info 方法获取详情（包括应用名 label）
            info = self.d.app_info(package_name)
            return {
                "package": package_name,
                "label": info.get("label", "未知名称"), # 应用显示的名称
                "versionName": info.get("versionName"),
                "isSystem": False # 既然我们在查第三方，默认是非系统
            }
        except Exception:
            return {"package": package_name, "label": "无法获取详情"}
    def get_apk_size(self, package_name):
        """
        获取应用 APK 文件的大小 (单位: MB)
        """
        try:
            # 1. 获取 APK 路径
            # 输出格式通常为: package:/data/app/~~xxx/com.xxx-xxx==/base.apk
            out, _ = self.d.shell(f"pm path {package_name}")
            if not out.strip():
                print(f"应用 {package_name} 未安装")
                return 0

            apk_path = out.strip().split(":", 1)[1]

            # 2. 获取文件大小 (字节)
            # 使用 ls -l 获取详细信息
            out_ls, _ = self.d.shell(f"ls -l {apk_path}")
            # ls -l 输出示例: -rw-r--r-- 1 system system 12345678 2023-01-01 12:00 ...
            # 第5列通常是文件大小
            file_size_bytes = int(out_ls.split()[4])

            # 3. 转换为 MB
            size_mb = file_size_bytes / (1024 * 1024)
            return round(size_mb, 2)

        except Exception as e:
            print(f"获取大小失败: {e}")
            return 0

    def get_app_version(self, package_name):
        """
        获取指定包名的版本信息
        :param device: uiautomator2 连接对象 (d)
        :param package_name: 应用包名 (例如 'com.tencent.mm')
        :return: (version_name, version_code) 的元组，如果未安装则返回 None
        """
        try:
            # 1. 使用 uiautomator2 原生接口获取信息
            info = self.d.app_info(package_name)
            
            # info 的结构通常是: 
            # {'versionName': '8.0.42', 'versionCode': 2400, 'label': '微信', ...}
            
            if info:
                v_name = info.get('versionName')
                v_code = info.get('versionCode')
                print(f"[成功]  版本名: {v_name} | 版本号: {v_code}")
                return v_name, v_code
            else:
                print(f"[失败] 无法获取 {package_name} 的信息 (可能未安装)")
                return None

        except Exception as e:
            # 如果应用未安装，uiautomator2 可能会抛出错误，或者返回 None
            print(f"[错误] 获取版本失败: {e}")
            return None

