import logging
import os
import asyncio
from typing import Optional, List
from urllib.parse import urlparse
import re
import hashlib
import sys
import time
import subprocess

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.utils import delete_file

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)

class DownloadService:
    """简化的下载服务类"""
    
    _instance: Optional['DownloadService'] = None

    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化下载服务"""
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = True
        
        # 配置路径
        self._download_dir = os.getenv('TEMP_DIR', 'temp')
        os.makedirs(self._download_dir, exist_ok=True)
    
    @classmethod
    def get_instance(cls) -> 'DownloadService':
        """获取服务实例"""
        return cls()
    
    # 获取aria2c命令
    def _get_aria2_command(self, url: str, filename: str, user_agent: str, proxy: str) -> List[str]:
        """获取aria2c命令"""
        # 从URL提取域名作为Referer
        parsed_url = urlparse(url)
        domain = f"{parsed_url.scheme}://{parsed_url.netloc}"
                
        # 构建基础参数列表
        params = ['aria2c']
        
        # 请求头设置
        params.extend([
            f'--header=Referer: {domain}',
            f'--header=User-Agent: {user_agent}',
        ])
        
        # 代理设置
        if proxy:
            params.extend([
                f'--all-proxy={proxy}',
                '--proxy-method=tunnel',
            ])
        
        # 网络连接参数
        params.extend([
            '--timeout=60',                    # 超时时间
            '--connect-timeout=10',            # 连接超时
            '--retry-wait=2',                  # 重试间隔
            '--max-tries=5',                   # 重试次数
            '--lowest-speed-limit=1K',         # 最低速度限制
            '--max-resume-failure-tries=3',    # 断点续传重试次数
        ])
        
        # 连接和并发控制
        params.extend([
            '-s8',                             # 连接数
            '-x4',                             # 每服务器连接数
            '-k2M',                            # 分片大小
            '-j1',                             # 最大并发下载数(多进程环境建议为1)
            '--max-connection-per-server=1',   # 限制每服务器连接
            '--split=8',                       # 分段下载数
            '--min-split-size=2M',             # 最小分割大小
        ])
        
        # 文件和目录设置
        params.extend([
            '-d', self._download_dir,
            '-o', filename,
            '--file-allocation=prealloc',      # 预分配磁盘空间
            '--continue=true',                 # 断点续传
            '--auto-file-renaming=false',      # 禁用自动重命名
            '--allow-overwrite=true',          # 允许覆盖
            '--remote-time=false',             # 不设置远程时间
        ])
        
        # 性能优化参数
        params.extend([
            '--disk-cache=32M',                # 磁盘缓存
            '--piece-length=1M',               # 块大小
        ])
        
        # RPC和进程隔离
        params.extend([
            '--enable-rpc=false',              # 禁用RPC
            '--daemon=false',                  # 非守护进程模式
        ])
        
        # 日志和输出控制
        params.extend([
            '--log-level=warn',                # 警告级别日志
            '--console-log-level=warn',        # 控制台日志
            '--summary-interval=0',            # 禁用进度摘要
            '--download-result=hide',          # 隐藏下载结果
            '--quiet=true',                    # 静默模式
        ])
        
        # HTTP优化
        params.extend([
            '--enable-http-keep-alive=true',   # 启用HTTP keep-alive
            '--http-accept-gzip=true',         # 启用gzip压缩
        ])
        
        # 安全和兼容性
        params.extend([
            '--check-certificate=false',       # 跳过证书验证
            '--no-conf=true',                  # 不读取配置文件
            '--no-netrc=true',                 # 不使用netrc
        ])
        
        # 禁用BT功能 - 减少资源占用
        params.extend([
            '--enable-dht=false',              # 禁用DHT
            '--bt-enable-lpd=false',           # 禁用本地发现
            '--follow-torrent=false',          # 禁用种子跟踪
            '--seed-time=0',                   # 不做种
        ])
        
        # 添加URL
        params.append(url)
        
        # 过滤空字符串并返回
        return [param for param in params if param]

    # 生成下载文件名
    def _generate_filename(self, url: str) -> str:
        """生成下载文件名"""
        parsed_url = urlparse(url)
        filename = os.path.basename(parsed_url.path)
        
        # 清理文件名中的查询参数和锚点
        if '?' in filename:
            filename = filename.split('?')[0]
        if '#' in filename:
            filename = filename.split('#')[0]
        
        # 清理文件名中的特殊字符，防止目录创建
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        filename = re.sub(r'[^\w\-_.]', '_', filename)
        
        # 确保文件名不为空且以.apk结尾
        if not filename or not filename.lower().endswith('.apk'):
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            filename = f"download_{url_hash}.apk"
        
        # 确保文件名长度合理
        if len(filename) > 100:
            name_part = filename[:50]
            ext_part = filename[-4:] if filename.endswith('.apk') else '.apk'
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            filename = f"{name_part}_{url_hash}{ext_part}"
        
        return filename
    
    # 下载文件
    async def download(self, url: str, referer: str, is_use_proxy: bool = False, force_redownload: bool = False, max_retries: int = 3, progress_callback=None) -> Optional[str]:
        """下载文件，支持自动重试和进度监控""" 
        if not url or len(url) < 10:
            return None
        
        filename = self._generate_filename(url)
        file_path = os.path.join(self._download_dir, filename)
        
        # 检查文件是否已存在
        if os.path.exists(file_path) and not force_redownload:
            logger.info(f"文件正在下载中: {filename}")
            return None
        
        for attempt in range(max_retries):
                try:
                    # 获取配置
                    proxy = ""   
                    user_agent = "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

                    # 构建下载命令（修改为支持实时输出）
                    cmd = self._get_aria2_command_with_progress(url, filename, user_agent, proxy, referer)
                    
                    if attempt == 0:
                        logger.info(f"开始下载: {filename}")
                    else:
                        logger.info(f"重试下载 ({attempt + 1}/{max_retries}): {filename}")
                    
                    # 执行下载并监控进度
                    success = await self._execute_download_with_progress(cmd, progress_callback)
                    
                    if success:
                        # 下载成功，检查文件
                        if os.path.exists(file_path):     
                            # 检查是否为普通文件
                            if not os.path.isfile(file_path):
                                logger.error(f"下载结果不是普通文件: {file_path}")
                                self._cleanup_temp_files(file_path)
                                if attempt == max_retries - 1:
                                    return None
                                else:
                                    continue
                            
                            try:
                                file_size = os.path.getsize(file_path)
                                if file_size < 10 * 1024:
                                    logger.error(f"下载文件过小: {filename}")
                                    self._cleanup_temp_files(file_path)
                                    if attempt < max_retries - 1:
                                        continue
                                    else:
                                        return None
                                
                                # 下载成功
                                logger.info(f"下载成功: {filename}")
                                return file_path
                            except (OSError, IOError) as e:
                                logger.error(f"文件访问错误: {filename}: {str(e)}")
                                self._cleanup_temp_files(file_path)
                                if attempt == max_retries - 1:
                                    return None
                                continue
                        else:
                            logger.error(f"下载成功但文件不存在: {filename}")
                            return None
                    else:
                        # aria2c下载失败，尝试wget降级
                        self._cleanup_temp_files(file_path)
                        
                        # 在最后一次重试时，尝试wget降级
                        if attempt == max_retries - 1:
                            logger.warning(f"aria2c下载失败，尝试wget降级: {filename}")
                            try:
                                wget_success = await self._download_with_wget(url, filename, user_agent, proxy, referer, progress_callback)
                                if wget_success and os.path.exists(file_path):
                                    # wget下载成功，进行文件检查
                                    try:
                                        file_size = os.path.getsize(file_path)
                                        if file_size < 10 * 1024:
                                            logger.warning(f"wget下载的文件可能过小: {filename}")
                                            self._cleanup_temp_files(file_path)
                                            return None
                                        
                                        logger.info(f"wget降级下载成功: {filename}")
                                        return file_path
                                    except (OSError, IOError) as e:
                                        logger.error(f"wget下载文件访问错误: {filename}: {str(e)}")
                                        self._cleanup_temp_files(file_path)
                                        return None
                                else:
                                    logger.error(f"wget降级下载也失败: {filename}")
                                    return None
                            except Exception as e:
                                logger.error(f"wget降级下载出错: {filename}: {str(e)}")
                                return None
                        else:
                            logger.warning(f"aria2c下载失败，准备重试: {filename}")
                            await asyncio.sleep(2 ** attempt)  # 指数退避
                            
                except Exception as e:
                    # 清理临时文件
                    self._cleanup_temp_files(file_path)
                    
                    if attempt == max_retries - 1:
                        # 在最后一次重试时，尝试wget降级
                        logger.warning(f"aria2c下载出错，尝试wget降级: {filename}: {str(e)}")
                        try:
                            # 移除对不存在的 _aria2c_injector 的调用
                            user_agent = "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                            proxy = ""
                            
                            wget_success = await self._download_with_wget(url, filename, user_agent, proxy, referer, progress_callback)
                            if wget_success and os.path.exists(file_path):
                                # wget下载成功，进行文件检查
                                try:
                                    file_size = os.path.getsize(file_path)
                                    if file_size < 10 * 1024:
                                        logger.warning(f"wget下载的文件可能过小: {filename}")
                                        # 移除对不存在的 _aria2c_injector 的调用
                                        self._cleanup_temp_files(file_path)
                                        return None
                                    
                                    logger.info(f"wget降级下载成功: {filename}")
                                    return file_path
                                except (OSError, IOError) as file_e:
                                    logger.error(f"wget下载文件访问错误: {filename}: {str(file_e)}")
                                    self._cleanup_temp_files(file_path)
                                    return None
                            else:
                                logger.error(f"wget降级下载也失败: {filename}")
                                return None
                        except Exception as wget_e:
                            logger.error(f"wget降级下载出错: {filename}: {str(wget_e)}")
                            return None
                    else:
                        logger.warning(f"aria2c下载出错，准备重试: {filename}: {str(e)}")
                        await asyncio.sleep(2 ** attempt)  # 指数退避
            
        # 所有重试都失败了，清理临时文件
        self._cleanup_temp_files(file_path)
        return None
    
    def _cleanup_temp_files(self, file_path: str):
        """清理下载相关的临时文件"""
        try:
            # 删除主文件
            if os.path.exists(file_path):
                delete_file(file_path)
            
            # 删除aria2c产生的临时文件
            aria2_file = file_path + '.aria2'
            if os.path.exists(aria2_file):
                delete_file(aria2_file)
            
            # 删除可能存在的其他临时文件
            temp_patterns = [
                file_path + '.tmp',
                file_path + '.part',
                file_path + '.download'
            ]
            
            for temp_file in temp_patterns:
                if os.path.exists(temp_file):
                    delete_file(temp_file)
                    
        except Exception as e:
            logger.warning(f"清理临时文件时出错: {e}")
    
    def _get_aria2_command_with_progress(self, url: str, filename: str, user_agent: str, proxy: str, referer: str) -> List[str]:
        """获取支持进度输出的aria2c命令"""
        # 从URL提取域名作为Referer
        parsed_url = urlparse(url)
        domain = f"{parsed_url.scheme}://{parsed_url.netloc}"
                
        # 构建基础参数列表，使用stdbuf确保实时输出
        params = ['stdbuf', '-oL', 'aria2c']
        
        # 请求头设置
        params.extend([
            f'--header=User-Agent: {user_agent}',
            f'--header=Referer: {referer}',
        ])
        
        # 代理设置
        if proxy:
            params.extend([
                f'--all-proxy={proxy}',
                '--proxy-method=tunnel',
            ])
        
        # 网络连接参数
        params.extend([
            '--timeout=60',
            '--connect-timeout=30',
            '--retry-wait=5',
            '--max-tries=10',
        ])
        
        # 连接和并发控制
        params.extend([
            '-s10',
            '-x10', 
            '-k10M',
            '-m3',
        ])
        
        # 文件和目录设置
        params.extend([
            '-d', self._download_dir,
            '-o', filename,
            '--continue=true',
            '--auto-file-renaming=false',
            '--allow-overwrite=true',
            '--file-allocation=none',        # 禁用文件预分配
            '--remote-time=false',           # 不设置远程时间
        ])
        
        # 禁用不必要的功能
        params.extend([
            '--follow-metalink=false',       # 禁用metalink跟踪
            '--follow-torrent=false',        # 禁用种子跟踪
        ])
        
        # 日志设置（notice级别以显示进度）
        params.extend([
            '--log-level=notice',
            '--console-log-level=notice',
        ])
        
        # 安全和兼容性
        params.extend([
            '--check-certificate=false',
            '--no-conf=true',
            '--no-netrc=true',               # 不使用netrc
        ])
        
        # 添加URL
        params.append(url)
        
        return [param for param in params if param]
    
    async def _execute_download_with_progress(self, cmd: List[str], progress_callback) -> bool:
        """执行下载并监控进度"""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # 合并stderr到stdout
                bufsize=0  # Linux系统中必须为0
            )
            
            # 进度解析正则表达式
            progress_pattern = re.compile(r'(\d+\.?\d*[KMG]?i?B/\d*\.?\d*[KMG]?i?B(\(\d+%\))?)')
            speed_pattern = re.compile(r'(DL:\d+\.?\d*[KMG]?i?B)')
            eta_pattern = re.compile(r'(ETA:\d+[smhd]?)')
            
            # 读取输出并解析进度
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                    
                line_str = line.decode('utf-8', errors='ignore').strip()
                if line_str:
                    logger.info(line_str)
                    
                    # 解析进度信息
                    if progress_callback:
                        progress_info = self._parse_progress(line_str, progress_pattern, speed_pattern, eta_pattern)
                        if progress_info:
                            try:
                                await progress_callback(progress_info)
                            except Exception as e:
                                logger.warning(f"进度回调出错: {e}")
            
            await process.wait()
            return process.returncode == 0
            
        except Exception as e:
            logger.error(f"执行下载命令出错: {e}")
            return False
    
    def _parse_progress(self, line: str, progress_pattern, speed_pattern, eta_pattern) -> Optional[str]:
        """解析aria2c输出的进度信息"""
        progress_match = progress_pattern.search(line)
        speed_match = speed_pattern.search(line)
        eta_match = eta_pattern.search(line)
        
        process_str = ""
        if progress_match:
            process_str = f"下载进度: {progress_match.group(1)} "
        
        if speed_match:
            speed_text = speed_match.group(1)[3:]  # 去掉"DL:"前缀
            process_str += f"<br />下载速度: {speed_text}/s "
        
        if eta_match:
            eta_text = eta_match.group(1)[4:]  # 去掉"ETA:"前缀
            process_str += f"<br />预计时间: {eta_text} "
        
        return process_str if process_str else None
    
    def _get_wget_command(self, url: str, filename: str, user_agent: str, proxy: str, referer: str) -> List[str]:
        """获取wget下载命令"""
        # 构建wget命令参数
        params = ['wget']
        
        # 基本设置
        params.extend([
            '--no-check-certificate',          # 跳过SSL证书验证
            '--timeout=60',                    # 超时时间
            '--tries=5',                       # 重试次数
            '--waitretry=2',                   # 重试间隔
            '--continue',                      # 断点续传
            '--no-clobber',                    # 不覆盖已存在文件
            '--progress=bar:force',            # 显示进度条
        ])
        
        # 请求头设置
        params.extend([
            f'--user-agent={user_agent}',
            f'--referer={referer}',
        ])
        
        # 代理设置
        if proxy:
            if proxy.startswith('http://'):
                params.append(f'--http-proxy={proxy}')
            elif proxy.startswith('https://'):
                params.append(f'--https-proxy={proxy}')
            else:
                # 假设是http代理
                params.append(f'--http-proxy=http://{proxy}')
        
        # 输出设置
        params.extend([
            f'--output-document={os.path.join(self._download_dir, filename)}',
            '--quiet',                         # 静默模式，减少输出
        ])
        
        # 添加URL
        params.append(url)
        
        return params
    
    async def _download_with_wget(self, url: str, filename: str, user_agent: str, proxy: str, referer: str, progress_callback=None) -> bool:
        """使用wget下载文件"""
        try:
            cmd = self._get_wget_command(url, filename, user_agent, proxy, referer)
            logger.info(f"使用wget下载: {filename}")
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                bufsize=0
            )
            
            # wget进度解析正则表达式
            wget_progress_pattern = re.compile(r'(\d+)%.*?(\d+\.?\d*[KMG]?B/s).*?(\d+[smh]?)')
            
            # 读取输出并解析进度
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                    
                line_str = line.decode('utf-8', errors='ignore').strip()
                if line_str:
                    logger.info(f"wget: {line_str}")
                    
                    # 解析wget进度信息
                    if progress_callback:
                        progress_info = self._parse_wget_progress(line_str, wget_progress_pattern)
                        if progress_info:
                            try:
                                await progress_callback(progress_info)
                            except Exception as e:
                                logger.warning(f"wget进度回调出错: {e}")
            
            await process.wait()
            return process.returncode == 0
            
        except Exception as e:
            logger.error(f"wget下载出错: {e}")
            return False
    
    def _parse_wget_progress(self, line: str, progress_pattern) -> Optional[str]:
        """解析wget输出的进度信息"""
        match = progress_pattern.search(line)
        if match:
            percent = match.group(1)
            speed = match.group(2)
            eta = match.group(3)
            return f"下载进度: {percent}% <br />下载速度: {speed} <br />预计时间: {eta}"
        return None
