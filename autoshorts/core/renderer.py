import subprocess
import cv2
import numpy as np

from autoshorts.config import AppConfig
from autoshorts.core.protocols import Logger, ProgressReporter
from autoshorts.models import ProcessingOptions, LogLevel


class VideoRenderer:
    """
    Renders the final vertical (9:16) short video using FFmpeg and YOLOv8
    for smart subject tracking and cropping.
    """

    def __init__(
        self,
        config: AppConfig,
        logger: Logger,
        progress_reporter: ProgressReporter,
    ):
        self._config = config
        self._log = logger
        self._progress = progress_reporter

        self._progress.report_progress(80, "Initializing smart cropping model (YOLOv8)...")
        from ultralytics import YOLO
        import logging
        logging.getLogger("ultralytics").setLevel(logging.WARNING)
        self._model = YOLO("yolov8n.pt")

    def render(
        self,
        video_path: str,
        start_time: float,
        output_path: str,
        options: ProcessingOptions,
        clip_duration: float,
    ) -> None:
        """
        Slice, smartly crop to 9:16 using YOLOv8, and encode the final video.
        """
        self._progress.report_progress(82, f"Opening video for smart cropping at {start_time:.1f}s...")
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, start_time * 1000)

        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(clip_duration * fps)

        aspect_ratio_str = self._config.render.crop_aspect_ratio
        w_ratio, h_ratio = map(float, aspect_ratio_str.split('/'))
        target_width = int(height * (w_ratio / h_ratio))

        hw_accel = options.hardware_accel

        # Build FFmpeg command for piped input
        cmd = [
            self._config.ffmpeg_path, '-y',
            '-f', 'rawvideo',
            '-vcodec', 'rawvideo',
            '-s', f'{target_width}x{height}',
            '-pix_fmt', 'bgr24',
            '-r', str(fps),
            '-i', '-',  # Video from stdin
            '-ss', str(start_time),
            '-t', str(clip_duration),
            '-i', video_path,  # Audio from original file
            '-map', '0:v',
            '-map', '1:a',
        ]

        crf_value = self._config.render.default_crf
        preset = self._config.render.default_preset

        if hw_accel == "NVENC":
            cmd.extend([
                '-c:v', 'h264_nvenc',
                '-rc', 'vbr',
                '-cq', str(crf_value),
                '-b:v', '0',
                '-preset', 'p5',
                '-bf', '3',
                '-rc-lookahead', '32',
            ])
        elif hw_accel == "QSV":
            cmd.extend([
                '-c:v', 'h264_qsv',
                '-global_quality', str(crf_value),
                '-preset', preset,
            ])
        else:
            cmd.extend([
                '-c:v', 'libx264',
                '-crf', str(crf_value),
                '-preset', preset,
            ])

        cmd.extend([
            '-c:a', 'aac',
            '-b:a', self._config.render.default_audio_bitrate,
            '-shortest',
            output_path,
        ])

        self._log.log(f"Executing FFmpeg: {' '.join(cmd)}", LogLevel.DEBUG)

        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=False,
        )

        import threading
        def consume_stdout(pipe):
            for line in iter(pipe.readline, b''):
                line_str = line.decode('utf-8', errors='ignore')
                if "time=" in line_str:
                    self._log.log(f"FFmpeg encoding... {line_str.strip()}", LogLevel.DEBUG)
                    
        log_thread = threading.Thread(target=consume_stdout, args=(process.stdout,), daemon=True)
        log_thread.start()

        ema_center_x = width / 2.0
        alpha = 0.1  # Smoothing factor

        frames_processed = 0
        last_reported_pct = -1
        static_crop_locked = False

        while frames_processed < total_frames and cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
                
            run_inference = True
            if options.crop_mode == "Static" and static_crop_locked:
                run_inference = False
            elif options.skip_frames > 0 and (frames_processed % (options.skip_frames + 1)) != 0:
                run_inference = False

            if run_inference:
                # Run YOLO detection for persons (class 0)
                results = self._model.predict(frame, classes=[0], verbose=False)
    
                best_conf = 0
                best_center_x = ema_center_x
    
                if len(results) > 0 and len(results[0].boxes) > 0:
                    boxes = results[0].boxes
                    for box in boxes:
                        conf = float(box.conf[0])
                        if conf > best_conf:
                            best_conf = conf
                            x1, y1, x2, y2 = box.xyxy[0].tolist()
                            best_center_x = (x1 + x2) / 2.0
                            
                    if options.crop_mode == "Static" and best_conf > 0.5:
                        static_crop_locked = True
    
                # Apply EMA smoothing
                ema_center_x = (alpha * best_center_x) + ((1 - alpha) * ema_center_x)

            # Calculate crop bounds
            start_x = int(ema_center_x - (target_width / 2.0))
            start_x = max(0, min(start_x, width - target_width))

            # Crop frame
            cropped_frame = frame[:, start_x:start_x + target_width]

            # Write to FFmpeg
            try:
                process.stdin.write(cropped_frame.tobytes())
            except BrokenPipeError:
                break

            frames_processed += 1

            # Report progress
            fraction = frames_processed / total_frames
            current_pct = int(80 + fraction * 20)
            if current_pct != last_reported_pct:
                last_reported_pct = current_pct
                self._progress.report_progress(
                    current_pct,
                    f"Rendering & smart cropping: {frames_processed}/{total_frames} frames"
                )

        cap.release()
        if process.stdin:
            process.stdin.close()

        log_thread.join()

        process.wait()
        if process.returncode != 0:
            raise RuntimeError(
                f"FFmpeg rendering failed with exit code {process.returncode}"
            )
