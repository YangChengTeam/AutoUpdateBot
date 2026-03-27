import os
import sys
import time
import logging
import re

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
logger = logging.getLogger("7723Bot")

class Bot7723:
    def __init__(self):
        setup_env()  # 初始化环境（加载本地 ADB 路径）
        self.config = self._get_config()
        serial = self.config.get('emulator', {}).get('serial', '127.0.0.1:7555')
        self.device_manager = DeviceManager(serial)
        self.d = self.device_manager.d
        self.reporter = ReportService(self.config.get('api', {}))
        self.package_name = "com.upgadata.up7723"
        self.processed_titles = set()
        self._init_daily_log()

    def _init_daily_log(self):
        """初始化每日日志目录"""
        base_path = self._get_base_path()
        self.log_dir = os.path.join(base_path, "logs", "7723")
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
        # 7723 的详情页 Activity 名称，支持游戏详情页和社区详情页
        return "DetailGameActivity" in activity or "UpTalkDetailActivity" in activity

    def is_mod_page(self, activity=None):
        """判断是否在 MOD 页面的最新标签"""
        if activity is None:
            activity = self.get_activity()
        
        # 允许在 HomeActivity 或者是 NewClassicTagGameActivity
        if "NewClassicTagGameActivity" not in activity:
            logger.debug(f"is_mod_page: 当前 Activity 不是 NewClassicTagGameActivity (当前: {activity})")
            return False
            
        # 然后检查"最新"标签是否为选中状态
        latest_tab = self.d(text="最新")
        if latest_tab.exists:
            try:
                selected = latest_tab.info.get('selected', False)
                logger.debug(f"is_mod_page: 找到'最新'标签, selected={selected}")
                return selected
            except Exception as e:
                logger.warning(f"is_mod_page: 获取标签状态异常: {e}")
                # 兜底：如果已经在 Activity 但获取不到选中状态，视为已在页面
                return True
        
        return True

    def start(self, stop_func=None):
        logger.info("正在启动 7723 应用...")
        self.d.app_start(self.package_name, stop=True)
        time.sleep(5)
        
        while True:
            if stop_func and stop_func():
                logger.info("检测到停止信号，退出主循环...")
                break

            activity = self.get_activity()
            
            # 处理可能出现的弹窗
            self.handle_popups()
            
            # 检测是否在 MOD 页面
            if self.is_mod_page(activity):
                logger.info("检测到已进入【MOD-最新】页面，开始采集...")
                self.loop_crawl(stop_func)
                break
            else:
                logger.info(f"当前不在【MOD-最新】页面 (当前 Activity: {activity})，尝试自动导航...")
                self.handle_popups()
                if not self.navigate_to_mod():
                    logger.warning("自动导航失败，请手动切换到【MOD-最新】页面...")
                    time.sleep(5)

    def navigate_to_mod(self):
        """导航到 MOD -> 最新 页面"""
        activity = self.get_activity()
        logger.info(f"开始导航到 MOD 页面 (当前 Activity: {activity})")
        
        # 0. 如果已经在页面，直接返回成功
        if self.is_mod_page(activity):
            logger.info("确认已在【MOD-最新】页面")
            return True
        
        # 1. 处理弹窗
        self.handle_popups()
        
        # 2. 如果在 HomeActivity，点击 MOD
        if "HomeActivity" in activity:
            mod_btn = self.d(resourceId="com.upgadata.up7723:id/header_home_text_name", text="MOD")
            if mod_btn.exists:
                logger.info("点击主页【MOD】按钮")
                mod_btn.click()
                time.sleep(3)
                activity = self.get_activity()
            else:
                logger.warning("未能在主页找到【MOD】按钮")
        
        # 3. 如果在 NewClassicTagGameActivity，点击 最新
        if "NewClassicTagGameActivity" in activity:
            latest_btn = self.d(text="最新")
            if latest_btn.exists:
                logger.info("点击【最新】标签")
                latest_btn.click()
                time.sleep(2)
                
                # 检查最新标签是否变为选中状态
                if self.is_mod_page():
                    logger.info("成功进入【MOD-最新】页面")
                    return True
                else:
                    logger.warning("已点击【最新】但检测结果仍为 False")
            else:
                logger.warning("在 NewClassicTagGameActivity 未找到【最新】按钮")
        
        logger.warning(f"导航结束，未检测到成功进入目标页面 (当前 Activity: {activity})")
        return False

    def handle_popups(self):
        """处理可能出现的弹窗 (同意、知道了等)"""
        # 1. 强行检查包名，如果跳出了应用则切回
        try:
            current = self.d.app_current()
            if current.get('package') != self.package_name:
                logger.warning(f"检测到离开应用 (当前: {current.get('package')})，强行切回...")
                self.d.app_start(self.package_name)
                time.sleep(2)
        except:
            pass

        # 2. 处理通用弹窗
        popups = ["同意", "知道了", "我知道了", "跳过", "始终允许", "以后再说", "取消", "关闭", "Skip", "Close"]
        for p in popups:
            try:
                btn = self.d(text=p)
                if btn.exists(timeout=1):
                    logger.info(f"点击弹窗按钮: {p}")
                    btn.click()
                    time.sleep(1)
            except:
                pass

    def back_to_home(self):
        """返回到主页 Activity"""
        for _ in range(8):
            self.handle_popups()
            activity = self.get_activity()
            if "HomeActivity" in activity:
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
            
            if not self.navigate_to_mod():
                logger.warning("重新导航失败，尝试重置应用...")
                self.d.app_start(self.package_name, stop=True)
                time.sleep(5)
                self.navigate_to_mod()
            
            if found_old_data:
                logger.info("由于发现旧数据，立即开始下一轮采集循环...")
                continue
            
            # 如果没有发现旧数据（可能是列表到底了），等待一段时间
            logger.info("本轮处理完毕，等待 60 秒后开始下一轮...")
            for _ in range(60):
                if stop_func and stop_func():
                    return
                time.sleep(1)


    def _swipe_up(self):
        """上拉滑动"""
        self.d.swipe_ext("up", scale=0.8)
        time.sleep(1)

    def _swipe_up_detail(self):
        """详情页专用的精确垂直滑动（避免触发 tab 切换）"""
        # 使用屏幕中心位置进行精确垂直滑动
        screen_width = self.d.info['displayWidth']
        screen_height = self.d.info['displayHeight']
        
        # 从屏幕中心偏下位置向上滑动，保持 X 坐标不变
        start_x = screen_width // 2
        start_y = int(screen_height * 0.7)  # 从屏幕 70% 高度开始
        end_y = int(screen_height * 0.3)    # 滑动到屏幕 30% 高度
        
        self.d.swipe(start_x, start_y, start_x, end_y, duration=0.3)
        time.sleep(0.8)


    def _scroll_to_last_item(self, last_title=None):
        """通过切换 tab 重置列表位置，然后滚动到上次处理的项目"""
        # 先点击"最热"再点击"最新"，可以重置列表
        try:
            hottest_btn = self.d(text="最热")
            if hottest_btn.exists:
                hottest_btn.click()
                time.sleep(0.5)
            
            latest_btn = self.d(text="最新")
            if latest_btn.exists:
                latest_btn.click()
                time.sleep(1)
        except Exception as e:
            logger.debug(f"切换 tab 失败: {e}")
        
        if not last_title:
            return True
        
        # 滚动直到找到上次处理的项目
        for i in range(15):  # 最多滚动15次
            # 查找是否有该标题
            title_elem = self.d(resourceId="com.upgadata.up7723:id/item_game_normal_title", text=last_title)
            if title_elem.exists:
                try:
                    bounds = title_elem.info.get('visibleBounds', {})
                    if bounds.get('top', 0) > 0:
                        logger.info(f"找到上次处理的项目【{last_title}】")
                        return True
                except:
                    pass
            
            # 继续滚动
            self._swipe_up()
            time.sleep(0.5)
        
        logger.info(f"未找到上次处理的项目【{last_title}】，可能已滚过，继续采集")
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
            
            # 必须在目标页面才能点击
            if not self.is_mod_page():
                logger.warning(f"当前不在 MOD 页面 (Activity: {self.get_activity()})，尝试导航...")
                self.handle_popups()
                if not self.navigate_to_mod():
                    logger.error("无法进入 MOD 页面，跳出本轮循环")
                    return False

            # 直接查找所有的标题元素
            title_items = self.d(resourceId="com.upgadata.up7723:id/item_game_normal_title")
            
            if not title_items.exists:
                logger.warning("未能找到列表项标题")
                self._swipe_up()
                time.sleep(1)
                continue

            current_screen_last_title = None
            item_count = title_items.count
            logger.info(f"当前屏幕找到 {item_count} 个标题元素")
            
            for i in range(item_count):
                if stop_func and stop_func():
                    return False

                if not self.is_mod_page():
                    break

                try:
                    # 重新获取元素列表（因为返回后页面可能刷新）
                    title_items = self.d(resourceId="com.upgadata.up7723:id/item_game_normal_title")
                    if i >= title_items.count:
                        logger.info(f"索引 {i} 超出当前元素数量 {title_items.count}，等待下一页")
                        break
                    
                    title_elem = title_items[i]
                    
                    # 获取标题文本
                    title = title_elem.get_text() if title_elem.exists else "未知应用"
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
                    if not self.is_mod_page():
                        self.navigate_to_mod()

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
        # 滚动查找"更新时间"元素
        update_time_title = None
        for i in range(6):
            self.handle_popups()
            
            # 查找"更新时间"标题元素
            update_time_title = self.d(resourceId="com.upgadata.up7723:id/text_title", text="更新时间")
            if update_time_title.exists:
                # 检查元素是否在屏幕内
                if update_time_title.info['visibleBounds']['top'] < self.d.info['displayHeight']:
                    break
            
            if i < 5:
                logger.info(f"未找到【更新时间】元素，正在进行第 {i+1} 次向下滑动查找...")
                self._swipe_up_detail()  # 使用详情页专用滑动，避免切换 tab
                time.sleep(1.5)

        # 获取更新时间的值 (在 text_title="更新时间" 下面的 text_content)
        # 由于页面可能有多个 text_content，需要找到"更新时间"标题对应的那个
        time_text = None
        if update_time_title and update_time_title.exists:
            try:
                # 方法1: 通过父元素找到同级的 text_content
                parent = update_time_title.sibling(resourceId="com.upgadata.up7723:id/text_content")
                if parent.exists:
                    time_text = parent.get_text()
                    logger.info(f"检测到更新时间文本 (sibling): {time_text}")
            except Exception as e:
                logger.debug(f"sibling 方法失败: {e}")
            
            if not time_text:
                try:
                    # 方法2: 获取更新时间标题的位置，找到下方最近的 text_content
                    title_bounds = update_time_title.info.get('bounds', {})
                    if title_bounds:
                        title_bottom = title_bounds.get('bottom', 0)
                        title_left = title_bounds.get('left', 0)
                        title_right = title_bounds.get('right', 0)
                        
                        # 查找所有 text_content 元素
                        all_contents = self.d(resourceId="com.upgadata.up7723:id/text_content")
                        for content in all_contents:
                            try:
                                content_bounds = content.info.get('bounds', {})
                                if content_bounds:
                                    content_top = content_bounds.get('top', 0)
                                    content_left = content_bounds.get('left', 0)
                                    # 检查是否在标题下方且水平位置接近
                                    if content_top >= title_bottom - 10 and abs(content_left - title_left) < 50:
                                        time_text = content.get_text()
                                        logger.info(f"检测到更新时间文本 (位置匹配): {time_text}")
                                        break
                            except:
                                continue
                except Exception as e:
                    logger.debug(f"位置匹配方法失败: {e}")
        
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

    def _convert_share_url(self, raw_url):
        """
        将原始分享链接转换为标准格式
        例如: http://s.7723.cn/202602111211/468a777da347a7a475c3b5b00d09dcce/game/152054/flag/1
        转换为: https://www.7723.cn/apps/152054
        """
        if not raw_url:
            return None
        
        # 从 URL 中提取 game ID
        # 兼容 /game/、/apps/ 路径，以及以 /、.html 或字符串末尾结尾的情况
        match = re.search(r'/(?:game|apps)/(\d+)(?:/|\.|$)', raw_url)
        if match:
            game_id = match.group(1)
            converted_url = f"https://www.7723.cn/apps/{game_id}"
            logger.info(f"URL 转换: {raw_url} -> {converted_url}")
            return converted_url
        else:
            logger.warning(f"无法从 URL 中提取游戏 ID: {raw_url}")
            return raw_url  # 返回原始链接作为兜底

    def perform_share(self):
        """执行分享操作，获取链接并上报"""
        # 1. 点击"更多"按钮
        more_btn = self.d.xpath('//*[@resource-id="com.upgadata.up7723:id/more"]')
        if more_btn.exists:
            logger.info("点击【更多】按钮")
            more_btn.click()
            time.sleep(2)
            
            # 2. 点击"复制链接"
            copy_url_btn = self.d.xpath('//*[@resource-id="com.upgadata.up7723:id/subject_copy_url"]')
            if copy_url_btn.exists:
                logger.info("点击【复制链接】按钮")
                copy_url_btn.click()
                time.sleep(1)
                
                # 3. 从剪贴板获取链接
                raw_url = self.d.clipboard
                logger.info(f"获取到原始分享链接: {raw_url}")
                
                # 4. 转换 URL 格式
                share_url = self._convert_share_url(raw_url)
                
                # 5. 上报
                if share_url:
                    self.reporter.report_app_urls([share_url])
                    
                    # 6. 记录到每日日志
                    self._write_to_daily_log(self.current_title, share_url)
                    return True
                else:
                    logger.warning("剪贴板为空，获取链接失败")
            else:
                logger.warning("未能找到【复制链接】按钮")
                self.d.press("back")
        else:
            logger.warning("未能找到【更多】按钮")

        return False


def run_7723(stop_func=None):
    """GUI 调用的核心入口"""
    bot = Bot7723()
    bot.start(stop_func)

if __name__ == "__main__":
    run_7723()
