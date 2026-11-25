"""Windows-oriented application adapter derived from the verified Linux Fast pipeline.
No checkpoint, detector, solver, transport or user parameter replacement.
"""
import inspect
import threading
from contextlib import ExitStack
from pathlib import Path
from . import loader
PACKAGE_SOURCE = loader.activate()  # Must precede any original sam_3d_body import.
from persona_flowhmr.perception import Sam3DStreamExtractor
from .fused_crop import FusedCrop
from .no_mask_prompt import install as no_mask
from .sparse_feedback import install as sparse_feedback
from .prompt_cache import install as prompt_cache
LOCK = threading.RLock()

class FastSamExtractor(Sam3DStreamExtractor):
    backend_name = 'fast_sam_3d_body'
    options = dict(compile_crop=True, zero_mask_contract=True, feedback=True, prompt_cache=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fast_options = dict(self.options)
        model = self.estimator.model
        for head in (model.head_pose, model.head_pose_hand):
            schema = str(head.mhr.forward.schema)
            if 'bool apply_correctives' not in schema:
                raise RuntimeError('MHR asset interface mismatch: expected bool apply_correctives; retain original assets and inspect compatibility before continuing')
        loader.adapt_model(model, no_correctives=False, compile_slim=False)
        self.fast_model_source = inspect.getfile(type(model))
        if not Path(self.fast_model_source).resolve().is_relative_to((loader.P/'vendor').resolve()):
            raise RuntimeError('Loaded model is not the bundled pinned Fast implementation')
        self.crop = FusedCrop(compile_enabled=self.fast_options['compile_crop'] and self._use_compile)
        self.fast_stats = dict(calls=0, crop_calls=0, mask_calls=0, pose_computations=0, pose_reuses=0, errors=0)
        self.prompt_stats = {k:0 for k in ('computations_2d','hits_2d','computations_3d','hits_3d','decoder_calls','uncacheable')}
        original = self._extract_tokens
        def extract(*a, **kw):
            if not kw.get('gpu_preprocess', False) or self.device.type != 'cuda':
                return original(*a, **kw)
            from flowhmr.utils import sam_gpu_preprocess as mod
            with LOCK, ExitStack() as stack:
                old = mod._warp_affine_rgb
                mask = pose = cached = None
                try:
                    mod._warp_affine_rgb = self.crop
                    if self.fast_options['zero_mask_contract']:
                        mask = stack.enter_context(no_mask(model))
                    if self.fast_options['feedback']:
                        pose = stack.enter_context(sparse_feedback(model))
                    cached = stack.enter_context(prompt_cache(model, self.fast_options['prompt_cache']))
                    out = original(*a, **kw)
                    self.fast_stats['calls'] += 1
                    return out
                except Exception:
                    self.fast_stats['errors'] += 1
                    raise
                finally:
                    mod._warp_affine_rgb = old
                    self.fast_stats['crop_calls'] = self.crop.calls
                    if mask: self.fast_stats['mask_calls'] += mask['calls']
                    if pose:
                        for k in ('pose_computations','pose_reuses'): self.fast_stats[k] += pose[k]
                    if cached:
                        for k,v in cached.items(): self.prompt_stats[k] += v
        self._extract_tokens = extract

    def fast_status(self):
        model = self.estimator.model
        return dict(name=self.backend_name, loaded=True, profile='keep_correctives',
            upstream_commit='d72aa36913a1673ace029d345f437561a85ec9e2',
            package_source=PACKAGE_SOURCE, model_source=self.fast_model_source,
            correctives=bool(model.head_pose.apply_correctives and model.head_pose_hand.apply_correctives),
            backbone_dtype=str(getattr(model,'backbone_dtype',None)),
            backbone_compile=getattr(model.backbone,'_flowhmr_compile_state',None),
            crop_compile_requested=self.crop.compile_requested,
            options=dict(self.fast_options), optimizations=dict(self.fast_stats),
            prompt_cache=dict(self.prompt_stats), tensorrt=False)
