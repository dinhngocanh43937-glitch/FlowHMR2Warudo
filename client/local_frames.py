"""Bounded, lossless BGR frames for authenticated loopback-only transport."""

import struct
from urllib.parse import urlsplit

import cv2
import numpy as np

SIZE = struct.Struct("!HH")
MAX_PIXELS = 1920 * 1920
MAX_PAYLOAD = SIZE.size + MAX_PIXELS * 3


def use_local_raw(cfg):
    return cfg.get("deployment_mode") == "local" and urlsplit(
        cfg.get("input_url", "")
    ).hostname in ("127.0.0.1", "::1")


def pack_bgr(image):
    if (
        not isinstance(image, np.ndarray)
        or image.dtype != np.uint8
        or image.ndim != 3
        or image.shape[2] != 3
    ):
        raise ValueError("Expected uint8 HWC BGR frame")
    h, w = image.shape[:2]
    if not (16 <= w <= 1920 and 16 <= h <= 1920):
        raise ValueError("Raw frame dimensions outside limit")
    return SIZE.pack(w, h) + np.ascontiguousarray(image).tobytes()


def unpack_bgr(payload):
    if not SIZE.size <= len(payload) <= MAX_PAYLOAD:
        raise ValueError("Invalid raw payload size")
    w, h = SIZE.unpack_from(payload)
    if (
        not (16 <= w <= 1920 and 16 <= h <= 1920)
        or len(payload) != SIZE.size + w * h * 3
    ):
        raise ValueError("Raw dimensions/payload mismatch")
    bgr = np.frombuffer(payload, dtype=np.uint8, offset=SIZE.size).reshape(h, w, 3)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
