"""Selectable JPEG/H264 video ingress; low-latency H264 is the default."""
import argparse,contextlib,json,threading,time,uuid,struct,os,math
from collections import deque
from pathlib import Path
import cv2
from websockets.sync.client import connect
from transport import tls_options
from h264_codec import H264Encoder
from local_frames import pack_bgr
FRAME=struct.Struct('!4s16sQddI');clock=time.perf_counter

def run(cfg,source,seconds=None,stop_event=None,on_stats=None,on_preview=None,on_connection=None):
 if cfg.get('codec','h264')=='jpeg':
  from capture_jpeg import run as jpeg_run
  return jpeg_run(cfg,source,seconds,stop_event,on_stats,on_preview,on_connection)
 codec=cfg.get('codec','h264')
 if codec not in ('h264','raw_bgr'):raise ValueError('Unknown input codec')
 target_fps=int(cfg.get('target_fps',30))
 if target_fps not in (20,25,30):raise ValueError('Unsupported target FPS')
 stop=stop_event or threading.Event();session=uuid.uuid4();camera=str(source).isdigit();count=sent_bytes=keyframes=raw_count=0;encoder=None;ws_ref=None
 lock=threading.Lock();credit=threading.Condition();pending={};ack_stop=threading.Event();ack_error=[];ack_rtt=None;server_decode_ms=None;ack_history=deque(maxlen=90);pending_limit=4;latest=[None]
 preview_done=False
 def report(**data):
  if on_stats:on_stats(data)
 report(state='connecting',codec=codec,bitrate_kbps=cfg.get('bitrate_kbps',1500),frames_sent=0,bytes_sent=0,error='')
 try:
  with connect(cfg['input_url'],**tls_options(cfg,'input_url'),compression=None,additional_headers={'Authorization':'Bearer '+cfg['input_token']},max_size=4096,max_queue=4,ping_interval=10,ping_timeout=20,open_timeout=15,close_timeout=1) as ws:
   ws_ref=ws
   if on_connection:on_connection(ws)
   ws.send(json.dumps({'session':session.hex,'source':'camera' if camera else 'video','input_fps':target_fps,'codec':codec,'ack':True,'protocol':2,'bitrate_kbps':int(cfg.get('bitrate_kbps',1500))}));report(state='warming_up')
   deadline=clock()+1800
   while not stop.is_set():
    try:
     ready=json.loads(ws.recv(timeout=.5))
     if ready.get('state')!='ready' or ready.get('codec')!=codec or not ready.get('ack'):raise RuntimeError('Server does not support H264/ACK v2')
     break
    except TimeoutError:
     if clock()>deadline:raise TimeoutError('Model warmup timeout')
   if stop.is_set():return 0
   def receive_acks():
    nonlocal ack_rtt,server_decode_ms,pending_limit
    try:
     while not ack_stop.is_set() and not stop.is_set():
      try:message=json.loads(ws.recv(timeout=.25))
      except TimeoutError:continue
      if 'ack' not in message:raise ValueError('Unexpected server reply')
      seq=int(message['ack'])
      with credit:
       timestamp=pending.pop(seq,None)
       if timestamp is not None:
        ack_rtt=(clock()-timestamp)*1000;ack_history.append(ack_rtt)
        ordered=sorted(ack_history);p95=ordered[max(0,math.ceil(len(ordered)*.95)-1)]
        pending_limit=min(8,max(4,math.ceil(p95*.03)+2))
       server_decode_ms=message.get('decode_ms');credit.notify_all()
    except Exception as exc:
     if not ack_stop.is_set() and not stop.is_set():ack_error.append(type(exc).__name__)
     with credit:credit.notify_all()
   ack_thread=threading.Thread(target=receive_acks,daemon=True);ack_thread.start()
   cap=cv2.VideoCapture(int(source) if camera else source,cv2.CAP_DSHOW if camera and os.name=='nt' else cv2.CAP_ANY)
   if camera and os.name=='nt' and not cap.isOpened():
    cap.release()
    cap=cv2.VideoCapture(int(source),cv2.CAP_MSMF)
   if not cap.isOpened():raise RuntimeError('Could not open input camera/video')
   if camera:
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,1280);cap.set(cv2.CAP_PROP_FRAME_HEIGHT,720);cap.set(cv2.CAP_PROP_FPS,target_fps);cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
   fps=cap.get(cv2.CAP_PROP_FPS) or 30;start=clock();reader_stop=threading.Event()
   def read():
    nonlocal raw_count
    video_index=loop=0
    while not stop.is_set() and not reader_stop.is_set():
     ok,bgr=cap.read()
     if not ok:
      if camera:stop.set();break
      cap.set(cv2.CAP_PROP_POS_FRAMES,0);video_index=0;loop+=1;continue
     if not camera:
      target=loop*(cap.get(cv2.CAP_PROP_FRAME_COUNT)/fps)+video_index/fps
      if stop.wait(max(0,start+target-clock())):break
     captured=clock();media=video_index/fps if not camera else captured-start
     with lock:raw_count+=1;latest[0]=(bgr,media,captured,loop)
     video_index+=1
   read_thread=threading.Thread(target=read,daemon=True);read_thread.start();last_slot=last_loop=-1;last_preview=0;report_time=start;previous_count=previous_bytes=previous_raw=0;last_report=start;max_inflight=8
   try:
    while not stop.is_set() and (seconds is None or clock()-start<seconds):
     if ack_error:raise ConnectionError('ACK receive: '+ack_error[0])
     with credit:
      if pending and clock()-min(pending.values())>2.0:raise TimeoutError('Input ACK exceeded 2 seconds; reconnect instead of old-frame backlog')
      if len(pending)>=min(max_inflight,pending_limit):credit.wait(.005);continue
     slot=int((clock()-start)*target_fps)
     if slot==last_slot:stop.wait(.001);continue
     with lock:item=latest[0];read_count=raw_count
     if item is None:stop.wait(.005);continue
     bgr,media,captured,loop=item;h,w=bgr.shape[:2];scale=min(1,int(cfg.get('max_edge',960))/max(h,w));width=max(16,int(w*scale)//2*2);height=max(16,int(h*scale)//2*2)
     image=cv2.resize(bgr,(width,height)) if (width,height)!=(w,h) else bgr
     encode_start=clock()
     reset=loop!=last_loop and last_loop>=0
     if codec=='raw_bgr':au=pack_bgr(image);is_key=True
     else:
      if encoder is None:encoder=H264Encoder(width,height,int(cfg.get('bitrate_kbps',1500)))
      au,is_key=encoder.encode(image,slot,force_key=reset)
     encode_ms=(clock()-encode_start)*1000
     packet=FRAME.pack(b'RGB0' if codec=='raw_bgr' else b'H264',session.bytes,slot,media,captured,int(reset)|(2 if is_key else 0))+au;send_start=clock()
     with credit:pending[slot]=send_start
     ws.send(packet);send_ms=(clock()-send_start)*1000;count+=1;sent_bytes+=len(packet);keyframes+=int(is_key);last_slot=slot;last_loop=loop;now=clock()
     if on_preview and not preview_done and getattr(on_preview,'needs_frame',True):
      last_preview=now;thumb=cv2.resize(image,(max(1,int(width*min(1,480/width))),max(1,int(height*min(1,480/width)))));ok,jpg=cv2.imencode('.jpg',thumb,[cv2.IMWRITE_JPEG_QUALITY,65])
      if ok:on_preview(jpg.tobytes());preview_done=True
     if now-last_report>=.5:
      dt=max(.001,now-report_time)
      with credit:inflight=len(pending)
      report(state='streaming',codec=codec,bitrate_kbps=int(cfg.get('bitrate_kbps',1500)),frames_sent=count,frames_read=read_count,bytes_sent=sent_bytes,upload_fps=round((count-previous_count)/dt,2),capture_fps=round((read_count-previous_raw)/dt,2),upload_mbps=round((sent_bytes-previous_bytes)*8/dt/1e6,3),encode_ms=round(encode_ms,2),send_ms=round(send_ms,2),source_time_s=round(media,2),width=width,height=height,frame_id=slot,keyframes=keyframes,inflight=inflight,inflight_limit=pending_limit,ack_rtt_ms=round(ack_rtt,2) if ack_rtt is not None else None,server_decode_ms=server_decode_ms)
      last_report=report_time=now;previous_count=count;previous_bytes=sent_bytes;previous_raw=read_count
     if count%150==0:print('H264 sent',count,'frames',round(sent_bytes*8/max(.001,now-start)/1e6,3),'Mbps',flush=True)
   finally:
    reader_stop.set();ack_stop.set();read_thread.join(timeout=2);cap.release();ack_thread.join(timeout=1)
    if encoder:encoder.finish()
 finally:
  report(state='stopped',codec=codec,frames_sent=count,bytes_sent=sent_bytes,upload_fps=0,capture_fps=0,upload_mbps=0)
 return count
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--config',default=str(Path(__file__).with_name('receiver.json')));p.add_argument('--source',default='0');p.add_argument('--seconds',type=float);p.add_argument('--codec',choices=['h264','jpeg']);a=p.parse_args();cfg=json.loads(Path(a.config).read_text(encoding='utf-8'))
 if a.codec:cfg['codec']=a.codec
 while True:
  try:print('Finished; frames:',run(cfg,a.source,a.seconds),flush=True);break
  except KeyboardInterrupt:break
  except Exception as exc:
   print('Capture reconnect:',type(exc).__name__,str(exc),flush=True)
   if a.seconds is not None:raise
   time.sleep(3)
