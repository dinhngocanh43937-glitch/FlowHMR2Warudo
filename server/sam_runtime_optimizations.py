"""Reference integration: test on the target Windows GPU before release."""

import threading
from contextlib import nullcontext
from functools import wraps

from sam_fused_crop import FusedCrop
from sam_no_mask_prompt import install as install_no_mask
from sam_zero_mask_contract import verified_batches

_LOCK = threading.RLock()


def make_extractor(base, *, fused_crop=True, no_mask_prompt=True):
    class OptimizedSAM(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            cuda = self.device.type == "cuda"
            use_crop = bool(fused_crop and cuda)
            use_mask = bool(no_mask_prompt and cuda)
            crop = FusedCrop() if use_crop else None
            original_extract = self._extract_tokens
            self.sam_optimization_stats = {
                "fused_crop_requested": bool(fused_crop),
                "no_mask_requested": bool(no_mask_prompt),
                "cuda": cuda,
                "eligible_calls": 0,
                "fallback_calls": 0,
                "crop_calls": 0,
                "mask_prompt_calls": 0,
                "errors": 0,
            }

            @wraps(original_extract)
            def extract(*args, **kwargs):
                # Only this producer guarantees mask_score=0 and the same GPU crop semantics.
                if not cuda or not kwargs.get("gpu_preprocess", False):
                    self.sam_optimization_stats["fallback_calls"] += 1
                    return original_extract(*args, **kwargs)
                from flowhmr.utils import sam_gpu_preprocess as module

                with _LOCK:
                    previous_crop = module._warp_affine_rgb
                    state = None
                    try:
                        if crop is not None:
                            module._warp_affine_rgb = crop
                        contract = verified_batches() if use_mask else nullcontext(None)
                        with contract as accept_batch:
                            context = (
                                install_no_mask(
                                    self.estimator.model, accept_batch=accept_batch
                                )
                                if use_mask
                                else nullcontext(None)
                            )
                            with context as state:
                                result = original_extract(*args, **kwargs)
                        self.sam_optimization_stats["eligible_calls"] += 1
                        return result
                    except Exception:
                        self.sam_optimization_stats["errors"] += 1
                        # Do not hide OOM, compile errors, or model errors.
                        raise
                    finally:
                        module._warp_affine_rgb = previous_crop
                        self.sam_optimization_stats["crop_calls"] = (
                            crop.calls if crop else 0
                        )
                        if state is not None:
                            self.sam_optimization_stats["mask_prompt_calls"] += state[
                                "calls"
                            ]

            self._extract_tokens = extract

    return OptimizedSAM
