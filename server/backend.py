"""Shared local/remote inference bridge; real engine unchanged, no Persona scene access."""
import argparse,asyncio,contextlib,json,math,secrets,socket,subprocess,threading,time,uuid
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI,HTTPException,Request,WebSocket,WebSocketDisconnect
from protocol import pack
from runtime_parameters import ParameterControl,ParameterError
from network_input import install as install_input

DEFAULTS={'sam_stride':4,'body_decoder_layers':4,'ode_steps':2,'yolo_size':416,'hand_mode':'fast','hand_decoder_layers':1}

def build_engine(config,udp_port):
 from dataclasses import replace
 import torch
 from portable_compat import install_torch_unicode_io
 install_torch_unicode_io()
 from fastsam_runtime.integration import install as install_fast_sam
 install_fast_sam(config)
 from persona_flowhmr import engine as module
 from persona_flowhmr.config import EngineConfig,LATENCY_PRESETS
 from cuda_graphs import GraphWindowSolver
 if not torch.cuda.is_available():raise RuntimeError('NVIDIA CUDA GPU not detected. Run check-local.cmd and inspect the driver/environment.')
 class Solver(GraphWindowSolver):
  def __init__(self,*a,**kw):
   super().__init__(*a,cuda_graphs=config.get('flow_cuda_graphs',True),**kw)
   self.compile_calls=0;self.compile_error=None;forward=self._compiled_forward
   if forward is not None:
    def audited(**inputs):
     try:out=forward(**inputs)
     except Exception as exc:self.compile_error=type(exc).__name__+': '+str(exc);raise
     self.compile_calls+=1;return out
    self._compiled_forward=audited
  def solve_window(self,*a,**kw):
   self.last_steps=int(kw.get('ode_steps') or self.default_steps)
   return super().solve_window(*a,**kw)
 from yolo26_tracker import Yolo26Tracker
 from frame_rate_adapter import rate_aware_tracker
 module.BatchedYoloxTracker=rate_aware_tracker(Yolo26Tracker,lambda:engine.config.playout_fps)
 module.FlowHMRWindowSolver=Solver
 from persona_flowhmr.perception import Sam3DStreamExtractor as OriginalSAM
 from sam_runtime_optimizations import make_extractor
 if not config.get('fast_sam_enabled',True):
  module.Sam3DStreamExtractor=make_extractor(OriginalSAM,fused_crop=config.get('sam_fused_crop',True) and config.get('torch_compile',True),no_mask_prompt=config.get('sam_no_mask_prompt',True))
 values=ParameterControl.validate(config.get('parameters',DEFAULTS),complete=True)
 LATENCY_PRESETS['ultra_low']=replace(LATENCY_PRESETS['ultra_low'],body_decoder_layers=values['body_decoder_layers'],hand_decoder_layers=values['hand_decoder_layers'],ode_steps=values['ode_steps'],playout_delay_s=values['playout_delay_ms']/1000,sam_chunk_size=values['sam_chunk_size'])
 class LocalStreamingMocapEngine(module.StreamingMocapEngine):
  def _playout_worker(self,first_commit_event,realtime_source):
   while not self._stop_event.is_set():
    if self.telemetry.state=='error':return
    if first_commit_event.wait(.2):break
   if self._stop_event.is_set():return
   return super()._playout_worker(first_commit_event,realtime_source)
 engine=LocalStreamingMocapEngine(EngineConfig(source_mode='camera',preset='ultra_low',sam_stride=values['sam_stride'],hand_mode=values['hand_mode'],yolo_size=values['yolo_size'],playout_fps=values['target_fps'],torch_compile=config.get('torch_compile',True),perception_backend='sam3d',camera_tracking_enabled=False,vmc_enabled=True,vmc_host='127.0.0.1',vmc_port=udp_port,plugin_api_enabled=False))
 return engine,module,LATENCY_PRESETS

