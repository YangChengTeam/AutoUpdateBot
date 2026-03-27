import os
import sys
import time
import logging
import re

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.device.device import DeviceManager
from services.reporter import ReportService
from services.parser import ApkParser
from services.uploader import SftpUploader
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
logger = logging.getLogger("HYKBBot")

class BotHYKB:
    def __init__(self):
        setup_env()  # 初始化环境（加载本地 ADB 路径）
        self.config = self._get_config()
        serial = self.config.get('emulator', {}).get('serial', '127.0.0.1:7555')
        self.device_manager = DeviceManager(serial)
        self.d = self.device_manager.d
        self.reporter = ReportService(self.config.get('api', {}))
        self.package_name = "com.xmcy.hykb"
        self.processed_titles = set()
        
        # 初始化 APK 解析器
        base_path = self._get_base_path()
        aapt_path = os.path.join(base_path, 'bin', 'aapt', 'aapt.exe')
        aapt2_path = os.path.join(base_path, 'bin', 'aapt', 'aapt2.exe')
        self.parser = ApkParser(aapt_path, aapt2_path)
        
        # 初始化 SFTP 上传器
        sftp_config = self.config.get('sftp', {})
        self.uploader = SftpUploader(sftp_config)
        
        # 初始化本地临时目录
        self.temp_dir = os.path.join(base_path, 'temp', 'hykb')
        self.icons_dir = os.path.join(base_path, 'temp', 'hykb', 'icons')
        os.makedirs(self.temp_dir, exist_ok=True)
        os.makedirs(self.icons_dir, exist_ok=True)
        
        # HYKB 下载目录 (设备上)
        self.hykb_download_dir = "/sdcard/Android/data/com.xmcy.hykb/files/HYKB/bazaar/"
        
        self._init_daily_log()

    def _init_daily_log(self):
        """初始化每日日志目录"""
        base_path = self._get_base_path()
        self.log_dir = os.path.join(base_path, "logs", "hykb")
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
            logger.info(f"创建日志目录: {self.log_dir}")
        
        # 记录当前日期，用于检测日期变化
        self.current_date = None
        self.daily_log_file = None
        # 首次加载
        self._reload_daily_records()

    def _reload_daily_records(self):
        """清空并根据当天日志重新加载已处理记录"""
        today = time.strftime("%Y-%m-%d")
        
        # 检查日期是否变化
        if self.current_date == today:
            logger.debug("日期未变化，跳过重新加载")
            return
        
        logger.info(f"日期检查: {self.current_date} -> {today}")
        self.current_date = today
        self.daily_log_file = os.path.join(self.log_dir, f"{today}.log")
        
        # 清空旧记录
        self.processed_titles.clear()
        
        # 从当天日志加载记录
        if os.path.exists(self.daily_log_file):
            logger.info(f"正在从每日日志加载已处理记录: {self.daily_log_file}")
            try:
                with open(self.daily_log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if "|" in line:
                            title = line.split("|")[0].strip()
                            if title:
                                self.processed_titles.add(title)
                logger.info(f"已加载 {len(self.processed_titles)} 条历史记录")
            except Exception as e:
                logger.error(f"加载每日日志失败: {e}")
        else:
            logger.info(f"当天日志文件不存在，将从零开始记录: {self.daily_log_file}")

    def _write_to_daily_log(self, title, share_url):
        """将分享成功的应用记录到每日日志"""
        try:
            with open(self.daily_log_file, 'a', encoding='utf-8') as f:
                f.write(f"{title} | {share_url} | {time.strftime('%H:%M:%S')}\n")
        except Exception as e:
            logger.error(f"写入每日日志失败: {e}")

    def _write_checked_to_log(self, title):
        """将已检查的应用记录到每日日志（避免重复进入详情页）"""
        try:
            with open(self.daily_log_file, 'a', encoding='utf-8') as f:
                f.write(f"{title} | CHECKED | {time.strftime('%H:%M:%S')}\n")
            # 同时添加到内存中的已处理列表
            self.processed_titles.add(title)
        except Exception as e:
            logger.error(f"写入每日日志失败: {e}")

    def _get_base_path(self):
        """获取基础路径（打包后为 EXE 所在目录）"""
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        else:
            return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def _get_config(self):
        # Prefer root settings.yaml
        root_config = os.path.join(self._get_base_path(), 'settings.yaml')
        return load_config(root_config)

    def get_activity(self):
        """获取当前 Activity 名称"""
        try:
            current = self.d.app_current()
            return current.get('activity', '')
        except:
            return ""

    def is_detail_page(self, activity=None):
        """判断是否在详情页"""
        if activity is None:
            activity = self.get_activity()
        # HYKB 的详情页 Activity 名称
        return "GameDetailActivity" in activity

    def is_home_page(self, activity=None):
        """判断是否在首页"""
        if activity is None:
            activity = self.get_activity()
        
        # 1. 检查 Activity
        if "MainActivity" in activity:
            return True
        
        # 2. 兜底检测: 检查首页关键元素 (精选 tab)
        # 有时 ADB 报告的 Activity 依然是 SplashActivity，但 UI 已经渲染完成
        if self.d(resourceId="com.xmcy.hykb:id/title", text="精选").exists(timeout=1):
            logger.info("检测到首页关键元素【精选】，判定为首页状态")
            return True
            
        return False

    def start(self, stop_func=None):
        logger.info("正在启动 好游快爆 应用...")
        self.d.app_start(self.package_name, stop=True)
        time.sleep(5)
        
        splash_start_time = time.time()
        splash_timeout = 20  # 启动页超时时间

        while True:
            if stop_func and stop_func():
                logger.info("检测到停止信号，退出主循环...")
                break

            activity = self.get_activity()
            
            # 处理可能出现的弹窗
            self.handle_popups()
            
            # 检测是否在首页
            if self.is_home_page(activity):
                logger.info("检测到已进入首页，开始导航到【最新上架】...")
                if self.navigate_to_newest():
                    self.loop_crawl(stop_func)
                    break
            else:
                if "SplashActivity" in activity:
                    current_wait = time.time() - splash_start_time
                    logger.info(f"当前处于启动页 (已等待 {int(current_wait)}s)，尝试处理弹窗...")
                    
                    # 启动页特别处理: 尝试点击屏幕中心或跳过
                    if current_wait > 5:
                        # 尝试点击一些可能的“跳过”坐标或按钮
                        skip_btn = self.d(textMatches="(?i)跳过|Skip")
                        if skip_btn.exists(timeout=1):
                            logger.info("点击启动页【跳过】按钮")
                            skip_btn.click()
                        
                    if current_wait > splash_timeout:
                        logger.warning(f"启动页等待超时 ({splash_timeout}s)，尝试重启应用...")
                        self.d.app_start(self.package_name, stop=True)
                        time.sleep(5)
                        splash_start_time = time.time() # 重置计时
                else:
                    logger.info(f"当前不在首页 (当前 Activity: {activity})，尝试自动导航...")
                
                self.handle_popups()
                time.sleep(3)

    def navigate_to_newest(self):
        """导航到最新上架页面"""
        # 1. 先点击精选 tab
        jingxuan_btn = self.d(resourceId="com.xmcy.hykb:id/title", text="精选")
        if jingxuan_btn.exists:
            logger.info("点击【精选】标签")
            jingxuan_btn.click()
            time.sleep(2)
            
            # 一次最大高度上拉
            logger.info("执行一次最大高度上拉，快速跳过精选内容...")
            self._swipe_up_max()
            time.sleep(1)
        
        # 2. 向下滚动找到"最新上架"
        for i in range(10):
            newest_btn = self.d(resourceId="com.xmcy.hykb:id/tv_tab_title", text="最新上架")
            if newest_btn.exists:
                logger.info("找到【最新上架】，点击进入...")
                newest_btn.click()
                time.sleep(2)
                return True
            
            logger.info(f"未找到【最新上架】，正在进行第 {i+1} 次向下滑动...")
            self._swipe_up()
            time.sleep(1)
        
        logger.warning("未能找到【最新上架】")
        return False

    def handle_popups(self):
        """处理可能出现的弹窗"""
        # 1. 强行检查包名，如果跳出了应用则切回
        try:
            current = self.d.app_current()
            if current.get('package') != self.package_name:
                logger.warning(f"检测到离开应用 (当前: {current.get('package')})，强行切回...")
                self.d.app_start(self.package_name)
                time.sleep(2)
        except:
            pass

        # 2. 处理广告弹窗 (首页通知关闭按钮)
        try:
            ad_close = self.d(resourceId="com.xmcy.hykb:id/dialog_home_notice_image_close")
            if ad_close.exists(timeout=1):
                logger.info("关闭广告弹窗")
                ad_close.click()
                time.sleep(1)
        except:
            pass

        # 3. 处理通用弹窗
        popups = ["同意", "确定", "允许", "进入", "精选", "知道了", "我知道了", "跳过", "始终允许", "以后再说", "取消", "关闭", "Skip", "Close"]
        for p in popups:
            try:
                btn = self.d(text=p)
                if btn.exists(timeout=0.5):
                    logger.info(f"点击弹窗按钮: {p}")
                    btn.click()
                    time.sleep(1)
            except:
                pass
        
        # 4. 检查协议勾选框
        try:
            # 常见的好游快爆协议勾选框
            checkbox = self.d(resourceIdMatches=".*checkbox.*|.*protocol.*|.*agree.*")
            if checkbox.exists(timeout=0.5) and not checkbox.info.get('checked', True):
                logger.info("发现未勾选的协议框，尝试勾选")
                checkbox.click()
                time.sleep(0.5)
        except:
            pass

    def back_to_home(self):
        """返回到主页 Activity"""
        for _ in range(8):
            self.handle_popups()
            activity = self.get_activity()
            if self.is_home_page(activity):
                logger.info("已返回主页")
                return True
            logger.info(f"当前 Activity: {activity}, 尝试返回...")
            self.d.press("back")
            time.sleep(1.5)
        return False

    def loop_crawl(self, stop_func=None):
        while True:
            if stop_func and stop_func():
                logger.info("检测到停止信号，退出循环...")
                break

            logger.info("开始新一轮采集循环...")
            
            # 每轮循环前重新加载当天日志，确保日期切换时使用正确的记录
            self._reload_daily_records()
            
            found_old_data = False
            try:
                found_old_data = self.process_list(stop_func)
            except Exception as e:
                logger.error(f"处理列表时出错: {e}")

            # 无论是否发现旧数据，本轮结束后都退出到首页重新进入，以重置状态
            logger.info("本轮采集结束，退出到首页并重新进入列表以重置状态...")
            self.back_to_home()
            
            if not self.navigate_to_newest():
                logger.warning("重新导航失败，尝试重置应用...")
                self.d.app_start(self.package_name, stop=True)
                time.sleep(5)
                self.navigate_to_newest()
            
            if found_old_data:
                logger.info("由于发现旧数据，立即开始下一轮采集循环...")
                continue
            
            # 如果没有发现旧数据（可能是列表到底了），等待一段时间
            logger.info("本轮处理完毕，等待 60 秒后开始下一轮...")
            for _ in range(60):
                if stop_func and stop_func():
                    return
                time.sleep(1)


    def reset_list_position(self):
        """重置列表位置到最新上架"""
        try:
            # 先点击其他 tab 再点回精选
            jingxuan_btn = self.d(resourceId="com.xmcy.hykb:id/title", text="精选")
            if jingxuan_btn.exists:
                jingxuan_btn.click()
                time.sleep(1)
            
            # 重新导航到最新上架
            self.navigate_to_newest()
        except Exception as e:
            logger.warning(f"重置列表位置失败: {e}")

    def _swipe_up(self):
        """上拉滑动"""
        self.d.swipe_ext("up", scale=0.8)
        time.sleep(1)

    def _swipe_up_max(self):
        """执行一次最大高度的垂直向上滑动"""
        # 使用屏幕中心位置进行精确垂直滑动
        screen_width = self.d.info['displayWidth']
        screen_height = self.d.info['displayHeight']
        
        # 从屏幕极靠下位置向上滑动到极靠上位置
        start_x = screen_width // 2
        start_y = int(screen_height * 0.95)
        end_y = int(screen_height * 0.05)
        
        logger.debug(f"执行最大高度滑动: ({start_x}, {start_y}) -> ({start_x}, {end_y})")
        self.d.swipe(start_x, start_y, start_x, end_y, duration=0.4)
        time.sleep(1.0)

    def _swipe_up_detail(self):
        """详情页专用的精确垂直滑动（避免触发 tab 切换）"""
        # 使用屏幕中心位置进行精确垂直滑动
        screen_width = self.d.info['displayWidth']
        screen_height = self.d.info['displayHeight']
        
        # 从屏幕偏下位置向上滑动到偏上位置，保持 X 坐标不变以获取最大滑动距离
        start_x = screen_width // 2
        start_y = int(screen_height * 0.9)  # 从屏幕 90% 高度开始
        end_y = int(screen_height * 0.1)    # 滑动到屏幕 10% 高度
        
        self.d.swipe(start_x, start_y, start_x, end_y, duration=0.5)
        time.sleep(1.0)

    def _click_blank_area(self):
        """点击空白区域关闭弹窗"""
        screen_width = self.d.info['displayWidth']
        screen_height = self.d.info['displayHeight']
        # 点击屏幕左上角区域
        self.d.click(int(screen_width * 0.1), int(screen_height * 0.1))
        time.sleep(0.5)

    def _scroll_to_last_item(self, last_title=None):
        """滚动找到上次处理的项目（不重置列表位置）"""
        if not last_title:
            return True
        
        # 滚动直到找到上次处理的项目
        for i in range(5):  # 最多滚动5次
            # 查找是否有该标题
            title_elem = self.d.xpath(f'//*[@resource-id="com.xmcy.hykb:id/item_homeindex_game_title"]/android.widget.TextView[@text="{last_title}"]')
            if title_elem.exists:
                logger.info(f"找到上次处理的项目【{last_title}】")
                return True
            
            # 继续滚动
            self._swipe_up()
            time.sleep(0.5)
        
        logger.info(f"未找到上次处理的项目【{last_title}】，继续采集")
        return True

    def process_list(self, stop_func=None):
        """处理更新列表 - 只要更新日期 >= 今天就采集"""
        found_old_data = False
        last_element_title = None
        last_element_count = 0
        max_repeat_count = 3

        while not found_old_data:
            if stop_func and stop_func():
                return False
            
            # 必须是在首页才能点击
            if not self.is_home_page():
                logger.warning(f"当前不在首页 (Activity: {self.get_activity()})，尝试回退...")
                self.handle_popups()
                self.d.press("back")
                time.sleep(1.5)
                if not self.is_home_page():
                    logger.error("无法返回首页，跳出本轮循环")
                    return False

            # 查找列表项标题
            title_items = self.d.xpath('//*[@resource-id="com.xmcy.hykb:id/item_homeindex_game_title"]/android.widget.TextView[1]')
            
            if not title_items.exists:
                logger.warning("未能找到列表项标题")
                self._swipe_up()
                time.sleep(1)
                continue

            current_screen_last_title = None
            all_items = title_items.all()
            item_count = len(all_items)
            logger.info(f"当前屏幕找到 {item_count} 个标题元素")
            
            for i in range(item_count):
                if stop_func and stop_func():
                    return False

                if not self.is_home_page():
                    break

                try:
                    # 重新获取元素列表（因为返回后页面可能刷新）
                    title_items = self.d.xpath('//*[@resource-id="com.xmcy.hykb:id/item_homeindex_game_title"]/android.widget.TextView[1]')
                    try:
                        all_items = title_items.all()
                    except Exception as e:
                        logger.warning(f"获取元素列表失败，尝试恢复连接: {e}")
                        # 尝试恢复连接
                        time.sleep(2)
                        try:
                            self.d.info  # 测试连接
                            all_items = title_items.all()
                        except:
                            logger.error("连接恢复失败，跳出当前循环")
                            break
                    
                    if i >= len(all_items):
                        logger.info(f"索引 {i} 超出当前元素数量 {len(all_items)}，等待下一页")
                        break
                    
                    title_elem = all_items[i]
                    
                    # 获取标题文本
                    title = title_elem.text if title_elem else "未知应用"
                    # 移除标题中的 | 字符，避免日志解析问题
                    if title:
                        title = title.replace("|", "")
                    
                    if title and title != "未知应用":
                        current_screen_last_title = title
                        
                        if title in self.processed_titles:
                            logger.info(f"应用【{title}】已在历史记录中，跳过并继续检查...")
                            continue
                        self.processed_titles.add(title)

                    logger.info(f"正在检查第 {i+1} 项: {title}")
                    self.current_title = title
                    
                    # 点击标题进入详情页
                    title_elem.click()
                    time.sleep(2)
                    
                    # 确认进入了详情页
                    if self.is_detail_page():
                        result = self.check_and_share()
                        if result is True:
                            logger.info(f"【成功】已处理并上报: {title}")
                        elif result is False:
                            logger.info(f"【跳过】应用 {title} 更新日期较旧，停止本轮采集")
                            found_old_data = True
                        else:  # result is None
                            logger.warning(f"【警告】应用 {title} 未发现有效日期信息，跳过当前项继续采集")
                        
                        self.d.press("back")
                        time.sleep(1)
                        
                        # 返回后滚动找到上次处理的项目（避免回到顶部）
                        self._scroll_to_last_item(last_title=title)
                    else:
                        logger.warning(f"点击项目后未进入详情页 (当前: {self.get_activity()})")
                        self.handle_popups()

                    if found_old_data:
                        break
                except Exception as e:
                    logger.error(f"处理项目时出错: {e}")
                    if not self.is_home_page():
                        self.d.press("back")

            # 底部检测
            if current_screen_last_title:
                if current_screen_last_title == last_element_title:
                    last_element_count += 1
                    logger.info(f"检测到最后元素【{current_screen_last_title}】重复出现 {last_element_count}/{max_repeat_count} 次")
                    if last_element_count >= max_repeat_count:
                        logger.info(f"【底部检测】最后元素连续出现 {max_repeat_count} 次，已到达列表底部，结束本轮采集")
                        break
                else:
                    last_element_title = current_screen_last_title
                    last_element_count = 1

            if not found_old_data:
                self._swipe_up()
                time.sleep(2)
        
        return found_old_data

    def check_and_share(self):
        """判断是否为今天更新，若是则执行分享。"""
        # 0. 检查是否为预约状态
        try:
            download_info = self.d(resourceId="com.xmcy.hykb:id/text_detail_download_info")
            if download_info.exists and "预约" in download_info.get_text():
                logger.info(f"【跳过】应用 {self.current_title} 处于预约状态")
                # 记录到日志，避免下次重复进入详情页
                self._write_checked_to_log(self.current_title)
                return None
        except Exception as e:
            logger.debug(f"检查预约状态失败: {e}")

        # 1. 滚动查找"更多"按钮并点击
        more_btn = None
        for i in range(6):
            self.handle_popups()
            
            more_btn = self.d(resourceId="com.xmcy.hykb:id/module_e_more")
            if more_btn.exists:
                logger.info("找到【更多】按钮，点击展开详情...")
                more_btn.click()
                time.sleep(1)
                break
            
            if i < 8:
                logger.info(f"未找到【更多】按钮，正在进行第 {i+1} 次向下滑动查找...")
                self._swipe_up_detail()
                time.sleep(1.5)

        # 2. 查找更新时间元素 - 先找"更新时间"标签，再获取对应的时间值
        time_text = None
        update_time_label = self.d(resourceId="com.xmcy.hykb:id/item_gametail_gameinfo_text_toptext", text="更新时间")
        
        if update_time_label.exists:
            logger.info("找到【更新时间】标签")
            try:
                # 方法1: 通过 sibling 获取同级的时间值元素
                time_elem = update_time_label.sibling(resourceId="com.xmcy.hykb:id/item_gametail_gameinfo_text_bottomtext")
                if time_elem.exists:
                    time_text = time_elem.get_text()
                    logger.info(f"检测到更新时间文本 (sibling): {time_text}")
            except Exception as e:
                logger.debug(f"sibling 方法失败: {e}")
            
            if not time_text:
                try:
                    # 方法2: 通过位置匹配 - 获取标签下方最近的时间值元素
                    label_bounds = update_time_label.info.get('bounds', {})
                    if label_bounds:
                        label_bottom = label_bounds.get('bottom', 0)
                        label_left = label_bounds.get('left', 0)
                        
                        # 查找所有时间值元素
                        all_time_elems = self.d(resourceId="com.xmcy.hykb:id/item_gametail_gameinfo_text_bottomtext")
                        for elem in all_time_elems:
                            try:
                                elem_bounds = elem.info.get('bounds', {})
                                if elem_bounds:
                                    elem_top = elem_bounds.get('top', 0)
                                    elem_left = elem_bounds.get('left', 0)
                                    # 检查是否在标签下方且水平位置接近
                                    if elem_top >= label_bottom - 10 and abs(elem_left - label_left) < 100:
                                        time_text = elem.get_text()
                                        logger.info(f"检测到更新时间文本 (位置匹配): {time_text}")
                                        break
                            except:
                                continue
                except Exception as e:
                    logger.debug(f"位置匹配方法失败: {e}")
        else:
            logger.warning("未找到【更新时间】标签")
        
        # 3. 点击空白处关闭弹窗
        self._click_blank_area()
        time.sleep(0.5)
        
        if time_text:
            # 使用当前日期作为采集过滤条件
            min_date_str = time.strftime("%Y-%m-%d")
            logger.info(f"当前循环采集日期设定为: {min_date_str}")
            
            # 常见格式处理
            # 1. 直接包含日期 YYYY-MM-DD
            date_match = re.search(r"\d{4}-\d{2}-\d{2}", time_text)
            if date_match:
                app_date_str = date_match.group()
                if app_date_str >= min_date_str:
                    return self.perform_share()
                else:
                    logger.info(f"【过滤】应用更新日期 {app_date_str} 早于起始日期 {min_date_str}")
                    # 记录到日志，避免下次重复进入详情页
                    self._write_checked_to_log(self.current_title)
                    return False

            # 2. 关键词处理 (今天, 小时前, 分钟前)
            today_str = time.strftime("%Y-%m-%d")
            is_recent = any(kw in time_text for kw in ["今天", "小时前", "分钟前"])
            
            if is_recent:
                if today_str >= min_date_str:
                    return self.perform_share()
                else:
                    logger.info(f"【过滤】最近更新但今天早于起始日期 {min_date_str}")
                    # 记录到日志，避免下次重复进入详情页
                    self._write_checked_to_log(self.current_title)
                    return False
            
            # 3. 兜底匹配
            if min_date_str in time_text:
                return self.perform_share()
            
            # 4. 无法识别日期格式，也记录下来避免重复
            self._write_checked_to_log(self.current_title)
        else:
            logger.warning("未找到更新时间内容元素")
            # 找不到时间元素也记录，避免重复
            self._write_checked_to_log(self.current_title)

        return None

    def perform_share(self):
        """执行分享操作，获取链接并上报"""
        # 1. 点击分享按钮
        share_btn = self.d.xpath('//*[@resource-id="com.xmcy.hykb:id/iv_btn_more"]')
        if share_btn.exists:
            logger.info("点击【分享】按钮")
            share_btn.click()
            time.sleep(2)
            
            # 2. 点击"复制链接"
            copy_url_btn = self.d(resourceId="com.xmcy.hykb:id/tv_share_title", text="复制链接")
            if copy_url_btn.exists:
                logger.info("点击【复制链接】按钮")
                copy_url_btn.click()
                time.sleep(1)
                
                # 3. 从剪贴板获取内容
                clipboard_content = self.d.clipboard
                logger.info(f"剪贴板内容: {clipboard_content}")
                
                # 4. 从文本中提取 URL
                share_url = None
                if clipboard_content:
                    # 使用正则提取 http/https 链接
                    url_match = re.search(r'https?://[^\s]+', clipboard_content)
                    if url_match:
                        share_url = url_match.group()
                        logger.info(f"提取到链接: {share_url}")
                
                # 5. 上报分享链接
                if share_url:
                    self.reporter.report_app_urls([share_url])
                    
                    # 6. 记录到每日日志
                    self._write_to_daily_log(self.current_title, share_url)
                    
                    # 7. 下载、解析 APK 并上传
                    self.download_and_upload_apk(share_url)
                    
                    # 刷新连接，防止长时间操作后超时
                    try:
                        self.d.info
                    except:
                        logger.warning("刷新连接...")
                        time.sleep(1)
                    
                    return True
                else:
                    logger.warning("剪贴板为空，获取链接失败")
            else:
                logger.warning("未能找到【复制链接】按钮")
                self.d.press("back")
        else:
            logger.warning("未能找到【分享】按钮")

        return False

    def download_and_upload_apk(self, share_url: str):
        """下载 APK、解析并上传到 SFTP，最后通过 API 上报"""
        try:
            # 1. 点击下载按钮
            logger.info("[下载] 点击下载按钮")
            download_btn = self.d(resourceId="com.xmcy.hykb:id/btn_detail_download")
            if not download_btn.exists(timeout=3):
                logger.warning("[下载] 未找到下载按钮，跳过下载流程")
                return False
            
            download_btn.click()
            time.sleep(2)
            
            # 2. 等待下载完成 (按钮文本变为"安装")
            logger.info("[下载] 等待下载完成...")
            max_wait = 300  # 最大等待 5 分钟
            wait_interval = 3
            waited = 0
            
            while waited < max_wait:
                # 检查是否出现安装弹窗 (通过检测安装按钮)
                install_btn = self.d(resourceId="com.xmcy.hykb:id/btn_detail_download", text="安装")
                if install_btn.exists(timeout=1):
                    logger.info("[下载] 下载完成，检测到安装按钮")
                    break
                
                # 也检查系统安装弹窗
                sys_install = self.d(text="安装")
                if sys_install.exists(timeout=1):
                    logger.info("[下载] 下载完成，检测到系统安装弹窗")
                    break
                
                time.sleep(wait_interval)
                waited += wait_interval
                if waited % 30 == 0:
                    logger.info(f"[下载] 已等待 {waited} 秒...")
            
            if waited >= max_wait:
                logger.warning("[下载] 等待超时，跳过下载流程")
                return False
            
            # 3. 取消安装弹窗
            logger.info("[下载] 取消安装弹窗")
            cancel_btn = self.d(text="取消")
            if cancel_btn.exists(timeout=2):
                cancel_btn.click()
                time.sleep(1)
            else:
                # 尝试按返回键关闭弹窗
                self.d.press("back")
                time.sleep(1)
            
            # 4. 列出 HYKB 下载目录找到对应的 APK
            logger.info("[下载] 查找已下载的 APK 文件")
            files = self.device_manager.list_dir_adb(self.hykb_download_dir)
            logger.info(f"[下载] 目录文件列表: {files}")
            
            # 通过应用名称匹配 APK 文件
            target_apk = None
            app_name = self.current_title  # 当前处理的应用名称
            
            for f in files:
                # 文件名包含应用名称即匹配
                if app_name and app_name in f:
                    target_apk = f
                    logger.info(f"[下载] 匹配到文件: {f}")
                    break
            
            # 如果按名称没找到，尝试找最新的 .apk 文件作为备选
            if not target_apk:
                apk_files = [f for f in files if '.apk' in f.lower()]
                if apk_files:
                    target_apk = apk_files[-1]
                    logger.info(f"[下载] 未按名称匹配，使用备选: {target_apk}")
            
            if not target_apk:
                logger.warning(f"[下载] 未找到 APK 文件 (应用名: {app_name})")
                return False
            
            remote_apk_path = f"{self.hykb_download_dir}{target_apk}"
            local_apk_path = os.path.join(self.temp_dir, target_apk)
            
            logger.info(f"[下载] 目标 APK: {target_apk}")
            
            # 5. 拉取 APK 到本地
            if not self.device_manager.adb_pull(remote_apk_path, local_apk_path):
                logger.error("[下载] 拉取 APK 失败")
                return False
            
            logger.info(f"[下载] 拉取 APK 成功: {local_apk_path}")
            
            # 6. 解析 APK
            logger.info("[解析] 开始解析 APK 信息")
            apk_info = self.parser.parse(
                local_apk_path, 
                extract_icon=True, 
                icon_output_dir=self.icons_dir
            )
            
            if not apk_info or 'package' not in apk_info:
                logger.error("[解析] APK 解析失败")
                return False
            
            logger.info(f"[解析] APK 信息: {apk_info.get('package')} v{apk_info.get('versionName')}")
            
            # 7. 重命名 APK 并上传
            # 将拉取到的 APK 重命名为 包名.apk
            new_local_apk_path = os.path.join(self.temp_dir, f"{apk_info['package']}.apk")
            try:
                if os.path.exists(new_local_apk_path):
                    os.remove(new_local_apk_path)
                os.rename(local_apk_path, new_local_apk_path)
                local_apk_path = new_local_apk_path
                logger.info(f"[下载] 已重命名本地 APK 为: {local_apk_path}")
            except Exception as e:
                logger.warning(f"[下载] 重命名本地 APK 失败: {e}")

            logger.info("[上传] 上传 APK 到 SFTP")
            apk_uploaded = self.uploader.upload_apk(local_apk_path)
            
            if apk_uploaded:
                logger.info("[上传] APK SFTP 传输成功")
            else:
                logger.warning("[上传] APK SFTP 传输失败")
            
            # 8. SFTP 上传 Icon
            icon_path = apk_info.get('local_icon_path') or apk_info.get('icon')
            if icon_path and os.path.exists(icon_path):
                # 重命名 icon 为 包名.ext
                package_name = apk_info.get('package')
                if package_name:
                    ext = os.path.splitext(icon_path)[1]
                    new_icon_path = os.path.join(os.path.dirname(icon_path), f"{package_name}{ext}")
                    try:
                        if os.path.exists(new_icon_path) and os.path.abspath(icon_path) != os.path.abspath(new_icon_path):
                            os.remove(new_icon_path)
                        if os.path.abspath(icon_path) != os.path.abspath(new_icon_path):
                            os.rename(icon_path, new_icon_path)
                            icon_path = new_icon_path
                            logger.info(f"[上传] 已重命名 Icon 为: {icon_path}")
                    except Exception as e:
                        logger.warning(f"[上传] 重命名 Icon 失败: {e}")
                
                logger.info("[上传] 上传 Icon 到 SFTP")
                icon_uploaded = self.uploader.upload_icon(icon_path)
                if icon_uploaded:
                    logger.info("[上传] Icon SFTP 传输成功")
                else:
                    logger.warning("[上传] Icon SFTP 传输失败")
            
            # 9. 构建下载信息
            sftp_cfg = self.config.get('sftp', {})
            remote_dir = sftp_cfg.get('remote_dir', '')
            remote_icon_dir = sftp_cfg.get('remote_icon_dir', '')
            
            # 构建远程 URL
            apk_filename = os.path.basename(local_apk_path)
            icon_filename = os.path.basename(icon_path) if icon_path else None
            
            # 构建符合后端要求的复杂数据结构
            download_info = {
                "app_url": share_url,  # 显式在根部添加 app_url
                "data": {
                    "filename": f"{remote_dir}/{apk_filename}",
                    "md5_hash": apk_info.get('md5'),
                    "package_name": apk_info.get('package'),
                    "version_code": int(apk_info.get('versionCode', 0)) if str(apk_info.get('versionCode', 0)).isdigit() else 0,
                    "version_name": apk_info.get('versionName'),
                    "file_size": apk_info.get('file_size'),
                    "appname": apk_info.get('appname'),
                    "en_app_name": apk_info.get('en_app_name') or apk_info.get('appname'),
                    "server": 151,
                    "type": "download",
                    "status": "success",
                    "app_down_url": f"{remote_dir}/{apk_filename}",
                    "icon_url": f"{remote_icon_dir}/{icon_filename}" if icon_filename else None,
                    "arch": 0,
                    "addtime": int(time.time())
                },
                "task_id": "0",  # 默认 0
                "extra": {
                    "app_url": share_url,
                    "site_id": 0,
                    "rule_id": 0,
                    "page_md5": "",
                    "package_name": apk_info.get('package'),
                    "md5_hash": None,
                    "app_name": apk_info.get('appname'),
                    "app_down_url": f"{remote_dir}/{apk_filename}",
                    "is_use_proxy": 1,
                    "is_auto": 0,
                    "is_vip": False
                }
            }
            
            # 10. API 上报下载信息
            logger.info("[API] 上报下载信息")
            if self.reporter.report_download_info(download_info):
                logger.info("[API] 下载信息上报成功")
            else:
                logger.warning("[API] 下载信息上报失败")
            
            # 11. 清理本地临时文件 (可选)
            # os.remove(local_apk_path)
            
            return True
            
        except Exception as e:
            logger.error(f"[下载] 下载流程异常: {e}")
            return False


def run_hykb(stop_func=None):
    """GUI 调用的核心入口"""
    bot = BotHYKB()
    bot.start(stop_func)

if __name__ == "__main__":
    run_hykb()
