"""Experimental fixed-tensor cache. Original Persona source is unmodified.

The cache contains read-only constants only; features, dynamic cameras, initial
noise and evolving ODE state are never reused as constant input. Single-solver
calls remain sequential, as in the upstream streaming engine.
"""
from collections import OrderedDict
import time
import numpy as np
import torch
from persona_flowhmr.solver import FlowHMRWindowSolver

class CachedWindowSolver(FlowHMRWindowSolver):
    cache_capacity = 4

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._constant_cache = OrderedDict()
        self.constant_cache_hits = 0
        self.constant_cache_misses = 0

    def _constants(self, window, steps):
        key = (str(self.device), torch.float32, window, steps, self.vtxt_dim)
        entry = self._constant_cache.get(key)
        if entry is not None:
            self._constant_cache.move_to_end(key)
            self.constant_cache_hits += 1
            return entry
        self.constant_cache_misses += 1
        ts = torch.linspace(0., 1., steps + 1, device=self.device, dtype=torch.float32)
        entry = dict(
            camera=torch.eye(3, device=self.device, dtype=torch.float32).reshape(1, 1, 9).expand(1, window, 9).contiguous(),
            text=torch.zeros((1, 1, self.vtxt_dim), device=self.device, dtype=torch.float32),
            mask=torch.ones((1, window), device=self.device, dtype=torch.bool),
            times=tuple(ts[i].expand(1) for i in range(steps)),
            dts=tuple(ts[i+1]-ts[i] for i in range(steps)),
            denominators=tuple(torch.clamp(1.-ts[i], min=1./float(steps)) for i in range(steps)),
        )
        self._constant_cache[key] = entry
        if len(self._constant_cache) > self.cache_capacity:
            self._constant_cache.popitem(last=False)
        return entry

    @torch.no_grad()
    def solve_window(self, sam_tokens_w_3072, frame_indices, *, ode_steps=None, camera_r_w_9=None):
        window = int(sam_tokens_w_3072.shape[0])
        if len(frame_indices) != window:
            raise ValueError(f'frame_indices length {len(frame_indices)} != window {window}')
        steps = int(ode_steps or self.default_steps)
        if steps < 1:
            raise ValueError(f'ode_steps must be >= 1, got {steps}')
        t_start = time.perf_counter()
        c = self._constants(window, steps)
        feature = sam_tokens_w_3072.unsqueeze(0).to(self.device, dtype=torch.float32, non_blocking=True)
        if camera_r_w_9 is None:
            camera = c['camera']
        else:
            camera = torch.as_tensor(camera_r_w_9, dtype=torch.float32).reshape(1, window, 9).to(self.device, dtype=torch.float32, non_blocking=True)
        ctxt_input = {'feature': feature, 'camera_R': camera}
        y0 = self._noise_for_frame_indices(frame_indices)
        x = y0.clone()
        forward_fn = self._compiled_forward or self.eager_model.forward
        for i in range(steps):
            inputs = dict(x=x, ctxt_input=ctxt_input, vtxt_input=c['text'], timesteps=c['times'][i], x_mask_temporal=c['mask'], ctxt_mask_temporal=c['mask'])
            try:
                prediction = forward_fn(**inputs)
            except Exception:
                self._compiled_forward = None
                forward_fn = self.eager_model.forward
                prediction = forward_fn(**inputs)
            if self.pred_type == 'velocity':
                velocity = prediction
            elif self.pred_type == 'x1':
                velocity = (prediction-x)/c['denominators'][i]
            elif self.pred_type == 'x1raw':
                velocity = prediction-y0
            else:
                raise NotImplementedError(f'Unsupported pred_type: {self.pred_type}')
            x = x+c['dts'][i]*velocity
        out = x[0].detach().cpu().numpy().astype(np.float32)
        self.last_solve_ms = (time.perf_counter()-t_start)*1000.
        return out
