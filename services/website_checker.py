from playwright.async_api import async_playwright
import logging
import requests
import json

class WebsiteChecker:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.llm_api_url = "http://172.16.20.236:9999/chat_llm"

    async def _call_llm(self, prompt):
        """
        调用 LLM 接口进行智能解析。
        """
        try:
            payload = {
                "input_text": prompt,
                "model_type": "doubao_ff2" # 默认使用 doubao_ff2
            }
            response = requests.post(self.llm_api_url, json=payload, timeout=30)
            if response.status_code == 200:
                result = response.json()
                # 适配不同的返回结构：优先寻找 "data" 或 "response" 字段
                if isinstance(result, dict):
                    if "data" in result:
                        return result["data"]
                    if "response" in result:
                        return result["response"]
                return str(result)
            else:
                self.logger.error(f"LLM 接口调用失败: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            self.logger.error(f"调用 LLM 时出现异常: {e}")
            return None

    async def _click_and_capture_download(self, page, target_link):
        """
        尝试在页面中找到 target_link 对应的元素并点击，捕获实际的下载地址。
        """
        self.logger.info(f"正在尝试点击验证链接: {target_link}")
        try:
            # 1. 尝试精确匹配 href
            selector = f'a[href="{target_link}"]'
            element = await page.query_selector(selector)
            
            if not element:
                # 2. 尝试模糊匹配 href 或 text
                links = await page.query_selector_all('a')
                for l in links:
                    href = await l.get_attribute('href')
                    text = await l.inner_text()
                    if href and (target_link in href or href in target_link):
                        element = l
                        break
                    if text and text.strip() and text.strip() in target_link:
                        element = l
                        break
            
            if element:
                self.logger.info("找到对应元素，准备执行点击验证...")
                try:
                    # 滚动到元素位置，确保可见
                    await element.scroll_into_view_if_needed()
                    
                    async with page.expect_download(timeout=10000) as download_info:
                        # 使用 force=True 防止被遮挡
                        await element.click(force=True)
                    
                    download = await download_info.value
                    actual_url = download.url
                    suggested_filename = download.suggested_filename
                    
                    self.logger.info(f"点击成功！捕获到实际下载地址: {actual_url}, 建议文件名: {suggested_filename}")
                    
                    # 验证是否为 APK
                    if suggested_filename.lower().endswith('.apk') or '.apk' in actual_url.lower():
                        return actual_url
                    else:
                        self.logger.warning(f"点击后捕获的文件似乎不是 APK: {suggested_filename}")
                except Exception as e:
                    self.logger.warning(f"点击未触发下载或超时: {e}")
            else:
                self.logger.warning(f"未能在页面上找到可点击的元素: {target_link}")
        except Exception as e:
            self.logger.error(f"执行点击验证时出错: {e}")
        
        return None

    async def find_download_link(self, task):
        """
        智能访问 URL 并结合 LLM 查找匹配的下载链接。
        """
        url = task.get('website')
        current_version = task.get('version_name', "")
        package_name = task.get('package', "")
        keywords = task.get('keywords', [])
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                )
                page = await context.new_page()
                
                self.logger.info(f"正在智能检查网站 (LLM): {url}")
                await page.goto(url, timeout=30000, wait_until='networkidle')
                
                # 1. 提取页面关键信息供 LLM 解析
                page_info = await page.evaluate('''() => {
                    // 获取所有链接
                    const links = Array.from(document.querySelectorAll('a')).map(a => ({
                        text: a.innerText.trim(),
                        href: a.href,
                        title: a.title.trim()
                    })).filter(l => l.href.startsWith('http') && l.text.length > 0);
                    
                    // 获取页面主要文本（前 2000 字）
                    const bodyText = document.body.innerText.substring(0, 2000);
                    
                    return { links, bodyText };
                }''')

                # 2. 构建 LLM Prompt
                prompt = f"""
你是一个专业的网页解析助手。请根据以下提供的网页内容和任务信息，找出最可能的 Android APK 直接下载链接，并判断是否有更新。

注意事项：
1. 优先寻找以 .apk 结尾的链接。
2. 避免选择跳转到其他 HTML 页面、下载器页面或详情页的链接。
3. 如果页面上有多个版本，请选择与目标包名 {package_name} 最相关的 Android 版本。
4. 如果下载链接明显是一个 HTML 页面（如 index.html, download.php 等不带直接文件名的），请谨慎判断。
5. 我们会尝试点击你提供的链接来捕获实际的 APK 下载地址，所以请务必提供那个能触发下载的 <a> 标签的 href。

任务信息:
- 目标包名: {package_name}
- 当前版本: {current_version}
- 搜索关键字: {', '.join(keywords)}
- 网页 URL: {url}

网页链接列表:
{json.dumps(page_info['links'][:100], ensure_ascii=False, indent=2)}

网页文本摘要:
{page_info['bodyText']}

请分析后按以下 JSON 格式返回结果（仅返回 JSON）：
{{
  "download_link": "找到的 APK 直接下载链接（必须是直接触发下载的文件地址），没找到则为空字符串",
  "version_found": "页面上发现的版本号，没发现则为空",
  "has_update": true/false,
  "reason": "判断依据简述，如果下载链接可能不是直接 APK 请注明"
}}
"""
                # 3. 调用 LLM
                llm_response_raw = await self._call_llm(prompt)
                if llm_response_raw:
                    try:
                        # 尝试提取 JSON 部分
                        json_start = llm_response_raw.find('{')
                        json_end = llm_response_raw.rfind('}') + 1
                        if json_start >= 0 and json_end > 0:
                            llm_result = json.loads(llm_response_raw[json_start:json_end])
                            
                            download_link = llm_result.get('download_link')
                            self.logger.info(f"LLM 解析建议链接: {download_link}")
                            
                            if download_link:
                                # --- 使用点击验证逻辑 ---
                                actual_url = await self._click_and_capture_download(page, download_link)
                                if actual_url:
                                    return {
                                        "download_link": actual_url,
                                        "version_found": llm_result.get('version_found'),
                                        "has_update": llm_result.get('has_update', True),
                                        "reason": f"点击验证成功: {llm_result.get('reason')}"
                                    }
                                # --- 点击验证结束 ---

                                return {
                                    "download_link": download_link,
                                    "version_found": llm_result.get('version_found'),
                                    "has_update": llm_result.get('has_update', True),
                                    "reason": llm_result.get('reason')
                                }
                    except Exception as e:
                        self.logger.error(f"解析 LLM 返回结果失败: {e}, 原始响应: {llm_response_raw}")

                # 4. 兜底逻辑：如果 LLM 失败，使用原有的正则匹配逻辑
                self.logger.warning("LLM 解析未获得结果，使用传统匹配逻辑兜底")
                all_links = page_info['links']
                for link in all_links:
                    href = link.get('href')
                    if not href or href.startswith('javascript:') or not href.startswith('http'):
                        continue
                    
                    link_text = (link.get('text') or "").lower()
                    link_title = (link.get('title') or "").lower()
                    
                    is_match_kw = any(kw.lower() in link_text or kw.lower() in link_title for kw in keywords)
                    if is_match_kw:
                        # 兜底逻辑也尝试点击验证
                        actual_url = await self._click_and_capture_download(page, href)
                        return {
                            "download_link": actual_url if actual_url else href,
                            "version_found": None,
                            "has_update": True, # 传统模式默认尝试更新
                            "reason": f"传统关键字匹配{' (点击验证成功)' if actual_url else ''}"
                        }
                            
                return None
                
            except Exception as e:
                self.logger.error(f"检查网站 {url} 时出错: {e}")
                return None
            finally:
                await browser.close()

    async def get_file_size(self, url):
        """
        使用 HEAD 请求获取文件大小 (字节)。
        """
        try:
            # 允许重定向
            response = requests.head(url, allow_redirects=True, timeout=10)
            if 'Content-Length' in response.headers:
                return int(response.headers['Content-Length'])
            
            # 如果缺少 Content-Length，尝试范围请求
            response = requests.get(url, headers={'Range': 'bytes=0-10'}, stream=True, timeout=10)
            if 'Content-Range' in response.headers:
                # Content-Range: bytes 0-10/123456
                content_range = response.headers['Content-Range']
                total_size = content_range.split('/')[-1]
                return int(total_size)
                
            self.logger.warning(f"无法确定 {url} 的大小")
            return 0
        except Exception as e:
            self.logger.error(f"获取 {url} 的大小时出错: {e}")
            return 0
