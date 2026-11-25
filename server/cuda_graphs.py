"""Opt-in, process-local CUDA Graphs adapters. Production and vendor stay read-only.

Instantiate before starting worker threads. Each independent window/chunk begins
one graph iteration; no tensors from a previous iteration survive on GPU.
"""
from contextlib import contextmanager
import torch
from cached_solver import CachedWindowSolver
from persona_flowhmr.perception import Sam3DStreamExtractor

@contextmanager
def compile_graphs(enabled):
    """Scope compiler options to model construction; never leave a global patch."""
    if not enabled:
        yield
        return
    original = torch.compile
    def compile(*args, **kwargs):
        options = dict(kwargs.get('options') or {})
        options['triton.cudagraphs'] = True
        kwargs['options'] = options
        return original(*args, **kwargs)
    torch.compile = compile
    try:
        yield
    finally:
        torch.compile = original

class GraphWindowSolver(CachedWindowSolver):
    def __init__(self, *args, cuda_graphs=False, **kwargs):
        self.cuda_graphs = bool(cuda_graphs and kwargs.get('use_compile', True))
        with compile_graphs(self.cuda_graphs):
            super().__init__(*args, **kwargs)
        self.graph_forward_calls = 0
        self.graph_errors = []
        if self.cuda_graphs and self._compiled_forward is not None:
            forward = self._compiled_forward
            def audited_forward(**inputs):
                try:
                    result = forward(**inputs)
                except Exception as e:
                    self.graph_errors.append(f'{type(e).__name__}: {e}')
                    raise
                self.graph_forward_calls += 1
                return result
            self._compiled_forward = audited_forward

    @torch.no_grad()
    def solve_window(self, *args, **kwargs):
        if self.cuda_graphs and self._compiled_forward is not None:
            torch.compiler.cudagraph_mark_step_begin()
        return super().solve_window(*args, **kwargs)

class GraphSamExtractor(Sam3DStreamExtractor):
    def __init__(self, *args, cuda_graphs=False, **kwargs):
        self.cuda_graphs = bool(cuda_graphs and kwargs.get('use_compile', True))
        with compile_graphs(self.cuda_graphs):
            super().__init__(*args, **kwargs)

    @torch.no_grad()
    def _run_chunked_tokens(self, *args, **kwargs):
        if self.cuda_graphs:
            torch.compiler.cudagraph_mark_step_begin()
        return super()._run_chunked_tokens(*args, **kwargs)
