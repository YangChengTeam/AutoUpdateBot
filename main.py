
import os
import time
import math
import threading
from os import path
# 导入核心环境
from core.env_loader import setup_env, BASE_DIR, AAPT_PATH
from utils.utils import delete_file, get_file_blake3, get_local_path, load_config, rename
import yaml
setup_env() 

# 导入所有服务模块
from core.device.device import DeviceManager
from services.updater import UpdateService
from services.extractor import ApkExtractor
from services.parser import ApkParser
from services.uploader import SftpUploader
from services.reporter import ReportService 
from services.app_manager import AppManager
from services.worker_service import WorkerService


# 全局停止标志（用于GUI控制）
STOP_FLAG = False

storage_dir = os.path.join(BASE_DIR, 'storage')
stop_flag_func = None
cfg = None
app_manager = None
device = None
updater = None
extractor = None
parser = None
uploader = None
reporter = None
worker_thread = None # Worker 线程句柄
is_test = False 
loop_enabled = False
loop_interval = False
pkg_name = ""

current_screenshot_path = ""

def get_third_party_apps():
    packages = app_manager.get_third_party_packages()
    app_infos = []
    for pkg_name in packages:
        version, code = app_manager.get_app_version(pkg_name)
        app_infos.append({
            'package': pkg_name,
            'version': version,
            'code': code
        })
    return app_infos


def init(config = None):
    global cfg, app_manager, device, updater, extractor, parser, uploader, reporter
    global is_test, loop_enabled, loop_interval
    # 1. 初始化配置与连接
    cfg = config if config else load_config()

    # 2. 实例化所有服务 (依赖注入)
    # 设备层
    device = DeviceManager(cfg['emulator']['serial'])
    app_manager = AppManager(device)

    updater = UpdateService(device, cfg)            # 负责点点点
    extractor = ApkExtractor(device, storage_dir)   # 负责拉取
    parser = ApkParser(AAPT_PATH)                   # 负责解析
    uploader = SftpUploader(cfg['sftp'])            # 负责上传
    reporter = ReportService(cfg['api'])            # 负责上报 
    
    is_test = cfg["istest"]
    loop_enabled = cfg["loop_enabled"] 
    loop_interval=cfg["loop_interval"]
                

def take_screenshot(folder_path="screenshots"):
    """
    截图並保存到指定目录
    :param folder_path: 保存的文件夹路径
    """
    global current_screenshot_path 
    # 1. 確保目錄存在，不存在則創建
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
        print(f"已创建目录: {folder_path}")

    # 2. 生成唯一文件名 (使用當前時間)
    # 格式範例: 20231027_153022.jpg
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    file_name = f"screenshot_{timestamp}.jpg"
    
    # 3. 組合完整路徑
    full_path = os.path.join(folder_path, file_name)

    # 4. 執行截圖
    # d.screenshot() 默認保存為 jpg，也可以指定為 png
    device.d.screenshot(full_path)
    current_screenshot_path = full_path
    print(f"截图已保存: {full_path}")
    return pkg_name

def set_config(config):
    global cfg, app_manager, device, updater, extractor, parser, uploader, reporter
    global is_test, loop_enabled, loop_interval, pkg_name

    cfg = config if config else load_config()
    cfg = load_config()
    is_test = cfg["istest"]
    loop_enabled = cfg["loop_enabled"] 
    loop_interval=cfg["loop_interval"]
    device.set_config(cfg['emulator']['serial'])
    uploader.set_config(cfg['sftp'])
    updater.set_config(cfg)
    reporter.set_config(cfg['api'])

    print("重载设置配置成功")


