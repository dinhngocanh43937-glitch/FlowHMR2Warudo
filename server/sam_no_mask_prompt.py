"""Eliminate discarded mask convolutions in the fixed zero-mask GPU-crop path.

This is a specialization for the existing GPU prepare batch that always creates
mask_score=0. Do not install for callers supplying segmentation masks/scores.
"""

from contextlib import contextmanager


@contextmanager
def install(model, enabled=True, *, accept_batch=None):
    state = {
        "calls": 0,
        "contract": "GPU prepare_gpu_batch always supplies mask_score=0",
    }
    if not enabled:
        yield state
        return
    assert model.cfg.MODEL.PROMPT_ENCODER.get("MASK_EMBED_TYPE") is not None
    assert model.cfg.MODEL.PROMPT_ENCODER.get("MASK_PROMPT", "v1") == "v1"
    original = model._get_mask_prompt
    had_instance = "_get_mask_prompt" in model.__dict__
    prior_instance = model.__dict__.get("_get_mask_prompt")

    def get_mask_prompt(batch, image_embeddings):
        if accept_batch is None or not accept_batch(batch):
            return original(batch, image_embeddings)
        _, no_mask = model.prompt_encoder.get_mask_embeddings(
            None, image_embeddings.shape[0], image_embeddings.shape[2:]
        )
        state["calls"] += 1
        # Original torch.where with score=0 always selects these same values.
        return no_mask.to(image_embeddings).contiguous()

    model._get_mask_prompt = get_mask_prompt
    try:
        yield state
    finally:
        if had_instance:
            model._get_mask_prompt = prior_instance
        else:
            del model._get_mask_prompt