class Runtime:
 def __init__(self,config,state,engine=None,engine_module=None,presets=None):
  self.config=config;self.state=Path(state);self.state.mkdir(parents=True,exist_ok=True)
  self.read_token=config['read_token'];self.write_token=config['input_token']
  if min(len(self.read_token),len(self.write_token))<32:raise ValueError('Tokens require 32 or more characters')
  if self.read_token==self.write_token:raise ValueError('Read and input tokens must differ')
  self.sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);self.sock.bind(('127.0.0.1',0));self.sock.settimeout(.2)
  self.udp_port=self.sock.getsockname()[1]
  if engine is None:
   try:engine,engine_module,presets=build_engine(config,self.udp_port)
   except BaseException:self.sock.close();raise
  self.engine=engine;self.engine_module=engine_module;self.presets=presets
  self.operation=threading.Lock();self.lock=threading.Lock();self.stop=threading.Event()
  self.generation=uuid.uuid4().hex;self.seq=0;self.latest=None;self.clients=0;self.motion_sent=0;self.invalid=0
  self.gpu={'available':False,'error':'not sampled'};self.gpu_time=0
 def on_session(self,session):
  with self.lock:self.generation=uuid.uuid4().hex;self.latest=None
 def receive(self):
  while not self.stop.is_set():
   try:payload,_=self.sock.recvfrom(65535)
   except socket.timeout:continue
   except OSError:break
   if not payload.startswith(b'#bundle\0') or len(payload)>65000:self.invalid+=1;continue
   now=time.time()
   with self.lock:
    self.seq+=1;self.latest=(self.generation,self.seq,now,pack(self.generation,self.seq,now,payload))
 def auth(self,headers,write=False):
  expected='Bearer '+(self.write_token if write else self.read_token)
  if not secrets.compare_digest(headers.get('authorization',''),expected):raise HTTPException(403,'Forbidden')
 def gpu_sample(self):
  if not self.config.get('gpu_metrics',True):return
  try:
   flags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess,'CREATE_NO_WINDOW') else 0
   result=subprocess.run(['nvidia-smi','--query-gpu=index,name,memory.total,memory.used,utilization.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=3,creationflags=flags)
   if result.returncode:raise RuntimeError('nvidia-smi failed')
   import csv,io
   rows=list(csv.reader(io.StringIO(result.stdout)))
   self.gpu={'available':True,'sampled_at':time.time(),'devices':[{'index':int(r[0]),'name':r[1].strip(),'total_mib':float(r[2]),'used_mib':float(r[3]),'utilization_percent':float(r[4])} for r in rows],'worker_used_mib':None,'worker_attribution':'not attributed','compute_process_count':None}
  except Exception as exc:self.gpu={'available':False,'sampled_at':time.time(),'error':type(exc).__name__}
 def monitor(self):
  while not self.stop.is_set():self.gpu_sample();self.stop.wait(3)
 def metrics(self):
  from fastsam_runtime.integration import status as fast_sam_status
  e=self.engine;p=e.config.get_preset();sam=getattr(e,'_sam3d',None);solver=getattr(e,'_solver',None)
  return dict(available=True,sampled_at=time.time(),fast_sam=fast_sam_status(sam),running=e.is_running,telemetry=vars(e.telemetry).copy(),config=dict(playout_delay_ms=int(p.playout_delay_s*1000),sam_chunk_size=p.sam_chunk_size,target_fps=e.config.playout_fps,model_fps=30,quality='fast',preset=e.config.preset,hand_mode=e.config.hand_mode,yolo_size=e.config.yolo_size,ode_steps=p.ode_steps,body_decoder_layers=p.body_decoder_layers,hand_decoder_layers=p.hand_decoder_layers,sam_stride=e.config.sam_stride,torch_compile=e.config.torch_compile,camera_tracking=False),parameters=self.parameters.snapshot(),runtime_config={'sam':{k:getattr(sam,k,None) for k in ['hand_mode','body_decoder_layers','hand_decoder_layers','chunk_size']},'solver_observed_steps':getattr(solver,'last_steps',None)},network_input=dict(self.network),input_queue_capacity=2,constant_cache={'hits':getattr(solver,'constant_cache_hits',0),'misses':getattr(solver,'constant_cache_misses',0)},solver_compile={'enabled':getattr(solver,'_compiled_forward',None) is not None,'successful_calls':getattr(solver,'compile_calls',0),'error':getattr(solver,'compile_error',None)},sam_optimizations=dict(getattr(sam,'sam_optimization_stats',{'state':'not_loaded','crop_calls':0,'mask_prompt_calls':0})),sam_compile={'error':(getattr(getattr(getattr(getattr(sam,'estimator',None),'model',None),'backbone',None),'_flowhmr_compile_state',None) or {}).get('error'),'status':(getattr(getattr(getattr(getattr(sam,'estimator',None),'model',None),'backbone',None),'_flowhmr_compile_state',None) or {}).get('status')},cuda_graphs={'forward_calls':getattr(solver,'graph_forward_calls',0),'flow_requested':self.config.get('flow_cuda_graphs',True),'sam_requested':False,'errors':getattr(solver,'graph_errors',[])},relay={'clients':self.clients,'upstream_messages':self.seq,'upstream_connected':True,'sent':self.motion_sent,'invalid_packets':self.invalid},gpu=self.gpu,deployment_mode=self.config.get('deployment_mode','local'))

def create_app(config,state,engine=None,engine_module=None,presets=None):
 runtime=Runtime(config,state,engine,engine_module,presets)
 @asynccontextmanager
 async def lifespan(app):
  threads=[threading.Thread(target=runtime.receive,daemon=True),threading.Thread(target=runtime.monitor,daemon=True)]
  for t in threads:t.start()
  try:yield
  finally:
   runtime.stop.set();await asyncio.to_thread(runtime.engine.stop);runtime.sock.close()
   for t in threads:await asyncio.to_thread(t.join,4)
 app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None);app.state.runtime=runtime
 token_file=runtime.state/'input-token.txt';token_file.write_text(runtime.write_token);token_file.chmod(0o600)
 runtime.network=install_input(app,runtime.engine_module,runtime.engine,runtime.operation,str(token_file),runtime.on_session,allow_raw=config.get('deployment_mode')=='local')
 runtime.parameters=ParameterControl(runtime.engine,runtime.operation,runtime.network,runtime.presets,runtime.state/'parameters.json')
 @app.get('/health')
 def health():return {'service':'motion-inference','ready':True,'deployment_mode':config.get('deployment_mode','local')}
 @app.get('/metrics')
 def metrics(request:Request):runtime.auth(request.headers);return runtime.metrics()
 @app.get('/settings')
 def read_settings(request:Request):runtime.auth(request.headers);return runtime.parameters.snapshot()
 @app.post('/settings')
 def write_settings(request:Request,payload:dict):
  runtime.auth(request.headers,True)
  try:return runtime.parameters.apply(payload)
  except ParameterError as exc:raise HTTPException(exc.status,str(exc)) from None
  except OSError:raise HTTPException(503,'Parameter persistence failed') from None
 @app.websocket('/motion')
 async def motion(ws:WebSocket):
  try:runtime.auth(ws.headers)
  except HTTPException:await ws.close(code=1008);return
  if runtime.clients>=4:await ws.close(code=1008);return
  await ws.accept();runtime.clients+=1;seen=None
  async def watch():
   try:
    while (await ws.receive())['type']!='websocket.disconnect':pass
   except (WebSocketDisconnect,RuntimeError,OSError):pass
  watcher=asyncio.create_task(watch())
  try:
   while not watcher.done():
    with runtime.lock:p=runtime.latest
    if p and p[:2]!=seen and 0<=time.time()-p[2]<2:
     await asyncio.wait_for(ws.send_bytes(p[3]),.75);seen=p[:2];runtime.motion_sent+=1
    await asyncio.wait([watcher],timeout=1/120)
  except (WebSocketDisconnect,RuntimeError,OSError,asyncio.TimeoutError):pass
  finally:
   watcher.cancel();await asyncio.gather(watcher,return_exceptions=True);runtime.clients-=1
   with contextlib.suppress(Exception):await ws.close()
 return app

def main():
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=18891);p.add_argument('--cert');p.add_argument('--key');p.add_argument('--no-compile',action='store_true');p.add_argument('--no-cuda-graphs',action='store_true');a=p.parse_args()
 if a.host not in ('127.0.0.1','::1') and not (a.cert and a.key):p.error('Non-loopback binding requires --cert and --key')
 path=Path(a.config).resolve();config=json.loads(path.read_text())
 if a.no_compile:config['fast_sam_compile_crop']=False;config['torch_compile']=False;config['flow_cuda_graphs']=False;config['sam_fused_crop']=False
 if a.no_cuda_graphs:config['flow_cuda_graphs']=False
 import uvicorn
 uvicorn.run(create_app(config,path.parent),host=a.host,port=a.port,ssl_certfile=a.cert,ssl_keyfile=a.key,timeout_graceful_shutdown=10)
if __name__=='__main__':main()
