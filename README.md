# AutoUpdateBot

Android 应用更新自动检测与 APK 采集机器人。

## 功能特性

- **多平台支持**：支持 7723、HYKB（好游快爆）、CCPlay、GHZS 四大应用商店的自动更新检测
- **智能检测**：基于 OCR 文字识别 + uiautomator2 自动化操作，自动识别更新按钮并下载
- **APK 解析**：使用 AAPT 提取 APK 元信息（包名、版本、图标、截图等）
- **SFTP 上传**：支持将 APK 文件和截图自动上传至 SFTP 服务器
- **API 通知**：支持上报下载信息到后端 API
- **循环采集**：支持设置循环间隔持续采集
- **多端支持**：提供独立 GUI 客户端，可单独运行各平台采集器

## 项目结构

```
AutoUpdateBot/
├── api/                    # FastAPI REST API 服务
│   ├── main.py
│   └── routes/tasks.py     # 任务队列接口
├── cmd/                    # 各平台独立采集机器人
│   ├── 7723/               # 7723 应用市场
│   ├── hykb/               # 好游快爆
│   ├── ccplay/             # CCPlay
│   ├── ghzs/               # GHZS
│   ├── officialwebsite/     # 官网下载站
│   └── watcher/            # 文件监听器
├── core/                   # 核心模块
│   ├── device/device.py    # 设备管理（uiautomator2 封装）
│   ├── env_loader.py       # 环境变量初始化
│   ├── ocr/rapid_ocr.py   # OCR 引擎
│   └── queue/redis_queue.py
├── services/               # 业务服务层
│   ├── updater.py          # 更新检测服务
│   ├── extractor.py        # APK 提取服务
│   ├── parser.py           # APK 解析服务
│   ├── uploader.py         # SFTP 上传服务
│   ├── reporter.py         # API 上报服务
│   ├── app_manager.py      # 应用管理
│   ├── download.py         # 下载服务
│   ├── website_checker.py  # 网站检测
│   ├── queue.py            # 队列服务
│   └── worker_service.py   # 后台任务处理
├── utils/
│   └── utils.py            # 通用工具函数
├── gui_main.py             # 主程序 GUI
├── gui_watcher.py          # 文件监听器 GUI
├── main.py                 # 主程序入口
├── settings.yaml           # 配置文件（不上传，请复制 settings.yaml.example）
├── watcher.yaml            # 文件监听器配置
└── requirements.txt        # Python 依赖
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

```bash
cp settings.yaml.example settings.yaml
# 编辑 settings.yaml，填入实际配置
```

主要配置项：

```yaml
emulator:
  serial: '127.0.0.1:7555'   # Android 模拟器序列号

sftp:
  host: 'YOUR_SFTP_HOST'
  port: 22
  user: 'YOUR_USER'
  password: 'YOUR_PASSWORD'
  remote_dir: '/home/down/emulator'

api:
  url: 'http://YOUR_API/api/apk/localTask/apkUpdate'

redis:
  host: 'localhost'
  port: 6379
  db: 0
```

### 3. 运行

```bash
# 主程序 GUI
python gui_main.py

# 单独运行某个采集器
python cmd/7723/gui_main.py
python cmd/hykb/gui_main.py
python cmd/ccplay/gui_main.py

# API 服务
python api/main.py

# 文件监听器
python gui_watcher.py
```

### 4. 构建可执行文件

```bash
pyinstaller hykb.spec
pyinstaller 7723.spec
pyinstaller ccplay.spec
```

## 配置说明

### 检测关键字

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `skip_keywords` | 点击跳过/关闭按钮的关键字 | 完成、关闭、取消、同意... |
| `download_keywords` | 点击下载/更新按钮的关键字 | 立即升级、立即更新... |
| `update_keywords` | 更新列表匹配关键字 | 更新 |

### filter_packages

过滤包名列表，列表中的应用不会参与更新检测。

### loop_enabled / loop_interval

开启循环采集模式，设置循环间隔（秒）。

## 技术栈

- **uiautomator2** — Android 设备自动化控制
- **RapidOCR** — 基于 ONNX 的 OCR 文字识别
- **pyaxmlparser** — APK Manifest 解析
- **paramiko** — SFTP 文件传输
- **FastAPI** — REST API 服务
- **Redis** — 任务队列
- **PyYAML** — 配置文件解析
- **tkinter** — GUI 界面

## 许可证

MIT License
