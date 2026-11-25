"""Strict, persistent inference parameters. Applies only while input is stopped."""
import json,os,tempfile,threading,time
from dataclasses import replace
from pathlib import Path
SCHEMA={
 'playout_delay_ms':{'label':'延迟预算(ms)','values':[200,300,400,500,600,700,800,1000]},
 'sam_chunk_size':{'label':'SAM批次','values':[1,2]},
 'target_fps':{'label':'目标帧率','values':[20,25,30]},
 'sam_stride':{'label':'SAM间隔帧数','values':[1,2,3,4,5,6]},
 'body_decoder_layers':{'label':'身体解码层数','values':[1,2,3,4,5,6]},
 'ode_steps':{'label':'FlowHMR步数','values':list(range(1,17))},
 'yolo_size':{'label':'YOLO26m检测尺寸','values':[416,640]},
 'hand_mode':{'label':'手部推理','values':['off','fast','full']},
 'hand_decoder_layers':{'label':'手部解码层数','values':[1,2,3,4,5,6]},
}
DEFAULTS={'playout_delay_ms':800,'sam_chunk_size':2,'target_fps':30,'sam_stride':4,'body_decoder_layers':4,'ode_steps':2,'yolo_size':416,'hand_mode':'fast','hand_decoder_layers':1}
class ParameterError(Exception):
 def __init__(self,status,message):super().__init__(message);self.status=status
class ParameterControl:
 def __init__(self,engine,operation,input_stats,presets,path):
  self.engine=engine;self.operation=operation;self.input_stats=input_stats;self.presets=presets;self.path=Path(path);self.lock=threading.RLock();self.revision=0;self.saved_at=None
  if self.path.exists():
   data=json.loads(self.path.read_text(encoding='utf-8'));values=self.validate(data['values'],complete=True)
   if type(data['revision']) is not int or data['revision']<0:raise ValueError('Invalid saved parameter revision')
   self._set(values);self.revision=data['revision'];self.saved_at=data.get('saved_at')
 def values(self):
  cfg=self.engine.config;p=self.presets[cfg.preset]
  return {'playout_delay_ms':int(round(p.playout_delay_s*1000)),'sam_chunk_size':int(p.sam_chunk_size),'target_fps':int(cfg.playout_fps),'sam_stride':int(cfg.effective_sam_stride()),'body_decoder_layers':int(p.body_decoder_layers),'ode_steps':int(p.ode_steps),'yolo_size':int(cfg.effective_yolo_size()[0]),'hand_mode':cfg.effective_hand_mode(),'hand_decoder_layers':int(p.hand_decoder_layers)}
 @staticmethod
 def validate(values,complete=False):
  if complete and isinstance(values,dict) and 'target_fps' not in values:values=dict(values,target_fps=30)
  if complete and isinstance(values,dict):values={'playout_delay_ms':800,'sam_chunk_size':2,**values}
  if not isinstance(values,dict) or not values or set(values)-set(SCHEMA) or (complete and set(values)!=set(SCHEMA)):raise ParameterError(400,'参数字段错误。')
  for key,value in values.items():
   allowed=SCHEMA[key]['values'];expected=str if key=='hand_mode' else int
   if type(value) is not expected or value not in allowed:raise ParameterError(400,'参数范围错误：'+key)
  return dict(values)
 def _set(self,values):
  cfg=self.engine.config
  self.presets[cfg.preset]=replace(self.presets[cfg.preset],body_decoder_layers=values['body_decoder_layers'],hand_decoder_layers=values['hand_decoder_layers'],ode_steps=values['ode_steps'],playout_delay_s=values['playout_delay_ms']/1000,sam_chunk_size=values['sam_chunk_size'])
  cfg.playout_fps=values['target_fps'];cfg.sam_stride=values['sam_stride'];cfg.yolo_size=values['yolo_size'];cfg.hand_mode=values['hand_mode']
 def snapshot(self):
  with self.lock:return {'revision':self.revision,'values':self.values(),'schema':SCHEMA,'defaults':DEFAULTS,'active':bool(self.engine.is_running or self.input_stats['active']),'saved_at':self.saved_at,'effective_on':'next_input_start','warmup_notice':'改变层数、手部或检测尺寸，下一次开始可能重新预热。'}
 def _persist(self,values,revision,saved_at):
  self.path.parent.mkdir(parents=True,exist_ok=True);temp=None
  try:
   with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=self.path.parent,prefix='.client-parameters-',delete=False) as f:
    temp=f.name;os.chmod(temp,0o600);json.dump({'revision':revision,'values':values,'saved_at':saved_at},f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
   os.replace(temp,self.path);temp=None
  finally:
   if temp:Path(temp).unlink(missing_ok=True)
 def apply(self,payload):
  if not isinstance(payload,dict) or set(payload)!={'revision','values'} or type(payload.get('revision')) is not int:raise ParameterError(400,'请求格式错误。')
  patch=self.validate(payload['values'])
  with self.operation,self.lock:
   if self.engine.is_running or self.input_stats['active']:raise ParameterError(409,'请先停止视频采集，等待服务器推理停止，再应用参数。')
   if payload['revision']!=self.revision:raise ParameterError(409,'参数已被其他客户端修改，请先重新读取。')
   before=self.values();candidate=self.validate(before|patch,complete=True)
   if candidate==before:return self.snapshot()|{'changed':False}
   stamp=time.time();revision=self.revision+1
   self._set(candidate)
   try:self._persist(candidate,revision,stamp)
   except Exception:
    self._set(before);raise
   self.revision=revision;self.saved_at=stamp
   return self.snapshot()|{'changed':True}
def install(app,engine,operation,input_stats,presets,path):
 from fastapi import HTTPException
 control=ParameterControl(engine,operation,input_stats,presets,path)
 @app.get('/client-settings')
 def read_parameters():return control.snapshot()
 @app.post('/client-settings')
 def write_parameters(payload:dict):
  try:return control.apply(payload)
  except ParameterError as exc:raise HTTPException(exc.status,str(exc)) from None
  except OSError:raise HTTPException(503,'参数保存失败，原参数保持不变。') from None
 return control
