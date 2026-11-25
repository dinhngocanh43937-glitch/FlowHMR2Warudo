"""Capture-only client, shared by CLI and local UI. GPU work stays on server."""
import argparse,json,threading,time,uuid,struct,os
from pathlib import Path
import cv2
from websockets.sync.client import connect
from transport import tls_options
FRAME=struct.Struct('!4s16sQddI')
def run(cfg,source,seconds=None,stop_event=None,on_stats=None,on_preview=None,on_connection=None):
 target_fps=int(cfg.get('target_fps',30))
 if target_fps not in (20,25,30):raise ValueError('Unsupported target FPS')
 stop=stop_event or threading.Event();count=0;session=uuid.uuid4();is_camera=str(source).isdigit();src=int(source) if is_camera else source
 preview_done=False
 def report(**data):
  if on_stats:on_stats(data)
 report(state='connecting',frames_sent=0,bytes_sent=0,error='')
 print('Connecting input; waiting for server models/compile warmup...',flush=True)
 with connect(cfg['input_url'],**tls_options(cfg,'input_url'),compression=None,additional_headers={'Authorization':'Bearer '+cfg['input_token']},max_size=4096,max_queue=1,ping_interval=10,ping_timeout=20,open_timeout=15) as ws:
  if on_connection:on_connection(ws)
  ws.send(json.dumps({'session':session.hex,'source':'camera' if is_camera else 'video','input_fps':target_fps}));report(state='warming_up')
  deadline=time.monotonic()+360
  while not stop.is_set():
   try:state=json.loads(ws.recv(timeout=.5));assert state['state']=='ready';break
   except TimeoutError:
    if time.monotonic()>deadline:raise TimeoutError('Model warmup timeout')
  if stop.is_set():return 0
  cap=cv2.VideoCapture(src,cv2.CAP_DSHOW if is_camera and os.name=='nt' else cv2.CAP_ANY)
  if is_camera and os.name=='nt' and not cap.isOpened():
   cap.release()
   cap=cv2.VideoCapture(int(source),cv2.CAP_MSMF)
  if not cap.isOpened():raise RuntimeError('Could not open input camera/video')
  if is_camera:
   cap.set(cv2.CAP_PROP_FRAME_WIDTH,1280);cap.set(cv2.CAP_PROP_FRAME_HEIGHT,720);cap.set(cv2.CAP_PROP_FPS,target_fps);cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
  fps=cap.get(cv2.CAP_PROP_FPS) or 30;lock=threading.Lock();latest=[None];start=time.monotonic();sent_bytes=0;last_preview=0;last_report=start;last_read_count=0;read_count=0;report_time=start;report_count=0;report_bytes=0
  def read():
   nonlocal read_count
   video_index=0;loop=0
   while not stop.is_set():
    ok,bgr=cap.read()
    if not ok:
     if is_camera:stop.set();break
     cap.set(cv2.CAP_PROP_POS_FRAMES,0);video_index=0;loop+=1;continue
    if not is_camera:
     target=loop*(cap.get(cv2.CAP_PROP_FRAME_COUNT)/fps)+video_index/fps
     if stop.wait(max(0,start+target-time.monotonic())):break
    captured=time.monotonic();media=video_index/fps if not is_camera else captured-start
    with lock:latest[0]=(bgr,media,captured,loop);read_count+=1
    video_index+=1
  thread=threading.Thread(target=read,daemon=True);thread.start();last_slot=-1;last_loop=-1
  try:
   while not stop.is_set() and (seconds is None or time.monotonic()-start<seconds):
    slot=int((time.monotonic()-start)*target_fps)
    if slot==last_slot:stop.wait(.001);continue
    with lock:item=latest[0];captured_count=read_count
    if item is None:stop.wait(.005);continue
    image,media,captured,loop=item;h,w=image.shape[:2];scale=min(1,cfg.get('max_edge',960)/max(h,w))
    if scale<1:image=cv2.resize(image,(int(w*scale),int(h*scale)))
    encode_start=time.monotonic();ok,jpeg=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,cfg.get('jpeg_quality',85)]);encode_ms=(time.monotonic()-encode_start)*1000
    if not ok:continue
    if last_slot<0:slot=0;start=time.monotonic();report_time=last_report=start
    payload=FRAME.pack(b'FRM1',session.bytes,slot,media,captured,int(loop!=last_loop and last_loop>=0))+jpeg.tobytes();send_start=time.monotonic();ws.send(payload);send_ms=(time.monotonic()-send_start)*1000
    last_slot=slot;last_loop=loop;count+=1;sent_bytes+=len(payload);now=time.monotonic()
    if on_preview and not preview_done and getattr(on_preview,'needs_frame',True):
     last_preview=now;thumb=cv2.resize(image,(max(1,int(image.shape[1]*min(1,480/image.shape[1]))),max(1,int(image.shape[0]*min(1,480/image.shape[1])))))
     good,preview=cv2.imencode('.jpg',thumb,[cv2.IMWRITE_JPEG_QUALITY,65])
     if good:on_preview(preview.tobytes());preview_done=True
    if now-last_report>=.5:
     dt=max(.001,now-report_time);report(state='streaming',frames_sent=count,frames_read=captured_count,bytes_sent=sent_bytes,upload_fps=round((count-report_count)/dt,2),capture_fps=round((captured_count-last_read_count)/dt,2),upload_mbps=round((sent_bytes-report_bytes)*8/dt/1e6,3),encode_ms=round(encode_ms,2),send_ms=round(send_ms,2),source_time_s=round(media,2),width=image.shape[1],height=image.shape[0],frame_id=slot)
     last_report=report_time=now;report_count=count;report_bytes=sent_bytes;last_read_count=captured_count
    if count%150==0:print('Sent',count,'frames; latest model slot',slot,flush=True)
  finally:
   stop.set();thread.join(timeout=2);cap.release();report(state='stopped',frames_sent=count,bytes_sent=sent_bytes,upload_fps=0,upload_mbps=0)
 return count
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--config',default=str(Path(__file__).with_name('receiver.json')));p.add_argument('--source',default='0');p.add_argument('--seconds',type=float);a=p.parse_args();cfg=json.loads(Path(a.config).read_text(encoding='utf-8'));tls_options(cfg,'input_url')
 while True:
  try:print('Finished; frames:',run(cfg,a.source,a.seconds),flush=True);break
  except KeyboardInterrupt:break
  except Exception as e:
   print('Input reconnect:',type(e).__name__,str(e),flush=True)
   if a.seconds is not None:raise
   time.sleep(3)
