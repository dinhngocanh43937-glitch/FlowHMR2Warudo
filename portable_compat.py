"""Process-local Windows Unicode path adapter; upstream/vendor are unmodified."""
import functools
import os


def install_torch_unicode_io():
    import torch
    if getattr(torch.jit.load,'_portable_unicode_io',False):return
    original=torch.jit.load
    @functools.wraps(original)
    def load(f,*args,**kwargs):
        if isinstance(f,(str,os.PathLike)):
            path=os.fspath(f)
            if isinstance(path,str) and not path.isascii():
                # torch 2.8's C++ fopen rejects Unicode paths on Windows. The
                # public file-like API uses Python's Unicode-aware open instead.
                with open(path,'rb') as stream:
                    return original(stream,*args,**kwargs)
        return original(f,*args,**kwargs)
    load._portable_unicode_io=True
    torch.jit.load=load
