"""Explicit online model setup; never runs through the offline application entrypoint."""
import os, sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
os.environ['PERSONA_FLOWHMR_MODELS']=str(root/'engine/models')
sys.path.insert(0,str(root/'engine/src'))
def main():
    from persona_flowhmr.setup_models import download_missing_models
    # Uses the upstream downloader and model license terms. Token stays in environment.
    status=download_missing_models(hf_token=os.environ.get('HF_TOKEN'))
    print(status)
    if not status['ready_for_live_camera']: raise SystemExit('Model setup incomplete; see errors above')
    from ultralytics import YOLO
    target=root/'engine/models/yolo26m/yolo26m.pt'
    target.parent.mkdir(parents=True,exist_ok=True)
    YOLO(str(target))
    if not target.is_file(): raise SystemExit('YOLO26m model missing')
    print('Models ready:',root/'engine/models')
if __name__=='__main__':main()
