"""Call install(config) in a fresh backend before engine/model import or construction."""
def install(config):
    if not config.get('fast_sam_enabled', True):
        return None  # Preserve all existing bindings in an unchanged, fresh process.
    from .runtime import FastSamExtractor
    from persona_flowhmr import engine
    options = dict(
        compile_crop=config.get('fast_sam_compile_crop', config.get('torch_compile', True)),
        zero_mask_contract=config.get('fast_sam_zero_mask_contract', True),
        feedback=config.get('fast_sam_feedback', True),
        prompt_cache=config.get('fast_sam_prompt_cache', True))
    if any(type(v) is not bool for v in options.values()):
        raise TypeError('Fast SAM optimization flags must be JSON booleans')
    existing=engine.Sam3DStreamExtractor
    if existing is not FastSamExtractor and getattr(existing,'backend_name',None)=='fast_sam_3d_body':
        raise RuntimeError('Fast already installed: restart rather than stacking adapters')
    FastSamExtractor.options=options
    engine.Sam3DStreamExtractor=FastSamExtractor
    return FastSamExtractor

def status(extractor):
    getter=getattr(extractor,'fast_status',None)
    return getter() if getter else dict(name='existing_sam', loaded=extractor is not None, fast_enabled=False)
