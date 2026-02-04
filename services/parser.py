import subprocess
import re
import os
import hashlib
import zipfile
import struct
import shutil
import io
import threading
from PIL import Image
try:
    from pyaxmlparser import APK
except ImportError:
    APK = None


class ApkParser:
    def __init__(self, aapt_path, aapt2_path=None):
        """
        :param aapt_path: bin/aapt/aapt.exe 的绝对路径
        :param aapt2_path: bin/aapt/aapt2.exe 的绝对路径
        """
        self.aapt_path = aapt_path
        self.aapt2_path = aapt2_path

    def get_md5(self, file_path):
        """获取文件的MD5 [优化] 使用更大的缓冲区并释放 GIL"""
        hash_md5 = hashlib.md5()
        import time
        try:
            with open(file_path, "rb") as f:
                # 使用 128KB 缓冲区减少系统调用
                for chunk in iter(lambda: f.read(128 * 1024), b""):
                    hash_md5.update(chunk)
                    # 每处理一个块微小休眠，让出 CPU 给主线程绘图，防止大文件解析时界面“假死”
                    time.sleep(0.001) 
        except Exception as e:
            print(f"    [错误] 计算 MD5 失败: {e}")
        return hash_md5.hexdigest()

    def extract_icon(self, apk_path, icon_path_in_apk, output_dir):
        """从APK中提取图标文件"""
        if not icon_path_in_apk:
            return None
        try:
            with zipfile.ZipFile(apk_path, 'r') as z:
                # 检查路径是否存在
                if icon_path_in_apk in z.namelist():
                    ext = os.path.splitext(icon_path_in_apk)[1]
                    # 生成唯一文件名
                    target_name = f"icon_{hashlib.md5(icon_path_in_apk.encode()).hexdigest()[:8]}{ext}"
                    target_path = os.path.join(output_dir, target_name)
                    
                    with z.open(icon_path_in_apk) as source, open(target_path, "wb") as target:
                        shutil.copyfileobj(source, target)
                    return target_path
        except Exception as e:
            print(f"    [错误] 提取图标失败: {e}")
        return None

    def _get_img_dims(self, data):
        """解析图片头部获取宽高 (支持 PNG 和 WebP)"""
        if len(data) < 24: return None
        
        # PNG
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            try:
                w, h = struct.unpack('>II', data[16:24])
                return w, h
            except: return None
            
        # WebP
        if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            try:
                if data[12:16] == b'VP8 ':
                    # Simple WebP (lossy)
                    # Width/height are at offset 26
                    # But we need more than 24 bytes. Let's assume data is enough.
                    pass 
                elif data[12:16] == b'VP8L':
                    # Lossless WebP
                    # 14th byte starts the size info (14 bits each)
                    b1, b2, b3, b4 = data[15], data[16], data[17], data[18]
                    w = 1 + (((b2 & 0x3F) << 8) | b1)
                    h = 1 + (((b4 & 0x0F) << 10) | (b3 << 2) | ((b2 & 0xC0) >> 6))
                    return w, h
                elif data[12:16] == b'VP8X':
                    # Extended WebP
                    # Width/height are 24-bit at offset 24
                    # We need at least 30 bytes
                    if len(data) >= 30:
                        w = 1 + struct.unpack('<I', data[24:27] + b'\x00')[0]
                        h = 1 + struct.unpack('<I', data[27:30] + b'\x00')[0]
                        return w, h
            except: pass
            
        # JPEG
        if data.startswith(b'\xff\xd8'):
            try:
                # 简单的 JPEG 尺寸提取
                off = 2
                while off < len(data):
                    if data[off] == 0xff:
                        marker = data[off+1]
                        if marker in [0xc0, 0xc2]:
                            h, w = struct.unpack('>HH', data[off+5:off+9])
                            return w, h
                        off += 2 + struct.unpack('>H', data[off+2:off+4])[0]
                    else:
                        off += 1
            except: pass
            
        return None

    def _get_largest_img_from_list(self, apk_path, paths):
        """从路径列表中找出分辨率最大的图片 (PNG/WebP)"""
        best_path = None
        max_score = (-1, -1) # (area, file_size)
        try:
            with zipfile.ZipFile(apk_path, 'r') as z:
                for p in paths:
                    if p not in z.namelist(): continue
                    # 只要在 candidates 列表里的都尝试读取头信息判断，不强制要求后缀
                    try:
                        file_size = z.getinfo(p).file_size
                        with z.open(p) as f:
                            # Read more for WebP VP8X (needs 30 bytes)
                            head = f.read(32)
                            dims = self._get_img_dims(head)
                            if dims:
                                w, h = dims
                                area = w * h
                                score = (area, file_size)
                                if score > max_score:
                                    max_score = score
                                    best_path = p
                    except: pass
        except: pass
        return best_path

    def _parse_xml_icon(self, apk_path, xml_path, aapt_tool):
        """尝试解析XML图标获取前景图或背景图中的位图路径"""
        if not aapt_tool: return None
        print(f"DEBUG: 正在解析 XML 图标: {xml_path}")
        try:
            # 1. 尝试使用 aapt dump xmltree 提取所有资源引用
            cmd = [aapt_tool, 'dump', 'xmltree', apk_path, xml_path]
            creationflags = 0x08000000 if os.name == 'nt' else 0
            
            output = subprocess.check_output(
                cmd, encoding='utf-8', errors='ignore',
                creationflags=creationflags, stderr=subprocess.STDOUT
            )
            
            # 提取所有看起来像资源路径的字符串 (res/...)
            candidates = re.findall(r'\"(res/.*?)\"', output)
            if candidates:
                print(f"DEBUG: 在 XML 中发现候选路径: {candidates}")
            
            for path in candidates:
                # 排除 xml 路径，我们只需要位图
                if not path.lower().endswith('.xml'):
                    print(f"DEBUG: 成功从 XML 提取位图路径: {path}")
                    return path
            
            # 2. 如果没有直接路径，尝试寻找资源 ID 引用 (如 @0x7f0d0008)
            id_matches = re.findall(r'\"(@0x[0-9a-fA-F]+)\"', output)
            if id_matches:
                print(f"DEBUG: 在 XML 中发现资源 ID 引用: {id_matches}")
                # 尝试通过 aapt dump resources 查找这些 ID 对应的原始路径
                res_cmd = [aapt_tool, 'dump', 'resources', apk_path]
                res_output = subprocess.check_output(
                    res_cmd, encoding='utf-8', errors='ignore',
                    creationflags=creationflags, stderr=subprocess.STDOUT
                )
                for res_id in id_matches:
                    hex_id = res_id[1:].lower() # 0x7f...
                    # 在资源 dump 中寻找该 ID 对应的文件路径
                    res_match = re.search(f'resource {hex_id}.*?file=\"(res/.*?)\"', res_output)
                    if res_match:
                        path = res_match.group(1)
                        print(f"DEBUG: 资源 ID {res_id} 映射到路径: {path}")
                        if not path.lower().endswith('.xml'):
                            print(f"DEBUG: 成功通过资源 ID 映射找到位图: {path}")
                            return path
                        else:
                            print(f"DEBUG: 映射路径仍为 XML，继续查找...")
            
            # 如果走到这里还没返回，说明解析失败
            print(f"DEBUG: 未能从 XML 中解析出位图路径。XML 内容如下：\n{output}")
                            
        except Exception as e:
            print(f"DEBUG: 解析 XML 图标出错: {str(e)}")
        
        return None

    def _parse_package_from_xmltree(self, apk_path, aapt_tool):
        """从 aapt dump xmltree manifest 中解析包名"""
        try:
            cmd = [aapt_tool, 'dump', 'xmltree', apk_path, 'AndroidManifest.xml']
            creationflags = 0x08000000 if os.name == 'nt' else 0
            output = subprocess.check_output(cmd, encoding='utf-8', errors='ignore', creationflags=creationflags)
            # 查找形如 package="com.example.app" 的内容
            match = re.search(r'package="([^"]+)"', output)
            if match:
                return match.group(1)
        except: pass
        return None

    def _parse_attr_from_xmltree(self, apk_path, aapt_tool, attr_name):
        """从 aapt dump xmltree manifest 中解析指定属性值"""
        try:
            cmd = [aapt_tool, 'dump', 'xmltree', apk_path, 'AndroidManifest.xml']
            creationflags = 0x08000000 if os.name == 'nt' else 0
            output = subprocess.check_output(cmd, encoding='utf-8', errors='ignore', creationflags=creationflags)
            # aapt 输出格式通常为: A: android:versionName(0x0101021c)="1.0.0"
            match = re.search(rf'{attr_name}\(0x[0-9a-fA-F]+\)="([^"]+)"', output)
            if not match:
                # 兼容 aapt2 的输出格式: A: http://schemas.android.com/apk/res/android:versionName="1.0.0"
                match = re.search(rf'{attr_name}="([^"]+)"', output)
            if match:
                return match.group(1)
        except: pass
        return None

    def _get_app_names_with_aapt(self, local_apk_path):
        """使用 aapt/aapt2 获取应用名称 (中英文)"""
        tools_to_try = []
        if self.aapt_path and (os.path.exists(self.aapt_path) or shutil.which(self.aapt_path)):
            tools_to_try.append(self.aapt_path)
        if self.aapt2_path and (os.path.exists(self.aapt2_path) or shutil.which(self.aapt2_path)):
            tools_to_try.append(self.aapt2_path)
            
        res = {'app_name': None, 'en_app_name': None}
        
        for current_aapt in tools_to_try:
            try:
                creationflags = 0x08000000 if os.name == 'nt' else 0
                out_bytes = subprocess.check_output([current_aapt, 'dump', 'badging', local_apk_path], creationflags=creationflags, stderr=subprocess.STDOUT)
                
                label_out = None
                for enc in ['utf-8', 'gbk', 'big5']:
                    try:
                        tmp = out_bytes.decode(enc)
                        if 'application-label' in tmp:
                            label_out = tmp
                            break
                    except: continue
                
                if not label_out:
                    continue

                labels = {}
                # 1. 匹配所有语言标签
                for l_lang, l_val in re.findall(r"application-label-([a-zA-Z\-_]+):\s*['\"]([^'\"]+)['\"]", label_out):
                    val = l_val
                    if any(c in val for c in "褰辫浠"):
                        try: val = val.encode('gbk').decode('utf-8')
                        except: pass
                    labels[l_lang.lower().replace('_', '-')] = val

                # 2. 匹配默认标签
                default_match = re.search(r"application-label:\s*['\"]([^'\"]+)['\"]", label_out)
                if default_match:
                    val = default_match.group(1)
                    if any(c in val for c in "褰辫浠"):
                        try: val = val.encode('gbk').decode('utf-8')
                        except: pass
                    labels['default'] = val

                # 3. 匹配 application: label='...'
                header_match = re.search(r"application:.*?\blabel=['\"]([^'\"]*)['\"]", label_out)
                if header_match:
                    val = header_match.group(1)
                    if any(c in val for c in "褰辫浠"):
                        try: val = val.encode('gbk').decode('utf-8')
                        except: pass
                    labels['header'] = val

                # 选择中文名
                zh_name = labels.get('zh-cn') or labels.get('zh_cn') or labels.get('zh') or labels.get('zh-rcn') or \
                          labels.get('zh-hk') or labels.get('zh_hk') or labels.get('zh-tw') or labels.get('zh-rtw') or \
                          labels.get('default') or labels.get('header')
                
                # 选择英文名
                en_name = labels.get('en-us') or labels.get('en') or labels.get('en-gb') or \
                          labels.get('default') or labels.get('header')
                
                if zh_name: res['app_name'] = zh_name
                if en_name: res['en_app_name'] = en_name
                
                if res['app_name']:
                    break # 成功获取到名称，跳出工具尝试循环
            except:
                continue
                
        return res


    def parse(self, local_apk_path, extract_icon=False, icon_output_dir=None, icon_callback=None):
        """
        解析APK并提取详细信息
        策略：优先使用 aapt，如果解析失败或信息不全，则尝试 pyaxmlparser，最后 aapt2
        :param icon_callback: 当图标提取完成后调用的回调函数，参数为本地图标路径
        """
        if not os.path.exists(local_apk_path):
            print("    [错误] 文件不存在，无法解析")
            return {}

        # 1. 尝试使用 pyaxmlparser (纯 Python 方案，对部分损坏文件较稳健)
        if APK:
            try:
                print(f"    [调试] 尝试使用 pyaxmlparser 解析: {os.path.basename(local_apk_path)}")
                apk_obj = APK(local_apk_path)
                if apk_obj.package:
                    info = {
                        'package': apk_obj.package,
                        'versionCode': apk_obj.version_code,
                        'versionName': apk_obj.version_name,
                        'appname': apk_obj.application,
                        'en_app_name': apk_obj.application, 
                        'permissions': apk_obj.get_permissions(),
                        'min_sdk': apk_obj.get_min_sdk_version(),
                        'arch': self._get_arch_from_lib(local_apk_path),
                        'need_internet': "1" if "android.permission.INTERNET" in apk_obj.get_permissions() else "0",
                        'file_size': os.path.getsize(local_apk_path),
                        'is_search': False,
                    }
                    
                    # [优化] 无论 pyaxmlparser 是否成功，都优先尝试用 aapt 获取中英文应用名
                    names = self._get_app_names_with_aapt(local_apk_path)
                    if names['app_name']:
                        info['appname'] = names['app_name']
                        print(f"    [调试] 通过 aapt 获取中文名: {names['app_name']}")
                    if names['en_app_name']:
                        info['en_app_name'] = names['en_app_name']
                        print(f"    [调试] 通过 aapt 获取英文名: {names['en_app_name']}")
                    
                    # 尝试获取图标路径
                    icon_path = apk_obj.get_app_icon()
                    print(f"    [调试] pyaxmlparser 原始图标路径: {icon_path}")
                    if not icon_path:
                        # 如果 pyaxmlparser 没拿到图标，尝试盲扫
                        print(f"    [调试] pyaxmlparser 未发现图标，启动盲扫...")
                        icon_path = self._find_real_icon_from_zip(local_apk_path, None)
                        if icon_path:
                            info['is_search'] = True
                        print(f"    [调试] 盲扫结果: {icon_path}")
                    
                    if icon_path:
                        info['is_xml_icon'] = icon_path.lower().endswith('.xml')
                        # 如果是 XML，尝试解析其位图路径
                        if info['is_xml_icon']:
                            print(f"    [调试] 发现 XML 图标: {icon_path}，尝试解析位图...")
                            # 获取 aapt 工具用于解析 XML
                            aapt_tool = self.aapt_path or self.aapt2_path
                            real_path = self._parse_xml_icon(local_apk_path, icon_path, aapt_tool)
                            if real_path:
                                print(f"    [调试] XML 解析到位图: {real_path}")
                                icon_path = real_path
                                info['is_xml_icon'] = False
                            else:
                                # 解析 XML 失败，启动盲扫
                                print(f"    [调试] XML 解析位图失败，启动第二次盲扫...")
                                real_icon = self._find_real_icon_from_zip(local_apk_path, icon_path)
                                if real_icon:
                                    print(f"    [调试] 第二次盲扫结果: {real_icon}")
                                    icon_path = real_icon
                                    info['is_xml_icon'] = False
                                    info['is_search'] = True
                        
                        if extract_icon and icon_output_dir:
                            extracted_path = self.extract_icon(local_apk_path, icon_path, icon_output_dir)
                            info['local_icon_path'] = extracted_path
                            info['icon'] = extracted_path # 兼容旧代码
                            print(f"    [调试] 最终提取的图标本地路径: {extracted_path}")
                            if icon_callback and extracted_path:
                                try: icon_callback(extracted_path, info.get('is_search', False))
                                except: pass
                    
                    print(f"    [成功] pyaxmlparser 解析成功: {info['package']}")
                    # 最后计算 MD5，确保图标能尽快显示
                    info['md5'] = self.get_md5(local_apk_path)
                    return info
            except Exception as e:
                print(f"    [调试] pyaxmlparser 解析出错: {e}")

        # 2. 如果 pyaxmlparser 失败，退回到 aapt 方案
        # 优先顺序：aapt -> aapt2 (aapt 更稳定，aapt2 用于某些新特性)
        tools_to_try = []
        if self.aapt_path:
            tools_to_try.append(self.aapt_path)
        if self.aapt2_path:
            tools_to_try.append(self.aapt2_path)

        for current_aapt in tools_to_try:
            if not current_aapt or not (os.path.exists(current_aapt) or shutil.which(current_aapt)):
                continue
            
            tool_name = 'aapt2' if 'aapt2' in current_aapt.lower() else 'aapt'
            
            try:
                # Subprocess setup for Windows (hide console window)
                creationflags = 0
                if os.name == 'nt':
                    creationflags = 0x08000000 # CREATE_NO_WINDOW
                
                cmd = [current_aapt, 'dump', 'badging', local_apk_path]
                output_bytes = subprocess.check_output(
                    cmd, 
                    creationflags=creationflags,
                    stderr=subprocess.STDOUT
                )
                
                # 尝试多种编码解码
                output = None
                # 优先级调整：优先使用 utf-8
                encodings_to_try = ['utf-8', 'gbk', 'big5']
                
                # 记录所有解码尝试的结果，以便在 package: 没找到时分析
                all_decoded_outputs = []
                
                for enc in encodings_to_try:
                    try:
                        tmp_output = output_bytes.decode(enc)
                        all_decoded_outputs.append(tmp_output)
                        # 如果包含 package:，说明基本解码正确
                        if 'package:' in tmp_output:
                            output = tmp_output
                            print(f"    [调试] 成功使用 {enc} 解码 aapt 输出")
                            break
                    except:
                        continue
                
                # 如果都没有找到 package:，但在忽略错误的情况下找到了，也凑合用
                if not output:
                    try:
                        tmp_output = output_bytes.decode('utf-8', errors='ignore')
                        if 'package:' in tmp_output:
                            output = tmp_output
                            print(f"    [调试] 使用 utf-8 (ignore) 强制解码找到 package:")
                    except: pass

                if not output:
                    # 打印前 200 个字符用于调试，看看到底是什么东西
                    try:
                        preview = output_bytes[:200].hex()
                        print(f"    [错误] 无法从 aapt 输出中找到 package 关键字。原始输出(hex): {preview}")
                    except: pass
                
                if not output or 'package:' not in output:
                    # [兜底方案] 如果 badging 解析失败，尝试从 xmltree manifest 解析包名
                    print(f"    [调试] {tool_name} badging 解析失败，尝试 xmltree 兜底...")
                    package_name = self._parse_package_from_xmltree(local_apk_path, current_aapt)
                    if package_name:
                        # 构造一个模拟的 badging 输出以继续后续解析逻辑，或者直接返回部分信息
                        # 这里我们采取更直接的方式：如果能拿到包名，就先填入 info
                        info = {'package': package_name, 'is_search': False}
                        # 尝试获取版本号
                        v_code = self._parse_attr_from_xmltree(local_apk_path, current_aapt, "versionCode")
                        v_name = self._parse_attr_from_xmltree(local_apk_path, current_aapt, "versionName")
                        if v_code: info['versionCode'] = v_code
                        if v_name: info['versionName'] = v_name
                        
                        # 尝试获取应用标签
                        label = self._parse_attr_from_xmltree(local_apk_path, current_aapt, "label")
                        if label:
                            # 如果 label 是资源 ID (如 @0x7f...)，这里暂时不做深度解析，后续 badging 可能会成功
                            info['appname'] = label
                        else:
                            info['appname'] = package_name
                        
                        print(f"    [工具] 使用 {tool_name} xmltree 兜底解析成功: {package_name}")
                        # 如果有了包名，我们可以继续尝试从资源中提取图标等其他信息
                        # 但为了简单起见，这里先跳到 info 处理部分
                        output = f"package: name='{package_name}' versionCode='{v_code or ''}' versionName='{v_name or ''}'"
                    else:
                        print(f"    [警告] {tool_name} 兜底解析也失败，尝试切换工具...")
                        continue

                info = {'is_search': False}
                print(f"    [工具] 使用 {tool_name} 解析成功")
                
                # 1. 基础包信息
                # 兼容 aapt 和 aapt2 的输出格式，允许冒号后有空格，支持单双引号，支持任意空白符
                pkg_match = re.search(r"package:\s*name=['\"]([^'\"]*)['\"].*?versionCode=['\"]([^'\"]*)['\"].*?versionName=['\"]([^'\"]*)['\"]", output, re.S)
                if not pkg_match:
                    # 尝试更宽松的匹配
                    name_m = re.search(r"package:.*?name=['\"]([^'\"]*)['\"]", output, re.S)
                    code_m = re.search(r"versionCode=['\"]([^'\"]*)['\"]", output, re.S)
                    name_v = re.search(r"versionName=['\"]([^'\"]*)['\"]", output, re.S)
                    if name_m:
                        info['package'] = name_m.group(1)
                        info['versionCode'] = code_m.group(1) if code_m else ""
                        info['versionName'] = name_v.group(1) if name_v else ""
                else:
                    info['package'] = pkg_match.group(1)
                    info['versionCode'] = pkg_match.group(2)
                    info['versionName'] = pkg_match.group(3)
                
                if 'package' not in info: continue

                # 2. 应用名称 (多语言)
                labels = {}
                # 兼容 aapt2 可能存在的空格: application-label-zh-CN: '名称'，支持单双引号
                label_matches = re.findall(r"application-label-([a-zA-Z\-_]+):\s*['\"]([^'\"]+)['\"]", output)
                for lang, val in label_matches:
                    clean_val = val
                    if any(c in clean_val for c in "褰辫浠"):
                        try:
                            clean_val = clean_val.encode('gbk').decode('utf-8')
                        except: pass
                    labels[lang.lower().replace('_', '-')] = clean_val
                
                default_label_match = re.search(r"application-label:\s*['\"]([^'\"]*)['\"]", output)
                if default_label_match:
                    val = default_label_match.group(1)
                    if any(c in val for c in "褰辫浠"):
                        try:
                            val = val.encode('gbk').decode('utf-8')
                        except: pass
                    labels['default'] = val
                
                header_match = re.search(r"application:.*?\blabel=['\"]([^'\"]*)['\"]", output)
                if header_match:
                    val = header_match.group(1)
                    if any(c in val for c in "褰辫浠"):
                        try:
                            val = val.encode('gbk').decode('utf-8')
                        except: pass
                    labels['header'] = val

                #info['app_names'] = labels

                # 优先级选择显示名称
                zh_name = labels.get('zh-cn') or labels.get('zh_cn') or labels.get('zh') or labels.get('zh-rcn') or \
                          labels.get('zh-hk') or labels.get('zh_hk') or labels.get('zh-tw') or labels.get('zh-rtw') or \
                          labels.get('default') or labels.get('header')
                
                if not zh_name:
                    # 兼容 aapt2: launchable-activity: name='...' label='...' (一个或多个空格)
                    launch_match = re.search(r"launchable-activity:.*?label=['\"]([^'\"]*)['\"]", output)
                    if launch_match: zh_name = launch_match.group(1)
                
                info['appname'] = zh_name or "Unknown Application"
                
                en_name = labels.get('en-us') or labels.get('en') or labels.get('en-gb') or \
                          labels.get('default') or labels.get('header') or info['appname']
                info['en_app_name'] = en_name

                # 3. 权限
                permissions = re.findall(r"uses-permission:\s*name='([^']*)'", output)
                info['permissions'] = permissions

                # 4. 架构
                info['arch'] = self._get_arch_from_lib(local_apk_path)

                # 5. SDK & Internet
                sdk_match = re.search(r"(?:sdkVersion|minSdkVersion):\s*'(\d+)'", output)
                info['min_sdk'] = sdk_match.group(1) if sdk_match else "Unknown"
                info['need_internet'] = "1" if "android.permission.INTERNET" in permissions else "0"

                # 6. 图标
                icon_path = None
                
                # aapt/aapt2 dump badging 输出示例:
                # application-icon-120:'META-INF/6g'
                # application-icon-640:'META-INF/6j'
                # application-icon-65534:'META-INF/6g'
                # application: label='NB' icon='META-INF/6g'
                
                # 1. 提取所有带有密度的 application-icon-XXX
                # 兼容 aapt2 可能存在的空格，支持单双引号
                density_icons = re.findall(r"application-icon(?:-([a-zA-Z0-9]+))?:\s*['\"]([^'\"]*)['\"]", output)
                
                # 2. 提取 application: 行中的默认图标
                default_icon_path = None
                # 更加灵活的匹配方式，防止其他属性干扰，支持单双引号
                app_line_match = re.search(r"application:.*?\bicon=['\"]([^'\"]*)['\"]", output)
                if app_line_match:
                    default_icon_path = app_line_match.group(1)

                # 处理所有发现的密度图标
                processed_icons = [] # list of (density, path)
                seen_paths = set()

                if density_icons:
                    for d, path in density_icons:
                        if path in seen_paths: continue
                        seen_paths.add(path)
                        
                        d_val = 0
                        if d:
                            if d.isdigit():
                                d_val = int(d)
                            else:
                                d_lower = d.lower()
                                if 'xxxhdpi' in d_lower: d_val = 640
                                elif 'xxhdpi' in d_lower: d_val = 480
                                elif 'xhdpi' in d_lower: d_val = 320
                                elif 'hdpi' in d_lower: d_val = 240
                                elif 'mdpi' in d_lower: d_val = 160
                                elif 'anydpi' in d_lower: d_val = 65535
                        processed_icons.append((d_val, path))
                
                if default_icon_path and default_icon_path not in seen_paths:
                    # 默认图标权重设为 1，作为保底
                    processed_icons.append((1, default_icon_path))
                    seen_paths.add(default_icon_path)

                # 寻找最佳图片和最佳 XML
                best_img_path = None
                best_img_density = -1
                best_xml_path = None
                best_xml_density = -1

                for d_val, path in processed_icons:
                    is_xml = path.lower().endswith('.xml')
                    if is_xml:
                        if d_val > best_xml_density:
                            best_xml_density = d_val
                            best_xml_path = path
                    else:
                        # 对于图片图标：
                        # 65534/65535 (anydpi) 的图片通常只是默认图的引用
                        # 真正的最高清图通常在 640 (xxxhdpi)
                        effective_density = d_val
                        if d_val > 640: effective_density = 2 # 降级，但比默认(1)高一点
                        
                        if effective_density > best_img_density:
                            best_img_density = effective_density
                            best_img_path = path

                # 最终决策逻辑：
                # 1. 优先使用图片图标 (只要 aapt 识别到了图片，直接使用，不再搜索)
                # 2. 如果只有 XML 图标，则直接进入 ZIP 盲扫逻辑
                
                icon_path = None
                if best_img_path:
                    # 只要 aapt 识别到了位图图标，直接使用
                    icon_path = best_img_path
                    info['is_xml_icon'] = False
                elif best_xml_path:
                    # 如果只有 XML 图标，标记原始来源是 XML，并直接通过 ZIP 盲扫寻找真实位图
                    info['is_xml_icon'] = True
                    real_img = self._find_real_icon_from_zip(local_apk_path, best_xml_path)
                    if real_img:
                        icon_path = real_img
                        info['is_search'] = True
                    else:
                        # 实在找不到位图，最后只能用 XML 路径本身
                        icon_path = best_xml_path
                
                info['icon'] = icon_path

                # 最终检查
                if not icon_path:
                    print(f"    [警告] {tool_name} 未能识别图标路径")
                
                # 7. 导出图标
                if icon_path and extract_icon:
                    info['icon_path_in_apk'] = icon_path
                    try:
                        if icon_output_dir:
                            save_dir = icon_output_dir
                        else:
                            save_dir = os.path.join(os.path.dirname(local_apk_path), "icons")
                        
                        if not os.path.exists(save_dir): os.makedirs(save_dir)
                        
                        # 检测真实后缀
                        real_ext = "png" # 默认
                        try:
                            with zipfile.ZipFile(local_apk_path, 'r') as z:
                                with z.open(icon_path) as f:
                                    header = f.read(32)
                                    if header.startswith(b'\x89PNG\r\n\x1a\n'): real_ext = "png"
                                    elif header.startswith(b'RIFF') and b'WEBP' in header: real_ext = "webp"
                                    elif header.startswith(b'\xff\xd8'): real_ext = "jpg"
                                    elif b'<?xml' in header or b'<vector' in header: real_ext = "xml"
                        except: pass
                        
                        # 如果原路径有合法的后缀，优先保留
                        path_ext = icon_path.split('.')[-1].lower() if '.' in icon_path else ""
                        if path_ext in ['png', 'webp', 'jpg', 'jpeg', 'xml']:
                            save_ext = path_ext
                        else:
                            save_ext = real_ext

                        save_name = f"{info['package']}_{info['versionCode']}.{save_ext}"
                        save_path = os.path.normpath(os.path.join(save_dir, save_name))
                        
                        with zipfile.ZipFile(local_apk_path, 'r') as z:
                            with open(save_path, 'wb') as f:
                                f.write(z.read(icon_path))
                        
                        info['local_icon_path'] = save_path
                        info['icon'] = save_path # 兼容旧代码
                        print(f"    [成功] 图标已导出: {save_name} (路径: {icon_path})")
                        if icon_callback and save_path:
                            try: icon_callback(save_path, info.get('is_search', False))
                            except: pass
                    except Exception as e:
                        print(f"    [错误] 导出图标失败: {e}")
                
                # 8. 文件信息
                info['file_size'] = os.path.getsize(local_apk_path)
                info['md5'] = self.get_md5(local_apk_path)
                
                return info

            except Exception as e:
                print(f"    [错误] {tool_name} 执行失败: {e}")
                continue
        
        return {}

    def _is_mostly_single_color(self, img_data):
        """检查图片是否主要是纯色或颜色过于单调（如渐变、简单色块、简单线条图）"""
        try:
            img = Image.open(io.BytesIO(img_data))
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGB')
            
            w, h = img.size
            # 缩放图片以分析内容丰富度
            analysis_size = 32
            img_small = img.resize((analysis_size, analysis_size), Image.Resampling.LANCZOS)
            pixels = list(img_small.getdata())
            
            # 1. 检查透明像素占比 (图标内容通常应占据一定比例，但也不宜太小)
            if img_small.mode == 'RGBA':
                opaque_pixels = [p for p in pixels if p[3] > 30]
                opaque_count = len(opaque_pixels)
                total_count = len(pixels)
                opaque_ratio = opaque_count / total_count
                
                # 如果非透明像素占比极低（如小于 5%），通常是简单的箭头、线条或小图标，排除
                if opaque_ratio < 0.05:
                    return True
                
                # 更新 pixels 仅包含不透明部分用于后续分析
                pixels_rgb = [p[:3] for p in opaque_pixels]
            else:
                pixels_rgb = pixels

            if not pixels_rgb: return True

            # 2. 计算颜色方差
            r_vals = [p[0] for p in pixels_rgb]
            g_vals = [p[1] for p in pixels_rgb]
            b_vals = [p[2] for p in pixels_rgb]
            
            def variance(data):
                n = len(data)
                if n < 2: return 0
                avg = sum(data) / n
                return sum((x - avg) ** 2 for x in data) / n
            
            var = variance(r_vals) + variance(g_vals) + variance(b_vals)
            
            # 进一步提高方差阈值：图标通常具有更复杂的颜色分布
            if var < 800: 
                return True
            
            # 3. 检查颜色种类数 (去重后的量化颜色数量)
            # 进一步量化颜色，减少噪声干扰
            quantized_colors = set([(p[0]//24, p[1]//24, p[2]//24) for p in pixels_rgb])
            if len(quantized_colors) < 12:
                # 真正的图标在 32x32 缩略图中，量化后的主色调通常较丰富
                return True
            
            # 4. 边缘检测分析 (区分简单几何图形与复杂内容)
            # 计算相邻像素的差异
            edge_score = 0
            for i in range(len(pixels_rgb) - 1):
                p1 = pixels_rgb[i]
                p2 = pixels_rgb[i+1]
                diff = sum(abs(p1[j] - p2[j]) for j in range(3))
                if diff > 30: edge_score += 1
            
            # 如果边缘（突变点）太少，说明是简单的色块或极简单的线条
            if edge_score < (len(pixels_rgb) * 0.1):
                return True
                
            return False
        except:
            return False

    def _has_transparent_corners(self, img_data):
        """检查图片四个角是否有透明像素"""
        try:
            img = Image.open(io.BytesIO(img_data))
            if img.mode != 'RGBA':
                return False  # 非 RGBA 模式通常没有 Alpha 通道，视为不透明
            
            w, h = img.size
            if w < 10 or h < 10: return False
            
            # 检查四个角的 Alpha 值
            # 阈值设定：如果 Alpha < 200，则认为该角是透明的
            corners = [
                img.getpixel((0, 0))[3],
                img.getpixel((w - 1, 0))[3],
                img.getpixel((0, h - 1))[3],
                img.getpixel((w - 1, h - 1))[3]
            ]
            
            # 只要有一个角透明，就返回 True
            for alpha in corners:
                if alpha < 200:
                    return True
            return False
        except:
            return False

    def _find_real_icon_from_zip(self, apk_path, xml_path):
        """
        当 aapt 返回 XML 图标时，在 ZIP 中全局搜索最像图标的位图。
        不管名称，只管大小 and 图标特征（透明角、色彩丰富度）。
        """
        best_path = None
        max_score = (-1, -1)
        
        try:
            with zipfile.ZipFile(apk_path, 'r') as z:
                # 预定义 Android 标准图标尺寸（按优先级排序）
                # 192: xxhdpi, 144: xhdpi, 96: hdpi, 72: mdpi, 48: ldpi
                target_sizes = {192, 144, 96, 72, 48}
                
                for p in z.namelist():
                    # 仅处理图片
                    if not p.lower().endswith(('.png', '.webp', '.jpg', '.jpeg')):
                        continue
                    
                    try:
                        data = z.read(p)
                        with Image.open(io.BytesIO(data)) as img:
                            w, h = img.size
                            file_size = len(data)
                            
                            # 1. 基础过滤：必须是正方形且不能太小
                            if w != h or w < 48:
                                continue
                            
                            # 2. 特征过滤：排除纯色/单调图
                            if self._is_mostly_single_color(data):
                                continue
                                
                            # 3. 评分逻辑
                            path_lower = p.lower()
                            path_score = 0
                            
                            # 优先级 A: 路径特征分
                            if 'ic_launcher' in path_lower:
                                path_score += 100
                            if 'mipmap' in path_lower:
                                path_score += 50
                            if 'icon' in path_lower:
                                path_score += 30
                            if 'app_icon' in path_lower:
                                path_score += 40
                            
                            # 优先级 B: 尺寸分 (标准尺寸 192/144 等得分最高)
                            size_score = 10 if w in target_sizes else 5
                            if w > 192: size_score = 5 # 太大可能是启动页
                            if w == 512: size_score = 20 # 应用商店规格图标权重极高
                            
                            # 优先级 C: 特征分 (透明角通常是图标特征)
                            feature_score = 0
                            if self._has_transparent_corners(data):
                                feature_score += 20
                            
                            # 最终总分
                            total_score = (path_score + size_score + feature_score, w * h, file_size)
                            
                            if total_score > max_score:
                                max_score = total_score
                                best_path = p
                    except: continue
        except: pass
        return best_path

    def _get_arch_from_lib(self, apk_path):
        """检查 lib 目录确定架构"""
        try:
            with zipfile.ZipFile(apk_path, 'r') as z:
                all_files = z.namelist()
                lib_files = [f for f in all_files if f.startswith('lib/')]
                if not lib_files: return 3
                is_64, is_32 = False, False
                for f in lib_files:
                    f_l = f.lower()
                    if 'arm64-v8a' in f_l or 'x86_64' in f_l: is_64 = True
                    elif any(x in f_l for x in ['armeabi-v7a', 'armeabi', 'x86', 'mips']):
                        if 'x86_64' not in f_l: is_32 = True
                if is_64 and is_32: return 2
                if is_64: return 0
                if is_32: return 1
                return 3
        except: return 3
