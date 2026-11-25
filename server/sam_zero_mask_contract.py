"""Track only unchanged batches from the audited zero-mask GPU producer.

Python object identity checks introduce no GPU synchronization. No tensors are
cached across extraction calls. Noncontrolled batches retain the original path.
"""

import threading
from contextlib import contextmanager


@contextmanager
def verified_batches():
    from flowhmr.utils import lite_sam_infer as inference
    from flowhmr.utils import sam_gpu_preprocess as producer

    owner = threading.get_ident()
    known = []
    previous_prepare = producer.prepare_gpu_batch
    previous_combine = inference._combine_batches

    def remember(batch):
        known.append((batch["mask"], batch["mask_score"]))
        return batch

    def accepts(batch):
        return threading.get_ident() == owner and any(
            batch.get("mask") is mask and batch.get("mask_score") is score
            for mask, score in known
        )

    def prepare(*args, **kwargs):
        batch = previous_prepare(*args, **kwargs)
        return remember(batch) if threading.get_ident() == owner else batch

    def combine(batches, device):
        controlled = all(accepts(batch) for batch in batches)
        batch = previous_combine(batches, device)
        return remember(batch) if controlled else batch

    producer.prepare_gpu_batch = prepare
    inference._combine_batches = combine
    try:
        yield accepts
    finally:
        producer.prepare_gpu_batch = previous_prepare
        inference._combine_batches = previous_combine
        known.clear()