def core(_stop_flag_func=None, one_app = None):
    """
    主函数 - 支持循环检测
    
    参数:
        stop_flag_func: callable - 返回是否应该停止的函数（用于GUI控制）
    """
    print("=== 启动自动化更新机器人 ===")
    global cfg, app_manager, device, updater, extractor, parser, uploader, reporter
    global is_test, loop_enabled, loop_interval, worker_thread
    global stop_flag_func

    stop_flag_func = _stop_flag_func
    cycle_count = 0

    if not device or not device.check_connection():
        init()

    # 启动 Worker 线程
    if not worker_thread or not worker_thread.is_alive():
        worker_service = WorkerService(device)
        worker_thread = threading.Thread(target=worker_service.start, daemon=True)
        worker_thread.start()
        print(f"--> [Main] 已启动 Worker 后台线程")

    # 3. 循环检测逻辑
    while True:
        cycle_count += 1
        updater.start_watchers(take_screenshot, lambda: pkg_name)
        # 检查是否应该停止
        if stop_flag_func and stop_flag_func():
            print("检测到停止信号，退出任务。")
            break
        
        if loop_enabled and cycle_count > 1:
            print(f"\n{'='*60}")
            print(f"🔄 开始第 {cycle_count} 轮检测")
            print(f"{'='*60}\n")
        
        try:
            # 获取应用列表
            final_apps = []
            if one_app :
                print(f"单独测试{one_app}")
                final_apps.append(one_app)
            else: 
                print("正在获取第三方应用列表...")
                filter_packages = cfg["filter_packages"]
                apps = app_manager.get_third_party_packages()
                final_apps = [pkg for pkg in apps if pkg not in filter_packages]
                print(f"共发现 {len(final_apps)} 个第三方应用")
            
            # 处理每个应用
            for pkg_name in final_apps:
                # 检查停止信号
                if stop_flag_func and stop_flag_func():
                    print("检测到停止信号，中断当前任务。")
                    return
                old_version_code = 0
                try:
                    print(f"\n>>> 任务开始: {pkg_name}")
                    is_local_exist = True
                    local_apk_path = get_local_path(pkg_name, storage_dir)
                    
                    if not os.path.exists(local_apk_path):
                        _, old_version_code = app_manager.get_app_version(pkg_name)
                        is_local_exist = False
                        # Step 1: 启动应用
                        if not device.restart_app(pkg_name):
                            continue
                        j = 0
                        
                        while j < int(cfg['detection']['timeout']):
                            # 检查停止信号
                            if stop_flag_func and stop_flag_func():
                                print("检测到停止信号，中断检测。")
                                return
                            
                            time.sleep(1)
                            j += 1
                            print(f">>> [{j}/{cfg['detection']['timeout']}] 检测下载安装... (已耗时 {j}s)")
                            
                            if not updater.has_downloaded:
                                continue

                            # Step 2: 检测是否有更新
                            print(">>> 检测到更新操作，等待下载安装 (模拟休眠)...")
                            
                            # 1. 获取文件大小
                            size_mb = app_manager.get_apk_size(pkg_name)
                            print(f"文件大小: {size_mb} MB")

                            # 2. 动态计算循环次数
                            sleep_interval = 2
                            estimated_seconds = 120 + (size_mb * 1.5)
                            max_retries = max(math.ceil(estimated_seconds / sleep_interval), 60)

                            print(f"根据大小计算，最大等待时间: {estimated_seconds:.1f}秒 (约 {estimated_seconds/60:.1f} 分钟)")
                            print(f"设置循环上限为: {max_retries} 次")

                            # 3. 开始循环
                            for i in range(max_retries):
                                # 检查停止信号
                                if stop_flag_func and stop_flag_func():
                                    print("检测到停止信号，中断下载等待。")
                                    return
                                
                                if updater.has_updated:
                                    break
                                
                                if not updater.is_app_foreground(pkg_name):
                                    print("应用不在前台")

                                print(f">>> [{i}/{max_retries}] 等待下载安装... (已耗时 {i * sleep_interval}s)")
                                time.sleep(sleep_interval)
                            
                            time.sleep(5)
                            _, new_version_code = app_manager.get_app_version(pkg_name)
                            if new_version_code <= old_version_code:
                                print(">>> 安装完成后版本无更新，跳过。")
                            break
                    
                    if local_apk_path:
                        if not updater.has_updated or not updater.has_downloaded:
                            print(">>> 未检测到更新版本")
                            continue 
                        # Step 3: 提取新的 APK   
                        if not is_local_exist:   
                            local_apk_path = extractor.pull(pkg_name)
                        is_local_exist = True    
                        # Step 4: 解析 APK 信息
                        apk_info = parser.parse(local_apk_path)
                        
                        if int(apk_info['versionCode']) <= old_version_code:
                            print(">>> 安装完成后版本无更新，跳过。")
                            delete_file(local_apk_path)
                            continue

                        remote_filename = os.path.basename(local_apk_path)
                        remote_full_path = f"{cfg['sftp']['remote_dir']}/{remote_filename}".replace("//", "/")
                        apk_info["server"] = cfg['sftp']['host'].split('.')[-1]
                        apk_info["filename"] = remote_full_path
                        apk_info["file_size"] = os.path.getsize(local_apk_path)
                        apk_info["md5"] = get_file_md5(local_apk_path)
                        apk_info["screenshot_path"] = f"screenshots/{pkg_name}.jpg".replace("//", "/")
                        screenshot_path = path.join("screenshots",f"{pkg_name}.jpg")
                        if not os.path.exists(screenshot_path) and os.path.exists(current_screenshot_path):
                            rename(current_screenshot_path, screenshot_path)
                        
                        print(f">>> 包信息 {apk_info}")
                        if not is_test:
                            # Step 5: SFTP 上传
                            if os.path.exists(screenshot_path):
                                upload_screenshot_success = uploader.upload_screenhot(screenshot_path)
                                if upload_screenshot_success:
                                    delete_file(screenshot_path)      

                            upload_apk_success = uploader.upload_apk(local_apk_path)  
                            if upload_apk_success:
                                # Step 6: API 上报
                                delete_file(local_apk_path)
                                reporter.notify_success(apk_info)
                                print(f">>> 任务 {pkg_name} 圆满完成！")
                            else:
                                reporter.notify_failure("Apk上传远程服务器失败")
                    else:
                        print(">>> 无更新，跳过。")
                        
                except Exception as e:
                    print(f">>> 任务处理异常： {e}")
                finally:
                    clean(updater, device, pkg_name)
            
            print("\n=== 所有任务处理完毕 ===")
            
        except Exception as e:
            print(f"循环处理异常: {e}")
        finally:
            updater.stop_watchers()
        
        # 判断是否继续循环
        if not loop_enabled:
            print("循环检测未启用，任务结束。")
            break
        
        # 检查停止信号
        if stop_flag_func and stop_flag_func():
            print("检测到停止信号，退出循环。")
            break
        
        # 等待下次检测
        print(f"\n⏰ 等待 {loop_interval} 秒后开始下次检测...")
        print(f"   (约 {loop_interval//60} 分钟 {loop_interval%60} 秒)")
        
        # 分段等待，以便及时响应停止命令
        for i in range(loop_interval):
            if not loop_enabled:
                break
            if stop_flag_func and stop_flag_func():
                print("检测到停止信号，终止等待。")
                return
            time.sleep(1)
            
            # 每30秒提醒一次
            if (loop_interval - i) % 30 == 0 and (loop_interval - i) > 0:
                remaining = loop_interval - i   
                print(f"⏳ 距离下次检测还有 {remaining} 秒 ({remaining//60} 分钟)")


def clean(updater, device, pkg_name):
    """清理函数"""
    updater.has_uptated = False
    updater.has_downloaded = False
    print(f"正在关闭当前应用: {pkg_name}")
    device.d.app_stop(pkg_name) 
    time.sleep(2)


if __name__ == "__main__":
    core()