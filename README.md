# 🎬 AutoShorts Creator

An AI-powered desktop application built with Python and PyQt6 that automatically converts YouTube videos or local video files into engaging vertical (9:16) Shorts, Reels, and TikTok videos.

![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green)
![FFmpeg](https://img.shields.io/badge/video-FFmpeg-orange)
![YOLOv8](https://img.shields.io/badge/AI-YOLOv8-blueviolet)

---

## ✨ Features

- **🌐 Dual Source Ingestion**: Accept YouTube URLs or local video files (`.mp4`, `.mkv`, `.avi`).
- **🔥 Heatmap Engagement Analysis**: Automatically extracts YouTube viewer engagement peak data to identify viral moments.
- **🧠 Multimodal AI Analysis**: Parallel analysis combining Audio RMS Energy, Spectral Flux, Speech Detection (Silero VAD), and Optical Motion Analysis when heatmaps are unavailable.
- **🎬 Scene Boundary Detection**: Uses `scenedetect` to snap highlight clip boundaries cleanly to natural scene cuts.
- **🎯 AI Smart Subject Tracking & Cropping**: Integrated **YOLOv8** model tracks primary subjects dynamically to keep key elements centered during vertical (9:16) reframing.
- **⚡ Hardware Acceleration**: Supports CPU encoding as well as **NVIDIA NVENC** (`h264_nvenc`) and **Intel QSV** (`h264_qsv`) GPU acceleration.
- **🎛️ Configurable Parameters**: Customize target duration (15–60s), clip count (1–10), clip ordering (Linear / Non-linear), and resolution output.
- **🎨 Sleek Dark Theme UI**: Built with PyQt6, complete with thread-safe execution, progress tracking, live color-coded logs, and immediate cancellation control.

---

## 📁 Repository Structure

```text
AutoShortsCreator/
├── main.py                     # Entry point & FFmpeg verification
├── requirements.txt            # Dependency list
├── yolov8n.pt                  # YOLOv8 nano detection model
├── autoshorts/
│   ├── config.py               # Central configuration & dataclasses
│   ├── models.py               # Processing options & data models
│   ├── core/
│   │   ├── engine.py           # Pipeline orchestrator
│   │   ├── downloader.py       # Ingestion & YouTube heatmap parser
│   │   ├── renderer.py         # YOLOv8 subject tracking & FFmpeg render
│   │   ├── protocols.py        # Abstract interfaces (Strategy pattern)
│   │   └── analysis/
│   │       ├── heatmap.py      # YouTube heatmap analyzer strategy
│   │       └── multimodal.py   # Audio/visual AI multimodal strategy
│   └── ui/
│       ├── main_window.py      # PyQt6 interface layout & slot handlers
│       ├── worker.py           # Async background thread processing worker
│       └── theme.py            # Dark mode styling & stylesheet rules
└── temp_processing/            # Workspace directory for transient downloads
```

---

## 🚀 Quick Start

### 1. Prerequisites

- **Python**: Version 3.10 or higher.
- **FFmpeg**: Must be available on system `PATH` or placed as binary executables (`ffmpeg.exe`, `ffprobe.exe`) in the root directory.

### 2. Installation

1. **Clone the Repository**
   ```bash
   git clone https://github.com/your-username/AutoShortsCreator.git
   cd AutoShortsCreator
   ```

2. **Create a Virtual Environment**
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On Linux/macOS:
   source venv/bin/activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

---

## 💻 Usage

Run the entry point script to launch the application GUI:

```bash
python main.py
```

### Application Steps

1. **Select Source Media**: Toggle between **URL** (enter YouTube link) or **Local File** (browse file).
2. **Configure Settings**:
   - **Target Duration**: Choose total length of short video (15–60s).
   - **Max Clips**: Number of segments to slice and combine.
   - **Arrangement**: *Linear* (chronological order) or *Non-linear* (ranked by engagement score).
   - **Hardware Acceleration**: Select *CPU (Software)*, *NVENC (NVIDIA)*, or *QSV (Intel)*.
3. **Set Output Destination**: Select output folder for the final `.mp4` file.
4. **Generate**: Click **Generate Short**. Real-time progress and logs will display in the console below. Click **Stop** at any point to cancel execution cleanly.

---

## 🛠️ Tech Stack & Libraries

- **GUI**: [PyQt6](https://www.riverbankcomputing.com/software/pyqt/)
- **Media Processing**: [FFmpeg](https://ffmpeg.org/), [OpenCV](https://opencv.org/)
- **Subject Tracking**: [Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics)
- **Audio Analysis**: [Librosa](https://librosa.org/), [Silero VAD](https://github.com/snakers4/silero-vad)
- **Scene Detection**: [PySceneDetect](https://github.com/Breakthrough/PySceneDetect)
- **Video Ingestion**: [yt-dlp](https://github.com/yt-dlp/yt-dlp)

---

## 📜 License

Distributed under the MIT License. See [LICENSE](LICENSE) for more details.
