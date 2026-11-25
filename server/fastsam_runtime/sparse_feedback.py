"""Experimental sparse intermediate pose feedback; retain all Transformer layers."""
from contextlib import contextmanager
@contextmanager
def install(model):
    originals=[];state={'pose_computations':0,'pose_reuses':0}
    try:
        for decoder in [model.decoder,model.decoder_hand]:
            original=decoder.forward
            def make(forward):
                def wrapped(*args,**kwargs):
                    callback=kwargs.get('token_to_pose_output_fn')
                    if callback is None:return forward(*args,**kwargs)
                    cache=[]
                    def sparse(*a,**k):
                        if not cache:
                            cache.append(callback(*a,**k));state['pose_computations']+=1
                        else:state['pose_reuses']+=1
                        return cache[0]
                    kwargs['token_to_pose_output_fn']=sparse
                    return forward(*args,**kwargs)
                return wrapped
            originals.append((decoder,original));decoder.forward=make(original)
        yield state
    finally:
        for decoder,original in originals:decoder.forward=original
