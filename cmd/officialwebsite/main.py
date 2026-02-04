import os
import sys
import asyncio
import logging
import json
import time

# 将项目根目录添加到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.queue import QueueService
from services.website_checker import WebsiteChecker
from services.download import DownloadService
from services.uploader import SftpUploader
from services.reporter import ReportService
from services.parser import ApkParser
from utils.utils import load_config, get_file_md5


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("OfficialWebsiteUpdate")

# 加载配置
def get_config():
    """
    优先加载当前目录下的 config.yaml，找不到则加载根目录下的 settings.yaml
    """
    local_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.yaml')
    if os.path.exists(local_config_path):
        return load_config(local_config_path)
    return load_config()

async def process_task(task, website_checker, download_service, global_config):
    """
    处理单个任务。
    """
    try:
        url = task.get('website')
        current_size = task.get('file_size', 0)
        package_name = task.get('package')
        
        # 合并全局关键字
        global_keywords = global_config.get('keywords', [])
        task_keywords = task.get('keywords', [])
        # 去重合并
        combined_keywords = list(set(global_keywords + task_keywords))
        task['keywords'] = combined_keywords
        
        if not url:
            logger.error("任务中缺少 website 字段")
            return

        logger.info(f"正在处理任务: {url} ({package_name})")

        # 从 global_config 获取服务配置
        sftp_config = global_config.get('sftp')
        api_config = global_config.get('api')

        # 1. 智能查找 APK 链接
        checker_result = await website_checker.find_download_link(task)
        if not checker_result or not checker_result.get('download_link'):
            logger.warning(f"[{package_name}] 未找到下载链接")
            return

        download_link = checker_result['download_link'].strip().strip('`').strip()
        has_update_signal = checker_result.get('has_update', True)
        version_found = checker_result.get('version_found')

        # 2. 获取 APK 大小
        remote_size = await website_checker.get_file_size(download_link)
        logger.info(f"[{package_name}] 远程文件大小: {remote_size}, 当前大小: {current_size}, LLM更新信号: {has_update_signal}")

        # 3. 比对大小 (结合 LLM 智能决策是否更新)
        # 如果 LLM 明确说没有更新，且大小也没变，则跳过
        should_update = False
        if remote_size > 0 and remote_size != current_size:
            should_update = True
        elif has_update_signal and remote_size > 0:
            # 如果 LLM 认为有更新（可能是版本号变了但大小刚好一致，虽然概率低），也尝试下载
            should_update = True

        if should_update:
            logger.info(f"[{package_name}] 决定更新。原因: {'大小不匹配' if remote_size != current_size else 'LLM信号'}")
            
            # 4. 下载 APK
            # download_service.download 是异步的
            # referer 通常是网站 URL
            file_path = await download_service.download(
                url=download_link, 
                referer=url,
                is_use_proxy=False # Can be parameterized if needed
            )
            
            if file_path and os.path.exists(file_path):
                logger.info(f"已下载至 {file_path}")
                
                # 5. 解析 APK 元数据 (先解析，解析成功才上传)
                import platform
                if platform.system() == "Windows":
                    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    aapt_path = os.path.join(project_root, "bin", "aapt", "aapt.exe")
                    aapt2_path = os.path.join(project_root, "bin", "aapt", "aapt2.exe")
                else:
                    # Linux 系统直接使用系统已存在的 aapt 和 aapt2
                    aapt_path = "aapt"
                    aapt2_path = "aapt2"
                
                # 准备图标提取目录
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                icon_dir = os.path.join(project_root, "temp_icons")
                if not os.path.exists(icon_dir):
                    os.makedirs(icon_dir)

                parser = ApkParser(aapt_path, aapt2_path)
                apk_info = parser.parse(file_path, extract_icon=True, icon_output_dir=icon_dir)
                
                # 6. 验证 APK 有效性
                if not apk_info or not apk_info.get('package'):
                    logger.error(f"[{package_name}] APK 解析失败或文件无效，停止处理。")
                    try: os.remove(file_path)
                    except: pass
                    return

                # 7. 重命名文件为包名小写
                new_filename = f"{apk_info['package'].lower()}.apk"
                new_file_path = os.path.join(os.path.dirname(file_path), new_filename)
                try:
                    if os.path.exists(new_file_path):
                        os.remove(new_file_path)
                    os.rename(file_path, new_file_path)
                    file_path = new_file_path
                    logger.info(f"文件重命名为: {new_filename}")
                except Exception as e:
                    logger.error(f"重命名文件失败: {e}")

                # 8. SFTP 上传 (解析成功后才上传)
                remote_file_path = ""
                if sftp_config:
                    uploader = SftpUploader(sftp_config)
                    if uploader.upload_apk(file_path):
                        logger.info(f"SFTP 上传成功")
                        # 构造远程路径作为 filename 上报
                        remote_dir = sftp_config.get('remote_dir', '')
                        remote_file_path = os.path.join(remote_dir, new_filename).replace("\\", "/")
                    else:
                        logger.error(f"SFTP 上传失败")
                        return # 上传失败也停止上报
                else:
                    logger.warning("未提供 SFTP 配置，跳过上传")

                # 9. 上传图标
                icon_url = ""
                local_icon_path = apk_info.get('local_icon_path')
                if local_icon_path and os.path.exists(local_icon_path):
                    # 图标服务器配置
                    icon_sftp_config = {
                        'host': '172.16.6.84',
                        'port': 22,
                        'user': 'root',
                        'password': sftp_config.get('password', 'yangfei@123'), # 尝试使用主 SFTP 的密码
                        'remote_dir': '/home/pic/ico/'
                    }
                    icon_uploader = SftpUploader(icon_sftp_config)
                    if icon_uploader.upload(icon_sftp_config['remote_dir'], local_icon_path):
                        icon_filename = os.path.basename(local_icon_path)
                        icon_url = f"http://pic.tqqyun.com/ico/{icon_filename}"
                        logger.info(f"图标上传成功: {icon_url}")
                    else:
                        logger.error("图标上传失败")
                    
                    # 上传完后清理本地图标
                    try: os.remove(local_icon_path)
                    except: pass

                # 10. 上报 API
                if api_config:
                    reporter = ReportService(api_config)
                    # 准备上报信息 (按照 params 中的字段名称)
                    report_data = {
                        "package": apk_info.get('package') if apk_info.get('package') else package_name,
                        "appname": apk_info.get('appname', ""),
                        "versionName": apk_info.get('versionName') if apk_info.get('versionName') else (version_found if version_found else task.get('version_name', "")),
                        "versionCode": apk_info.get('versionCode', ""),
                        "file_size": apk_info.get('file_size') if apk_info.get('file_size') else os.path.getsize(file_path),
                        "filename": remote_file_path if remote_file_path else os.path.basename(file_path),
                        "md5": apk_info.get('md5') if apk_info.get('md5') else get_file_md5(file_path),
                        "icon_url": icon_url, 
                        "server": 151,  # 对应 151 服务器
                        "arch": apk_info.get('arch', 2),
                        "download_link": download_link,
                        "update_time": int(time.time()),
                        "update_reason": checker_result.get('reason', 'Size mismatch')
                    }
                    logger.info(f"[{package_name}] 正在上报更新: {report_data}")
                    reporter.notify_success(report_data)
                
                # 清理？DownloadService 通常将文件保留在临时目录。
                # 策略可能是保留或删除。暂时保留。
            else:
                logger.error("下载失败")
        else:
            logger.info("未检测到更新 (大小匹配或无效的远程大小)。")

    except Exception as e:
        logger.error(f"处理任务时出错: {e}")

async def main():
    logger.info("正在启动官网自动更新机器人")
    
    # 初始化服务
    config = get_config()
    
    redis_config = config.get('redis', {'host': 'localhost', 'port': 6379, 'db': 0})
    queue_service = QueueService(redis_config=redis_config)
    website_checker = WebsiteChecker()
    download_service = DownloadService.get_instance()
    
    queue_name = config.get('queue_name', "official_website_update_queue")
    
    while True:
        task = queue_service.get_task(queue_name)
        if task:
            await process_task(task, website_checker, download_service, config)
        else:
            # 如果没有任务则休眠
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
