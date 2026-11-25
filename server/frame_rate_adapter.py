"""Lower transport/detection FPS without changing the trained 30 Hz model clock."""

from collections import deque
from dataclasses import replace

import numpy as np


def model_index(sequence, fps):
    return (int(sequence) * 30 * 2 + fps) // (2 * fps)


class ModelClock:
    def __init__(self):
        self.previous = None
        self.pending = deque()
        self.repeated = 0

    def push(self, frame, fps):
        if fps != 30 and self.previous is not None:
            gap = frame.frame_index - self.previous.frame_index
            # Fill only expected rate-conversion gaps, never arbitrary backlog.
            if 1 < gap <= 2:
                for index in range(self.previous.frame_index + 1, frame.frame_index):
                    self.pending.append(
                        replace(
                            self.previous,
                            frame_index=index,
                            media_time_s=index / 30.0,
                            capture_mono_s=frame.capture_mono_s
                            - (frame.frame_index - index) / 30.0,
                            is_stream_reset=False,
                            is_camera_switch=False,
                        )
                    )
                    self.repeated += 1
        self.pending.append(frame)
        self.previous = frame


def rate_aware_tracker(base, fps_getter):
    class RateAwareTracker(base):
        def detect_and_track_batch(self, rgb_frames, *, reset_flags=None):
            if fps_getter() == 30 or not rgb_frames:
                return super().detect_and_track_batch(
                    rgb_frames, reset_flags=reset_flags
                )
            flags = (
                list(reset_flags)
                if reset_flags is not None
                else [False] * len(rgb_frames)
            )
            unique, unique_flags, mapping = [], [], []
            for image, reset in zip(rgb_frames, flags):
                if not unique or image is not unique[-1] or reset:
                    unique.append(image)
                    unique_flags.append(reset)
                mapping.append(len(unique) - 1)
            boxes = super().detect_and_track_batch(unique, reset_flags=unique_flags)
            self.rate_input_frames = getattr(self, "rate_input_frames", 0) + len(
                rgb_frames
            )
            self.rate_unique_frames = getattr(self, "rate_unique_frames", 0) + len(
                unique
            )
            return np.asarray(boxes)[mapping]

    return RateAwareTracker
