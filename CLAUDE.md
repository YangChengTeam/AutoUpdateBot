# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**AutoUpdateBot** is a Python automation framework for Android app management and APK collection. It automates:
- Detecting app updates across third-party app stores (7723, HYKB, CCPlay)
- Downloading and extracting APK files from Android emulators via ADB
- Parsing APK metadata (version, package name, icons, screenshots)
- Uploading files via SFTP and reporting to backend APIs
- Running multiple specialized bots for different platforms

## Architecture

### Core Layer (`core/`)
- **`device/device.py`**: `DeviceManager` wraps uiautomator2 for Android emulator interactions
- **`ocr/rapid_ocr.py`**: `OcrEngine` singleton for text detection in screenshots using RapidOCR
- **`env_loader.py`**: Environment setup for bundled ADB/AAPT binaries

### Services Layer (`services/`)
Each service is a separate class accepting config for dependency injection:
- **`updater.py`**: `UpdateService` - UI automation for update detection via uiautomator2 watchers
- **`extractor.py`**: `ApkExtractor` - Pulls APK files from device via ADB
- **`parser.py`**: `ApkParser` - Extracts metadata using aapt
- **`uploader.py`**: `SftpUploader` - SFTP file uploads
- **`reporter.py`**: `ReportService` - API notifications
- **`app_manager.py`**: `AppManager` - Package/version management
- **`worker_service.py`**: Background task queue processing

### Bot Implementations (`cmd/`)
Specialized bots for each app store, each with standalone GUI:
- **`7723/`**: Bot7723 for `com.upgadata.up7723`
- **`hykb/`**: BotHYKB for `com.xmcy.hykb`
- **`ccplay/`**: CCPlayBot for `com.lion.market`

All bots use `sys.path.append()` to access project root modules.

### API Layer (`api/`)
FastAPI REST server on port 10000 for task management.

## Common Commands

**Run main bot:**
```bash
python main.py          # CLI mode
python gui_main.py      # GUI mode
```

**Run individual bots:**
```bash
python cmd/7723/gui_main.py
python cmd/hykb/gui_main.py
python cmd/ccplay/gui_main.py
```

**Build executables (PyInstaller):**
```bash
pyinstaller 7723.spec   # Build 7723 bot
pyinstaller hykb.spec   # Build HYKB bot
pyinstaller ccplay.spec # Build CCPlay bot
pyinstaller ui.spec     # Build main GUI
```

**Run API server:**
```bash
python api/main.py      # Start FastAPI on port 10000
```

## Configuration

- **`settings.yaml`**: Main config (emulator serial, API URLs, SFTP credentials, detection keywords)
- **`watcher.yaml`**: File watcher and Redis queue configuration

Default emulator: `127.0.0.1:7555`

## Key Patterns

1. **Environment Setup**: Always call `setup_env()` from `core.env_loader` first - adds bundled ADB to PATH
2. **Service Instantiation**: Services accept `config` dict for dynamic reconfiguration
3. **Device Access**: `DeviceManager.d` exposes the raw uiautomator2 object
4. **Logging**: Structured logging with `[ServiceName]` prefixes
5. **Daily Log Tracking**: Bots track processed items in daily logs to avoid duplicates
6. **Package Path**: All `cmd/` bots use `sys.path.append()` to import from project root

## Dependencies

- **uiautomator2**: Android device automation
- **rapidocr-onnxruntime**: OCR for UI element detection
- **pyaxmlparser**: APK manifest parsing
- **paramiko**: SFTP uploads
- **FastAPI/uvicorn**: REST API server
- **redis**: Task queue coordination
- **PyYAML**: Configuration loading
- **tkinter**: GUI framework

## Binary Paths

Bundled binaries are in `bin/`:
- `bin/adb` - ADB executable
- `bin/aapt/aapt.exe` - AAPT for APK parsing

These are automatically added to PATH via `setup_env()`.

## Git Ignore

Logs, screenshots, APKs, and build artifacts are excluded via `.gitignore`.
