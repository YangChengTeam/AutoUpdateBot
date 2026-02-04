import requests
import time

class ReportService:
    def __init__(self, api_config):
        """
        :param api_config: dict, 对应 settings.yaml 里的 api 字段
                           例如: {'base_url': 'http://...'}
        """
        self.set_config(api_config)
        
        # 默认请求头
        self.headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'AutoUpdateBot/1.0',
        }

    def set_config(self, api_config):
        self.base_url = api_config.get('url')
        self.share_url = api_config.get('share_url')

    def notify_failure(self, apk_info):
        pass

    def notify_success(self, apk_info):
        """
        当 APK 更新处理成功时调用
        :param apk_info: 字典, parser.py 返回的解析结果 (versionName, versionCode, appname, package, md5, filename, file_size, etc.)
        """
        print(f"--> [API] 正在上报更新信息: {apk_info}...")
        return self._send_post(apk_info)

    def report_share_link(self, data):
        """
        上报分享链接
        :param data: dict, 包含包名、分享链接等信息
        """
        print(f"--> [API] 正在上报分享链接: {data}...")
        # 这里可以使用不同的 URL，但用户说“先定名称”，暂时复用 base_url 
        # 或者如果用户指的是 JSON 结构里的名称，则已经在 data 中体现
        return self._send_post(data)

    def report_app_urls(self, urls):
        """
        按照新格式上报 App 链接
        :param urls: list of strings, APP 链接列表
        """
        payload = {
            "data": {
                "app_urls": urls
            }
        }
        print(f"--> [API] 正在按照新格式上报 App 链接: {payload}...")
        return self._send_post(payload, url=self.share_url)

    def _send_post(self, data, url=None):
        """内部方法：发送 POST 请求"""
        target_url = url if url else self.base_url
        if not target_url:
            print("    [API] 错误: 未配置上报 URL")
            return False
            
        try:
            resp = requests.post(
                target_url, 
                json=data, 
                headers=self.headers, 
                timeout=10 
            )
            
            if resp.status_code == 200:
                print(f"    [API] 上报成功! Server回应: {resp.text[:50]}")
                return True
            else:
                print(f"    [API] 上报失败: HTTP {resp.status_code} - {resp.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"    [API] 网络请求异常: {e}")
            return False