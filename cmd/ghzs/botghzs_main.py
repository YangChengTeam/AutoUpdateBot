import os
import sys
import time
import logging
import re
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.device.device import DeviceManager
from services.reporter import ReportService
from utils.utils import load_config
from core.env_loader import setup_env

# Configure logging
log_handlers = []
if sys.stdout:
    log_handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=log_handlers
)
logger = logging.getLogger("GhzsBot")

class BotGhzs:
    def __init__(self):
        setup_env()
        self.config = self._get_config()
        # Default to localhost if not configured, or use what's in settings
        serial = self.config.get('emulator', {}).get('serial', '127.0.0.1:7555')
        self.device_manager = DeviceManager(serial)
        self.d = self.device_manager.d
        self.reporter = ReportService(self.config.get('api', {}))
        self.package_name = "com.gh.gamecenter"
        self.processed_titles = set()
        self._init_daily_log()

    def _init_daily_log(self):
        """初始化每日日志目录"""
        base_path = self._get_base_path()
        self.log_dir = os.path.join(base_path, "logs", "ghzs")
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
            logger.info(f"创建日志目录: {self.log_dir}")
        
        self.current_date = None
        self.daily_log_file = None
        self._reload_daily_records()

    def _reload_daily_records(self):
        today = time.strftime("%Y-%m-%d")
        if self.current_date == today:
            return
        
        logger.info(f"日期检查: {self.current_date} -> {today}")
        self.current_date = today
        self.daily_log_file = os.path.join(self.log_dir, f"{today}.log")
        self.processed_titles.clear()
        
        if os.path.exists(self.daily_log_file):
            logger.info(f"正在从每日日志加载已处理记录: {self.daily_log_file}")
            try:
                with open(self.daily_log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if "|" in line:
                            title = line.split("|")[0].strip()
                            if title:
                                self.processed_titles.add(title)
            except Exception as e:
                logger.error(f"加载每日日志失败: {e}")

    def _write_to_daily_log(self, title, share_url):
        try:
            with open(self.daily_log_file, 'a', encoding='utf-8') as f:
                f.write(f"{title} | {share_url} | {time.strftime('%H:%M:%S')}\n")
        except Exception as e:
            logger.error(f"写入每日日志失败: {e}")

    def _get_base_path(self):
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        else:
            return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def _get_config(self):
        root_config = os.path.join(self._get_base_path(), 'settings.yaml')
        return load_config(root_config)

    def start(self, stop_func=None):
        logger.info("正在启动光环助手应用...")
        self.d.app_start(self.package_name, stop=True)
        time.sleep(5)
        
        # Ensure we reach the list ensuring
        while True:
            if stop_func and stop_func():
                break

            self.handle_popups()
            if self.navigate_to_list():
                logger.info("进入列表页，开始采集循环...")
                self.loop_crawl(stop_func)
                # loop_crawl terminates only on stop_func, so if it returns, we likely want to exit or restart app
                break
            else:
                logger.warning("导航失败，5秒后重试...")
                time.sleep(5)

    def loop_crawl(self, stop_func=None):
        while True:
            if stop_func and stop_func():
                break
            
            # Inner loop: Scroll and accumulate
            while True:
                if stop_func and stop_func():
                    return

                self._reload_daily_records()
                found_old_data = self.process_list(stop_func)
                
                if found_old_data:
                    logger.info("发现旧数据，本轮采集结束")
                    break
                
                # Scroll down
                logger.info("上滑加载更多...")
                self.d.swipe_ext("up", scale=0.8)
                time.sleep(1)
            
            # Wait before next round
            logger.info("等待 60 秒后开始下一轮...")
            for _ in range(60):
                if stop_func and stop_func():
                    return
                time.sleep(1)
            
            # Restart/Refresh list
            logger.info("开始新一轮采集，重置列表位置...")
            if not self.navigate_to_list():
                logger.warning("重置列表失败，重启应用...")
                self.d.app_start(self.package_name, stop=True)
                time.sleep(5)
                self.navigate_to_list()
            
            # Simple check to stop if we are just scrolling endlessly without finding new titles?
            # Implemented processed_titles check inside process_list. 
            # Ideally we check if screen content changed.

    def process_list(self, stop_func=None):
        games = self.d(resourceId="com.gh.gamecenter:id/game_name")
        if not games.exists:
            logger.warning("未找到游戏列表项...")
            return False
            
        count = games.count
        logger.info(f"当前屏幕发现 {count} 个游戏")
        
        found_new_item = False
        
        for i in range(count):
            if stop_func and stop_func():
                return True # Stop

            try:
                # Reload elements
                games = self.d(resourceId="com.gh.gamecenter:id/game_name")
                if i >= games.count:
                    break
                    
                game = games[i]
                title = game.get_text()
                
                if not title:
                    continue

                if title in self.processed_titles:
                    logger.debug(f"跳过已处理: {title}")
                    continue
                
                logger.info(f"处理游戏 [{i+1}/{count}]: {title}")
                game.click()
                time.sleep(2) # Wait for transition
                
                # In Detail Page
                # Check for date, if old -> return True (stop outer loop)
                is_old = self.check_detail_and_share(title)
                
                # Back to list
                logger.info("返回列表...")
                self.d.press("back")
                time.sleep(1.5)
                
                if is_old:
                    return True
                    
            except Exception as e:
                logger.error(f"处理项目出错: {e}")
                
        return False

    def check_detail_and_share(self, title):
        # 找时间 d(resourceId="com.gh.gamecenter:id/dateTv")
        # 需要滚动找
        logger.info("查找更新时间...")
        date_text = None
        for _ in range(5):
             el = self.d(resourceId="com.gh.gamecenter:id/dateTv")
             if el.exists:
                 date_text = el.get_text()
                 break
             self.d.swipe_ext("up", scale=0.5)
             time.sleep(1)
             
        if not date_text:
            logger.warning("未找到时间信息，默认跳过")
            self.processed_titles.add(title)
            return False # Assume not old to keep searching? Or old? 
                         # User instruction: "判斷是否小于當天時間 如果是就跳過"
                         # If date not found, we can't judge. Safe to skip reporting but continue loop?
                         # I will return False to continue loop.

        logger.info(f"发现时间: {date_text}")

        # Parse date
        # 判斷是否小于當天時間
        try:
             # Extract date YYYY-MM-DD
             match = re.search(r"\d{4}-\d{2}-\d{2}", date_text)
             if match:
                 date_str = match.group()
                 today_str = time.strftime("%Y-%m-%d")
                 if date_str < today_str:
                     logger.info(f"日期 {date_str} 早于今天 {today_str}，跳过并停止采集")
                     return True # is_old = True, stop loop
             else:
                 # If relative time e.g. "2 hours ago", it's likely today.
                 if "今天" in date_text or "小时前" in date_text or "分钟前" in date_text:
                     pass # Continue to report
                 else:
                     # Check if it contains year/month that is obviously old?
                     # Simple fallback: if no YYYY-MM-DD found and no "Today" keywords, 
                     # we might check if it has a date from previous years. 
                     pass 
        except Exception as e:
            logger.error(f"日期解析错误: {e}")

        # If we are here, it's considered new or recent enough
        self.perform_share(title)
        self.processed_titles.add(title)
        return False # not old, continue

    def perform_share(self, title):
        logger.info("执行分享操作...")
        # Then click menu_more
        menu = self.d(resourceId="com.gh.gamecenter:id/menu_more")
        if menu.exists:
            menu.click()
            time.sleep(1)
        else:
            logger.warning("未找到更多菜单")
            return

        # Then click copy_link_tv
        copy_btn = self.d(resourceId="com.gh.gamecenter:id/copy_link_tv")
        if copy_btn.exists:
            copy_btn.click()
            time.sleep(1)
        else:
            logger.warning("未找到复制链接按钮")
            return
        
        # Get clipboard
        link = self.d.clipboard
        logger.info(f"获取链接: {link}")
        
        if link:
            self.reporter.report_app_urls([link])
            self._write_to_daily_log(title, link)
            logger.info("上报成功")
        else:
            logger.warning("剪贴板为空")

def run_ghzs(stop_func=None):
    bot = BotGhzs()
    bot.start(stop_func)

if __name__ == "__main__":
    run_ghzs()
