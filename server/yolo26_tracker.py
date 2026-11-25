"""YOLO26m detector with the existing ByteTrack/EMA/interpolation contract."""
from pathlib import Path
import os,sys
import numpy as np,torch
from persona_flowhmr.perception import BatchedYoloxTracker
from persona_flowhmr.paths import MODELS_DIR
# Optional application-local packages, never replace the base Torch/CUDA environment.
_here=Path(__file__).resolve().parent
_libs=Path(os.environ.get('FLOWHMR_YOLO26_LIBS',str(_here/'yolo26-switch-20261123/libs')))
if _libs.is_dir():sys.path.insert(0,str(_libs))
os.environ.setdefault('YOLO_AUTOINSTALL','false')
os.environ.setdefault('YOLO_CONFIG_DIR',str(_here/'yolo26-state'))
Path(os.environ['YOLO_CONFIG_DIR']).mkdir(parents=True,exist_ok=True)
class Yolo26Tracker(BatchedYoloxTracker):
 detector_backend='yolo26m'
 def __init__(self,ckpt_path=None,device='cuda',test_size=(416,416),yolo_stride=2,bbox_thr=.45,nms_thr=.30,ema_alpha=.65):
  from ultralytics import YOLO,settings
  settings.update({'sync':False})
  self.device=torch.device(device);self.bbox_thr=float(bbox_thr);self.nms_thr=float(nms_thr);self.ema_alpha=float(ema_alpha)
  self.weights=Path(os.environ.get('FLOWHMR_YOLO26_WEIGHTS',str(MODELS_DIR/'yolo26m/yolo26m.pt')))
  if not self.weights.is_file():raise FileNotFoundError(f'YOLO26m weights missing: {self.weights}')
  self.detector=YOLO(str(self.weights),task='detect');self.model=self.detector.model
  self._dtype=torch.float16 if self.device.type=='cuda' else torch.float32
  self.configure(test_size=test_size,yolo_stride=yolo_stride);self.predict_calls=0;self.detected_frames=0
 def _predict(self,rgb_frames):
  from ultralytics.utils import nms,ops
  from ultralytics.engine.results import Results
  # Initialize the official backend once, never invoke its dataset/stream wrapper per batch.
  if self.detector.predictor is None:
   self.detector.predict(source=[np.zeros((*self.test_size,3),np.uint8)],classes=[0],conf=self.bbox_thr,iou=self.nms_thr,imgsz=self.test_size,rect=False,device=str(self.device),half=self.device.type=='cuda',verbose=False,save=False)
  backend=self.detector.predictor.model
  h,w=rgb_frames[0].shape[:2];th,tw=self.test_size;gain=min(th/h,tw/w);nh,nw=round(h*gain),round(w*gain);left=round((tw-nw)/2-.1);top=round((th-nh)/2-.1)
  raw=torch.from_numpy(np.stack(rgb_frames)).to(self.device).permute(0,3,1,2).float()
  resized=torch.nn.functional.interpolate(raw,size=(nh,nw),mode='bilinear',align_corners=False).round().clamp_(0,255).to(dtype=self._dtype)
  batch=torch.full((len(rgb_frames),3,th,tw),114.,device=self.device,dtype=self._dtype);batch[:,:,top:top+nh,left:left+nw]=resized;batch.div_(255.)
  prediction=backend(batch)
  detections=nms.non_max_suppression(prediction,self.bbox_thr,self.nms_thr,classes=[0],agnostic=False,max_det=300,nc=0,end2end=getattr(backend,'end2end',False),rotated=False)
  result=[]
  for i,(det,rgb) in enumerate(zip(detections,rgb_frames)):
   det[:,:4]=ops.scale_boxes(batch.shape[2:],det[:,:4],(h,w),ratio_pad=((gain,gain),(left,top)))
   result.append(Results(rgb,path=f'frame{i}',names=backend.names,boxes=det[:,:6]))
  self.predict_calls+=1;self.detected_frames+=len(result);return result
 @torch.no_grad()
 def warmup(self,batch_size=4):
  self._predict([np.zeros((*self.test_size,3),np.uint8) for _ in range(max(1,int(batch_size)))])
  if self.device.type=='cuda':torch.cuda.synchronize(self.device)
 @torch.no_grad()
 def detect_and_track_batch(self,rgb_frames,*,reset_flags=None):
  n=len(rgb_frames)
  if not n:return np.zeros((0,4),np.float32)
  if reset_flags is not None and len(reset_flags)!=n:raise ValueError('reset_flags must match frames')
  h,w=rgb_frames[0].shape[:2]
  if any(im.shape[:2]!=(h,w) for im in rgb_frames):raise ValueError('Batch frame dimensions differ')
  indices=set(range(0,n,self.yolo_stride));indices.add(n-1)
  if reset_flags is not None:
   for i,reset in enumerate(reset_flags):
    if reset:
     indices.add(i)
     if i:indices.add(i-1)
  indices=sorted(indices);results=self._predict([rgb_frames[i] for i in indices])
  if len(results)!=len(indices):raise RuntimeError('YOLO26 output batch mismatch')
  key_boxes={};full_box=np.array([0,0,w,h],np.float32)
  for i,result in zip(indices,results):
   if reset_flags is not None and reset_flags[i]:self.reset_tracker()
   boxes=result.boxes;det=None
   if boxes is not None and len(boxes):
    # Original tracker expects xyxy,obj_conf,class_conf,class_id in original pixels.
    xyxy=boxes.xyxy;conf=boxes.conf.reshape(-1,1);det=torch.cat([xyxy,conf,torch.ones_like(conf),boxes.cls.reshape(-1,1)],dim=1)
   key_boxes[i]=self._step_single_frame(det,1.0,w,h,full_box)
  out=np.empty((n,4),np.float32);seg=0
  for i in range(n):
   if i in key_boxes:out[i]=key_boxes[i];continue
   while seg+1<len(indices)-1 and i>indices[seg+1]:seg+=1
   i0,i1=indices[seg:seg+2];a=(i-i0)/max(1,i1-i0);out[i]=(1-a)*key_boxes[i0]+a*key_boxes[i1]
  if not np.isfinite(out).all() or np.any(out[:,2:]<=out[:,:2]):raise RuntimeError('Invalid tracked boxes')
  return out
