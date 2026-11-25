"""Read-only source installation checks. Does not start inference or Warudo."""
import importlib, shutil, sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
def main():
    failed=[]
    for name in ['torch','torchvision','triton','av','cv2','PIL','ultralytics','tkinter','fastapi','websockets']:
        try: importlib.import_module(name); print('OK',name)
        except Exception as exc: failed.append(name); print('ERROR',name,str(exc))
    for name in ['ffmpeg','ffprobe']:
        ok=(root/'tools/bin'/f'{name}.exe').is_file() or bool(shutil.which(name))
        print('OK' if ok else 'MISSING',name)
        if not ok: failed.append(name)
    import torch
    print('CUDA available:',torch.cuda.is_available())
    if not torch.cuda.is_available(): failed.append('CUDA')
    if failed: raise SystemExit('Resolve missing components: '+', '.join(failed))
if __name__=='__main__': main()
