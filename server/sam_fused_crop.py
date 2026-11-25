"""Process-local fused SAM crop adapter; vendor sources remain untouched."""

from contextlib import contextmanager

import cv2
import numpy as np
import torch


def warp(image, inverse, columns, rows):
    coordinates = []
    for axis in range(2):
        horizontal = torch.round(inverse[:, axis, 0, None] * columns * 1024)
        vertical = torch.round(
            (inverse[:, axis, 1, None] * rows + inverse[:, axis, 2, None]) * 1024
        )
        coordinates.append(
            (horizontal.long()[:, None, :] + vertical.long()[:, :, None] + 16) >> 5
        )
    source_x, source_y = coordinates
    x0, y0 = source_x >> 5, source_y >> 5
    fx, fy = source_x & 31, source_y & 31
    h, w = image.shape[:2]
    pixels = image.reshape(-1, 3)
    result = torch.zeros((*source_x.shape, 3), dtype=torch.int32, device=image.device)
    for dy in (0, 1):
        y = y0 + dy
        wy = fy if dy else 32 - fy
        for dx in (0, 1):
            x = x0 + dx
            inside = (x >= 0) & (x < w) & (y >= 0) & (y < h)
            indices = y.clamp(0, h - 1) * w + x.clamp(0, w - 1)
            weights = wy * (fx if dx else 32 - fx) * inside
            result.add_(pixels[indices].int() * weights[..., None].int())
    crops = ((result + 512) >> 10).to(torch.uint8)
    return crops.permute(0, 3, 1, 2).contiguous().float().div_(255.0)


class FusedCrop:
    def __init__(self):
        self.forward = torch.compile(
            warp, fullgraph=True, dynamic=False, options={"triton.cudagraphs": False}
        )
        self.grids = {}
        self.calls = 0

    def __call__(self, image, matrices, size):
        w, h = size
        key = (str(image.device), w, h)
        if key not in self.grids:
            self.grids[key] = (
                torch.arange(w, dtype=torch.float64, device=image.device),
                torch.arange(h, dtype=torch.float64, device=image.device),
            )
        inverse = torch.as_tensor(
            np.stack([cv2.invertAffineTransform(m) for m in matrices]),
            dtype=torch.float64,
            device=image.device,
        )
        out = self.forward(image, inverse, *self.grids[key])
        self.calls += 1
        return out


@contextmanager
def install(enabled=True):
    if not enabled:
        yield None
        return
    from flowhmr.utils import sam_gpu_preprocess as mod

    previous = mod._warp_affine_rgb
    adapter = FusedCrop()
    mod._warp_affine_rgb = adapter
    try:
        yield adapter
    finally:
        mod._warp_affine_rgb = previous
