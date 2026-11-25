"""Authenticated JPEG/H264 input; process-local CameraSource adapter, bounded latest queue."""
import asyncio,io,json,math,queue,secrets,struct,threading,time,uuid
import cv2,numpy as np
from PIL import Image
from pathlib import Path
from fastapi import WebSocket
from h264_codec import H264Decoder
from local_frames import unpack_bgr,MAX_PAYLOAD
from frame_rate_adapter import ModelClock,model_index
from persona_flowhmr.sources import SampledFrame
FRAME=struct.Struct('!4s16sQddI')
def install(app,engine_module,engine,operation,token_path,on_session,*,allow_raw=False):
 token=Path(token_path).read_text().strip();frames=queue.Queue(maxsize=2);ready=threading.Event();closed=threading.Event();closed.set()
 stats={'active':False,'accepted':0,'dropped':0,'last_frame_id':None,'source_session':None,'last_source_media_s':None}
 class NetworkSource:
  def __init__(self,camera_index=0,**kw):self.camera_index=camera_index;self.model_clock=ModelClock();ready.set()
  def read_next(self):
   while not closed.is_set() and not engine._stop_event.is_set():
    if self.model_clock.pending:return self.model_clock.pending.popleft()
    try:
     self.model_clock.push(frames.get(timeout=.2),engine.config.playout_fps)
     stats['model_repeated_frames']=self.model_clock.repeated
     return self.model_clock.pending.popleft()
    except queue.Empty:pass
   return None
  def close(self):pass
  def switch_device(self,index,**kw):self.camera_index=index
 engine_module.CameraSource=NetworkSource
 def begin(session):
  with operation:
   engine.stop();closed.clear();ready.clear()
   while not frames.empty():frames.get_nowait()
   engine.config.source_mode='camera';engine.config.camera_index=0
   stats.update(active=True,accepted=0,dropped=0,last_frame_id=None,source_session=session)
   on_session(session);engine.start(realtime_source=True)
 def end():
  closed.set()
  try:
   with operation:engine.stop()
  finally:stats['active']=False
 @app.websocket('/input')
 async def input_video(ws:WebSocket):
  if not secrets.compare_digest(ws.headers.get('authorization',''),'Bearer '+token) or stats['active']:
   await ws.close(code=1008);return
  stats['active']=True;await ws.accept()
  try:
   hello=await asyncio.wait_for(ws.receive_json(),10);session=uuid.UUID(hello['session']).hex
   input_fps=hello.get('input_fps',30)
   if type(input_fps) is not int or input_fps not in (20,25,30) or input_fps!=engine.config.playout_fps:raise ValueError('input FPS differs from saved target FPS')
   stats['input_fps']=input_fps;stats['model_fps']=30;stats['model_repeated_frames']=0
   codec=hello.get('codec','jpeg');acks=bool(hello.get('ack',False))
   if codec not in ('jpeg','h264','raw_bgr'):raise ValueError('input codec')
   if codec=='raw_bgr' and (not allow_raw or ws.client is None or ws.client.host not in ('127.0.0.1','::1')):raise ValueError('Raw frames require local deployment and loopback peer')
   if codec in ('h264','raw_bgr') and not acks:raise ValueError('H264 requires bounded ACK protocol')
   decoder=H264Decoder() if codec=='h264' else None
   bitrate=int(hello.get('bitrate_kbps',0))
   if codec=='h264' and not 300<=bitrate<=5000:raise ValueError('bitrate')
   await asyncio.to_thread(begin,session)
   stats.update(codec=codec,bitrate_kbps=bitrate,bytes_received=0,decode_ms=0.0,decoded_frames=0,keyframes=0)
   warmup_disconnect=asyncio.create_task(ws.receive())
   try:
    for _ in range(9000 if engine.config.torch_compile else 1500):
     if warmup_disconnect.done():raise ConnectionError('Input closed during model warmup')
     if ready.is_set():break
     if engine.telemetry.error:raise RuntimeError(engine.telemetry.error)
     await asyncio.sleep(.2)
    else:raise TimeoutError('warmup timeout')
   finally:
    warmup_disconnect.cancel();await asyncio.gather(warmup_disconnect,return_exceptions=True)
   await ws.send_json({'state':'ready','model_fps':30,'session':session,'codec':codec,'ack':acks,'max_inflight':8})
   last=-1
   while True:
    data=await asyncio.wait_for(ws.receive_bytes(),10)
    if not FRAME.size<len(data)<=FRAME.size+(MAX_PAYLOAD if codec=='raw_bgr' else 3*1024*1024):raise ValueError('frame size')
    magic,s,seq,media,captured,flags=FRAME.unpack_from(data)
    if magic!=(b'RGB0' if codec=='raw_bgr' else b'H264' if codec=='h264' else b'FRM1') or uuid.UUID(bytes=s).hex!=session or seq<=last or not all(map(math.isfinite,[media,captured])):raise ValueError('frame metadata')
    payload=data[FRAME.size:];decode_start=time.perf_counter()
    if codec=='raw_bgr':
     rgb=unpack_bgr(payload)
    elif codec=='h264':
     if last<0 and not flags&2:raise ValueError('H264 must begin with IDR')
     rgb=await asyncio.to_thread(decoder.decode,payload,int(seq))
    else:
     with Image.open(io.BytesIO(payload)) as im:
      w,h=im.size
      if im.format!='JPEG' or not 16<=w<=1920 or not 16<=h<=1920:raise ValueError('image dimensions')
     rgb=await asyncio.to_thread(lambda:cv2.cvtColor(cv2.imdecode(np.frombuffer(payload,np.uint8),cv2.IMREAD_COLOR),cv2.COLOR_BGR2RGB))
    decode_ms=round((time.perf_counter()-decode_start)*1000,3)
    index=model_index(seq,input_fps)
    frame=SampledFrame(index,index/30.,time.perf_counter(),rgb,bool(flags&1))
    if frames.full():frames.get_nowait();stats['dropped']+=1
    frames.put_nowait(frame);last=seq;stats.update(accepted=stats['accepted']+1,last_frame_id=seq,last_source_media_s=media,last_client_capture_s=captured,bytes_received=stats['bytes_received']+len(data),decode_ms=decode_ms,decoded_frames=stats['decoded_frames']+1,keyframes=stats['keyframes']+int(codec=='h264' and bool(flags&2)))
    if acks:await ws.send_json({'ack':int(seq),'decode_ms':decode_ms})
  except Exception as e:
   try:await ws.close(code=1011,reason=type(e).__name__)
   except Exception:pass
  finally:
   await asyncio.shield(asyncio.to_thread(end))
 return stats
