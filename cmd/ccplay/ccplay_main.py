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
logger = logging.getLogger("CCPlayBot")

class CCPlayBot:
    def __init__(self):
        setup_env()  # 初始化环境（加载本地 ADB 路径）
        self.config = self._get_config()
        serial = self.config.get('emulator', {}).get('serial', '127.0.0.1:7555')
        self.device_manager = DeviceManager(serial)
        self.d = self.device_manager.d
        self.reporter = ReportService(self.config.get('api', {}))
        self.package_name = "com.lion.market"
        self.processed_titles = set()
        self._init_daily_log()

    def _init_daily_log(self):
        """初始化每日日志目录"""
        base_path = self._get_base_path()
        self.log_dir = os.path.join(base_path, "logs")
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
        return "GameDetailActivity" in activity or "GameOpenDetailActivity" in activity

    def is_list_page(self, activity=None):
        """判断是否在列表页"""
        if activity is None:
            activity = self.get_activity()
        return "LatelyUpdateActivity" in activity

    def start(self, stop_func=None):
        logger.info("正在启动 CCPlay...")
        self.d.app_start(self.package_name, stop=True)
        time.sleep(5)
        
        while True:
            if stop_func and stop_func():
                logger.info("检测到停止信号，退出主循环...")
                break

            activity = self.get_activity()
            
            # 检测是否在最近更新页面
            if self.is_list_page(activity) or self.d(text="最近更新").exists:
                logger.info("检测到已进入【最近更新】页面，开始采集...")
                self.loop_crawl(stop_func)
                break
            else:
                logger.info(f"当前不在【最近更新】页面 (当前 Activity: {activity})，尝试自动导航...")
                self.handle_ads()
                if not self.navigate_to_recent_updates():
                    logger.warning("自动导航失败，请手动切换到【最近更新】页面...")
                    time.sleep(5)

    def navigate_to_recent_updates(self):
        """从主页点击发现并找到最近更新入口"""
        activity = self.get_activity()
        
        # 0. 如果已经在列表页，直接返回成功
        if self.is_list_page(activity):
            logger.info("已在【最近更新】列表页")
            return True
        
        # 1. 确保在主页
        if "MainActivity" not in activity:
            logger.info("不在主页，尝试返回...")
            self.d.press("back")
            time.sleep(2)
            activity = self.get_activity()
            # 再次检查是否已到列表页
            if self.is_list_page(activity):
                return True

        # 2. 关闭弹窗并点击"发现"
        self.handle_ads()
        discover_btn = self.d(text="发现")
        if discover_btn.exists:
            logger.info("点击【发现】标签")
            discover_btn.click()
            time.sleep(2)
        
        # 3. 先下拉回到发现页顶部（确保能找到最近更新入口）
        logger.info("下拉回到发现页顶部...")
        for _ in range(3):
            self.d.swipe_ext("down", scale=0.8)
            time.sleep(0.3)
        time.sleep(1)
        
        # 4. 查找"最近更新"入口（不需要滚动太多次，因为入口通常在顶部附近）
        title_text = "最近更新（新游+版本更新）"
        logger.info(f"正在查找【{title_text}】入口...")
        
        for i in range(5):  # 最多滚动 5 次
            self.handle_ads()
            
            # 尝试通过文本定位标题
            title = self.d(text=title_text)
            if title.exists:
                # 尝试找到标题旁边的"更多"按钮（通过父容器定位）
                try:
                    # 获取标题的父容器，然后在父容器内查找"更多"按钮
                    parent = title.parent()
                    if parent.exists:
                        more_btn = parent.child(text="更多")
                        if more_btn.exists:
                            logger.info("找到并点击【更多】进入列表（通过父容器定位）")
                            more_btn.click()
                            time.sleep(3)
                            if self.is_list_page():
                                return True
                except Exception as e:
                    logger.debug(f"父容器定位失败: {e}")
                
                # 备选方案：使用 XPath 定位同一行的"更多"按钮
                try:
                    # 获取标题的边界
                    title_info = title.info
                    title_bounds = title_info.get('bounds', {})
                    if title_bounds:
                        title_top = title_bounds.get('top', 0)
                        title_bottom = title_bounds.get('bottom', 0)
                        
                        # 查找所有"更多"按钮，找到与标题在同一行的那个
                        more_buttons = self.d(text="更多")
                        for more_btn in more_buttons:
                            try:
                                more_info = more_btn.info
                                more_bounds = more_info.get('bounds', {})
                                if more_bounds:
                                    more_top = more_bounds.get('top', 0)
                                    more_bottom = more_bounds.get('bottom', 0)
                                    # 检查是否在同一水平线上（Y坐标有重叠）
                                    if more_top < title_bottom and more_bottom > title_top:
                                        logger.info("找到并点击【更多】进入列表（通过坐标匹配）")
                                        more_btn.click()
                                        time.sleep(3)
                                        if self.is_list_page():
                                            return True
                                        break
                            except:
                                continue
                except Exception as e:
                    logger.debug(f"坐标匹配定位失败: {e}")
                
                # 最后备选：直接点击标题
                logger.info("点击【最近更新】标题")
                title.click()
                time.sleep(3)
                if self.is_list_page():
                    return True
            
            if i < 4:
                logger.info(f"未找到目标，进行第 {i+1} 次向下滚动...")
                self._swipe_up()
                time.sleep(1)
            
        return False

    def loop_crawl(self, stop_func=None):
        while True:
            if stop_func and stop_func():
                logger.info("检测到停止信号，退出循环...")
                break

            logger.info("开始新一轮采集循环...")
            
            # 每轮循环前重新加载当天日志，确保日期切换时使用正确的记录
            self._reload_daily_records()
            
            try:
                self.process_list(stop_func)
            except Exception as e:
                logger.error(f"处理列表时出错: {e}")

            # 如果在详情页，先返回列表页
            if self.is_detail_page():
                logger.info("当前位于详情页，返回列表...")
                self.d.press("back")
                time.sleep(1.5)
            
            # 不再使用下拉刷新，而是返回上一页再重新进入来刷新数据
            logger.info("返回上一页，准备重新进入【最近更新】页面...")
            self.d.press("back")
            time.sleep(2)
            
            # 重新导航到【最近更新】页面
            logger.info("正在重新导航到【最近更新】页面...")
            if not self.navigate_to_recent_updates():
                logger.warning("重新导航失败，尝试再次导航...")
                time.sleep(2)
                self.navigate_to_recent_updates()
            
            time.sleep(1.5)
            
            # 优化等待，支持快速中止
            logger.info("等待 60 秒后开始下一轮...")
            for _ in range(60):
                if stop_func and stop_func():
                    return
                time.sleep(1)

    def _swipe_up(self):
        """上拉滑动"""
        self.d.swipe_ext("up", scale=0.8)
        time.sleep(1)

    def handle_ads(self):
        """处理特定的广告弹窗"""
        # 1. 强行检查包名，如果跳出了应用则切回
        try:
            current = self.d.app_current()
            if current.get('package') != self.package_name:
                logger.warning(f"检测到离开应用 (当前: {current.get('package')})，强行切回...")
                self.d.app_start(self.package_name)
                time.sleep(2)
        except:
            pass

        activity = self.get_activity()
        
        # 2. 处理特定的广告 Activity
        if "PortraitTransparentAdActivity" in activity or "FullScreenWebViewActivity" in activity:
            logger.info(f"检测到广告 Activity ({activity})，进行坐标闭合...")
            # 使用用户提供的准确坐标
            user_coords = [
                (0.905, 0.061),
                (0.866, 0.227),
                (0.778, 0.127),
                (0.974, 0.407)
            ]
            for x, y in user_coords:
                logger.info(f"点击用户坐标: ({x}, {y})")
                self.d.click(x, y)
                time.sleep(1)
                if self.get_activity() != activity:
                    break
            
            # 如果还没关掉，尝试 Back
            if self.get_activity() == activity:
                logger.info("坐标点击后仍处于广告页，尝试发送 Back...")
                self.d.press("back")
                time.sleep(1)

        # 3. 处理特定页面的弹窗 (如主页、详情页)
        main_ad_close = self.d(resourceId="com.lion.market:id/dlg_main_ad_close")
        if main_ad_close.exists:
            logger.info("检测到主页广告弹窗，点击 ID 关闭...")
            main_ad_close.click()
            time.sleep(1)

        detail_interstitial_close = self.d.xpath('//*[@resource-id="com.lion.market:id/xml_interstitial_tv_close_cd"]')
        if detail_interstitial_close.exists:
            logger.info("检测到详情页插屏广告，点击关闭...")
            detail_interstitial_close.click()
            time.sleep(1)

        special_ad_close = self.d.xpath('//*[@resource-id="com.lion.market:id/dlg_special_close"]/android.widget.ImageView[1]')
        if special_ad_close.exists:
            logger.info("检测到特别广告弹窗，点击 XPath 关闭...")
            special_ad_close.click()
            time.sleep(1)

        floating_ball_close = self.d.xpath('//*[@resource-id="com.lion.market:id/layout_home_choice_floating_ball_close"]')
        if floating_ball_close.exists:
            logger.info("检测到悬浮球广告，点击关闭...")
            floating_ball_close.click()
            time.sleep(1)

        # 4. 通用弹窗处理 (文本匹配)
        popups = ["跳过", "始终允许", "以后再说", "取消", "我知道了", "知道了", "同意", "关闭", "Skip", "Close"]
        for p in popups:
            try:
                btn = self.d(text=p)
                if btn.exists(timeout=1):
                    logger.info(f"点击通用弹窗按钮: {p}")
                    btn.click()
                    time.sleep(1)
            except:
                pass

    def process_list(self, stop_func=None):
        found_old_data = False
        is_first_loop = True # 用于标识是否为本轮采集的第一次获取列表
        last_element_title = None  # 追踪最后一个可见元素的标题
        last_element_count = 0  # 最后元素重复出现的次数
        max_repeat_count = 3  # 最多允许重复出现 3 次，超过则认为到达底部

        while not found_old_data:
            if stop_func and stop_func():
                return False
            
            # 必须是列表才能点击
            if not self.is_list_page():
                logger.warning(f"当前不在列表页 (Activity: {self.get_activity()})，尝试回退...")
                self.handle_ads()
                self.d.press("back")
                time.sleep(1.5)
                if not self.is_list_page():
                    logger.error("无法返回列表页，跳出本轮循环")
                    return False # 异常退出

            # 获取列表项
            # 优先使用结构化定位：loading_layout -> RecyclerView -> RelativeLayout
            items = self.d(resourceId="com.lion.market:id/loading_layout").child(className="androidx.recyclerview.widget.RecyclerView").child(className="android.widget.RelativeLayout")
            
            if not items.exists:
                items = self.d(resourceId="com.lion.market:id/rl_root")
            
            if not items.exists:
                items = self.d(className="android.widget.RelativeLayout", clickable=True)

            current_visible_processed = 0
            is_first_item_in_screen = True # 屏幕内的第一个元素
            current_screen_last_title = None  # 当前屏幕最后一个有效元素的标题

            for item in items:
                # 检查停止信号
                if stop_func and stop_func():
                    return False

                # 每一步判断 activity，确保仍在列表页
                if not self.is_list_page():
                    break

                try:
                    # 获取元素信息以判断高度
                    info = item.info
                    bounds = info.get('bounds', {})
                    if bounds:
                        width = bounds['right'] - bounds['left']
                        logger.info(f"元素宽度: {width}")
                        if width <= 300:
                            logger.info(f"跳过宽度为 {width} 的元素 (可能是分割线或广告)")
                            continue

                    # 尝试获取标题作为标识符
                    title_view = item.child(resourceIdMatches=".*title.*") or item.child(className="android.widget.TextView")
                    title = "未知应用"
                    if title_view.exists:
                        title = title_view.get_text()
                        
                        # 记录当前屏幕处理到的最后一个标题（用于底部检测）
                        if title and title != "未知应用":
                            current_screen_last_title = title
                        
                        is_first_item_in_screen = False

                        if title in self.processed_titles:
                            logger.info(f"应用【{title}】已在历史记录中，跳过并继续检查...")
                            continue
                        self.processed_titles.add(title)
                        # 限制缓存大小，防止内存占用过大（保留最近 500 个）
                        if len(self.processed_titles) > 500:
                            # Set 是无序的，如果需要精确 FIFO，这里可能需要改成 list 或 OrderedDict
                            # 但对于去重来说，500 个足以覆盖常规更新列表
                            pass 
                    
                    logger.info(f"正在检查: {title}")
                    self.current_title = title # 保存当前处理的标题用于日志记录
                    item.click()
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
                    else:
                        logger.warning(f"点击项目后未进入详情页 (当前: {self.get_activity()})")

                    current_visible_processed += 1
                    
                    if found_old_data:
                        break
                except Exception as e:
                    logger.error(f"处理项目时出错: {e}")
                    if not self.is_list_page():
                        self.d.press("back")

            # 底部检测：检查最后一个元素是否重复出现
            if current_screen_last_title:
                if current_screen_last_title == last_element_title:
                    last_element_count += 1
                    logger.info(f"检测到最后元素【{current_screen_last_title}】重复出现 {last_element_count}/{max_repeat_count} 次")
                    if last_element_count >= max_repeat_count:
                        logger.info(f"【底部检测】最后元素连续出现 {max_repeat_count} 次，已到达列表底部，结束本轮采集")
                        break  # 退出 while 循环，进入下一轮采集
                else:
                    last_element_title = current_screen_last_title
                    last_element_count = 1

            if current_visible_processed == 0 and not found_old_data:
                logger.warning("当前页面未发现新项目，尝试翻页...")
                self._swipe_up()
                time.sleep(2)
            
            if not found_old_data:
                self._swipe_up()
                is_first_loop = False # 第一次获取并处理/判断完首个元素后，后续翻页不再判断首个元素
                time.sleep(2)
        
        return found_old_data

    def check_and_share(self):
        """判断是否为‘今天’更新，若是则执行分享。"""
        # 使用用户提供的特定资源 ID 检测时间
        time_id = "com.lion.market:id/fragment_game_detail_company_info_layout_update"
        
        time_view = None
        # 添加滑动查找逻辑，增加滑动幅度到 0.8，最多滑动 5 次
        for i in range(6):
            self.handle_ads()
            time_view = self.d(resourceId=time_id)
            if time_view.exists:
                # 检查元素是否在屏幕内（有时 exists 但在屏幕外）
                if time_view.info['visibleBounds']['top'] < self.d.info['displayHeight']:
                    break
            
            if i < 5:
                logger.info(f"未找到时间元素，正在进行第 {i+1} 次大幅度向下滑动查找...")
                self._swipe_up()
                time.sleep(1.5)

        if time_view and time_view.exists:
            time_text = time_view.get_text()
            logger.info(f"检测到更新时间文本: {time_text}")
            
            # 始终使用当前日期作为采集过滤条件
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
                    return False

            # 2. 关键词处理 (今天, 小时前, 分钟前)
            today_str = time.strftime("%Y-%m-%d")
            is_recent = any(kw in time_text for kw in ["今天", "小时前", "分钟前"])
            
            if is_recent:
                # 关键词通常代表“今天”
                if today_str >= min_date_str:
                    return self.perform_share()
                else:
                    logger.info(f"【过滤】最近更新但今天早于起始日期 {min_date_str}")
                    return False
            
            # 3. 兜底匹配 (如果文本不含日期也不含关键词，尝试完全匹配配置日期)
            if min_date_str in time_text:
                return self.perform_share()
        else:
            logger.warning(f"滑动查找后仍未找到资源 ID {time_id}，尝试备选文本检测...")
            # 备选：详情页通用的更新时间文本
            time_view_alt = self.d(textContains="更新时间") or self.d(textContains="时间：")
            if time_view_alt.exists:
                time_text = time_view_alt.get_text()
                logger.info(f"详情页备选时间文本: {time_text}")
                
                min_date_str = time.strftime("%Y-%m-%d")
                
                # 优先匹配日期
                date_match = re.search(r"\d{4}-\d{2}-\d{2}", time_text)
                if date_match:
                    app_date_str = date_match.group()
                    if app_date_str >= min_date_str:
                        return self.perform_share()
                    return False

                # 匹配关键词
                if any(kw in time_text for kw in ["今天", "小时前", "分钟前"]) or min_date_str in time_text:
                    return self.perform_share()

        # 最终也没找到日期元素，或者备选也匹配失败
        return None

    def perform_share(self):
        # 1. 点击分享图标 (使用用户提供的特定 XPath)
        # 有时是 ImageView[3]，有时是 ImageView[2]
        share_btn = None
        for idx in [3, 2]:
            xpath = f'//*[@resource-id="com.lion.market:id/ActionbarMenuLayout"]/android.widget.ImageView[{idx}]'
            btn = self.d.xpath(xpath)
            if btn.exists:
                share_btn = btn
                break
        if share_btn:
            share_btn.click()
            time.sleep(2)
            
            # 2. 点击“复制链接” (使用用户提供的特定 XPath)
            copy_xpath = '//*[@resource-id="com.lion.market:id/layout_recycleview"]/android.widget.LinearLayout[5]/android.widget.ImageView[1]'
            copy_btn = self.d.xpath(copy_xpath)
            if not copy_btn.exists:
                # 备选方案：通过文本查找
                copy_btn = self.d(text="复制链接")

            if copy_btn.exists:
                copy_btn.click()
                time.sleep(1)
                
                # 3. 从剪贴板获取链接
                share_url = self.d.clipboard
                logger.info(f"获取到分享链接: {share_url}")
                
                # 4. 尝试获取包名
                target_pkg = "unknown"
                pkg_view = self.d(textContains="包名：") or self.d(textContains="com.") 
                if pkg_view.exists:
                    target_pkg = pkg_view.get_text().replace("包名：", "").strip()

                # 5. 上报
                if "wap." in share_url:
                    share_url = share_url.replace("wap.", "www.")
                self.reporter.report_app_urls([share_url])
                
                # 6. 记录到每日日志
                self._write_to_daily_log(self.current_title, share_url)
                return True
            else:
                logger.warning("未能在分享菜单中找到‘复制链接’按钮")
                self.d.press("back")
        else:
            logger.warning("由于点击分享图标失败，尝试备选方案...")
            share_btn_alt = self.d(description="分享") or self.d(resourceIdMatches=".*share.*") or self.d(resourceIdMatches=".*iv_more.*")
            if share_btn_alt.exists:
                share_btn_alt.click()
                time.sleep(2)
                if self.d(text="复制链接").exists:
                    self.d(text="复制链接").click()
                    return True

        return False

def run_ccplay(stop_func=None):
    """GUI 调用的核心入口"""
    bot = CCPlayBot()
    bot.start(stop_func)

if __name__ == "__main__":
    run_ccplay()
