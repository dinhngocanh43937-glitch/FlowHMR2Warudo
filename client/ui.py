"""Loopback-only browser UI; remote credentials never enter the browser."""
import argparse,collections,contextlib,json,mimetypes,os,secrets,socket,tempfile,threading,time,urllib.error,urllib.request,webbrowser
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit
from capture import run as capture_run
from first_frame_preview import FirstFramePreview
from local_frames import use_local_raw
from media_tools import prepare_video,PreparationCancelled,list_cameras
from receiver import Receiver
from transport import tls_options,http_connection
ROOT=Path(__file__).resolve().parent
class SettingsError(Exception):
 def __init__(self,status,message):super().__init__(message);self.status=status
class App:
 def __init__(self,cfg):
  self.cfg=cfg;self.key=secrets.token_urlsafe(32);self.lock=threading.RLock();self.quit=threading.Event();self.capture_stop=threading.Event();self.capture_thread=None;self.capture_ws=None;self.capture={'state':'stopped','frames_sent':0,'bytes_sent':0};self.preview=b'';self.receiver=None;self.receiver_thread=None;self.remote={};self.remote_ok=False;self.remote_at=None;self.remote_error='';self.metrics_rtt_ms=None;self.events=collections.deque(maxlen=60);self.temp=tempfile.TemporaryDirectory(prefix='motion-ui-');self.uploads={};self.previous=(time.monotonic(),0,0,0);self.receiver_rates={};self.parameter_result=None;self.event('控制台已就绪；推理参数可在停止采集后修改。')
  self.monitor=threading.Thread(target=self.poll_server,daemon=True);self.monitor.start()
 def event(self,message):
  with self.lock:self.events.append({'at':time.strftime('%H:%M:%S'),'message':message})
 def poll_server(self):
  endpoint,opener=http_connection(self.cfg,'metrics')
  while not self.quit.is_set():
   start=time.monotonic()
   try:
    req=urllib.request.Request(endpoint,headers={'Authorization':'Bearer '+self.cfg['token']})
    with opener.open(req,timeout=4) as response:data=json.load(response)
    with self.lock:self.remote=data;self.remote_ok=bool(data.get('available'));self.remote_at=time.monotonic();self.metrics_rtt_ms=round((self.remote_at-start)*1000,1);self.remote_error=data.get('error','')
   except Exception as exc:
    with self.lock:self.remote_ok=False;self.remote_error=type(exc).__name__
   self.quit.wait(max(.1,float(self.cfg.get('monitor_interval_s',1))-(time.monotonic()-start)))
 def parameter_request(self,method,payload=None):
  endpoint,opener=http_connection(self.cfg,'settings')
  token=self.cfg['token'] if method=='GET' else self.cfg['input_token']
  headers={'Authorization':'Bearer '+token}
  if payload is not None:headers['Content-Type']='application/json'
  req=urllib.request.Request(endpoint,headers=headers,data=json.dumps(payload).encode() if payload is not None else None,method=method)
  try:
   with opener.open(req,timeout=8) as response:result=json.load(response)
  except urllib.error.HTTPError as exc:
   try:message=json.loads(exc.read()).get('detail','参数请求失败。')
   except Exception:message='参数接口尚未部署或请求被拒绝。'
   status=exc.code;exc.close();raise SettingsError(status if status in (400,403,409,422,503) else 503,str(message)) from None
  except Exception as exc:raise SettingsError(503,'参数连接异常：'+type(exc).__name__) from None
  if not isinstance(result.get('values'),dict) or type(result.get('revision')) is not int:raise SettingsError(503,'服务器参数回读格式错误。')
  with self.lock:self.parameter_result=result
  return result
 def apply_parameters(self,payload):
  if self.capture_thread and self.capture_thread.is_alive():raise SettingsError(409,'请先停止本机视频采集，再应用推理参数。')
  result=self.parameter_request('POST',payload);self.event('服务器参数已保存并回读，版本 '+str(result['revision'])+'；下次开始推理生效。');return result
 def set_capture(self,data):
  with self.lock:self.capture.update(data)
 def set_preview(self,data):
  with self.lock:
   if data and not self.preview:
    self.preview=data;self.capture['preview_ready']=True;self.capture['preview_frames']=1
 def set_connection(self,ws):
  with self.lock:self.capture_ws=ws
 def start_capture(self,params):
  with self.lock:
   if self.capture_thread and self.capture_thread.is_alive():raise ValueError('采集仍在运行或停止中，请稍候。')
   if self.remote_ok and (self.remote.get('running') or self.remote.get('network_input',{}).get('active')):raise SettingsError(409,'上一轮推理尚未停止，请等待输入通道释放后再开始。')
   kind=params.get('kind','camera');source=params.get('source','0')
   if kind=='camera':
    source=int(source)
    if not 0<=source<=16:raise ValueError('摄像头编号应为0–16。')
    name=params.get('camera_name')
    if name:
     if not isinstance(name,str):raise ValueError('摄像头名称错误。')
     devices=list_cameras().get('devices',[])
     selected=next((d for d in devices if d['name']==name),None)
     if selected is None:raise ValueError('摄像头已断开或列表已变化，请刷新后重新选择。')
     source=selected['index']
     if not 0<=source<=16:raise ValueError('摄像头编号超出当前支持范围。')
   elif kind=='video':
    source=self.uploads.get(str(source),str(source))
    if not Path(source).is_file():raise ValueError('请先选择视频，或输入有效本机绝对路径。')
   else:raise ValueError('输入类型错误。')
   codec=params.get('codec','h264');bitrate=int(params.get('bitrate_kbps',1500))
   if codec not in ('h264','jpeg') or not 300<=bitrate<=5000:raise ValueError('编码/码率设置错误。')
   max_edge=int(params.get('max_edge',960));quality=int(params.get('jpeg_quality',85))
   if max_edge not in (480,640,720,960,1280):raise ValueError('分辨率设置错误。')
   if not 40<=quality<=95:raise ValueError('JPEG质量应为40–95。')
   self.cfg.update(max_edge=max_edge,jpeg_quality=quality,codec=codec,bitrate_kbps=bitrate)
   self.capture_stop=threading.Event();self.capture_ws=None;self.preview=b'';self.capture={'state':'connecting','frames_sent':0,'bytes_sent':0,'source_name':str(source) if kind=='camera' else Path(source).name,'kind':kind}
   self.capture.update(preview_session=secrets.token_hex(12),preview_ready=False,preview_frames=0)
   fps_values=(self.parameter_result or self.remote.get('parameters',{})).get('values',{})
   self.cfg['target_fps']=int(fps_values.get('target_fps',30));self.cfg['output_fps']=self.cfg['target_fps']
   cfg=dict(self.cfg)
   if use_local_raw(cfg):cfg['codec']='raw_bgr'
   preview_once=FirstFramePreview(self.set_preview)
   def work():
    try:
     stream_source=source
     if kind=='video':
      self.set_capture({'state':'preprocessing','preprocess_percent':0,'error':''})
      self.event('视频预处理：横屏864×486 / 竖屏486×864 · 30FPS · H.264；完成后自动推流。')
      try:
       prepared,info=prepare_video(source,Path(self.temp.name)/'processed',self.capture_stop,lambda p:self.set_capture({'preprocess_percent':p}))
      except PreparationCancelled:return
      except Exception as exc:
       self.set_capture({'error':str(exc),'preprocess_failed':True});self.event('视频预处理失败：'+str(exc));return
      stream_source=str(prepared);cfg['max_edge']=864
      self.set_capture({'prepared_video':info,'preprocess_percent':100})
      self.event('视频已就绪：%d×%d / 30FPS / H.264%s' % (info['width'],info['height'],'（复用兼容文件/缓存）' if info['reused'] else ''))
     while not self.capture_stop.is_set():
      if self.remote_ok and (self.remote.get('running') or self.remote.get('network_input',{}).get('active')):
       self.set_capture({'state':'waiting_previous','error':''});self.capture_stop.wait(.5);continue
      try:capture_run(cfg,stream_source,stop_event=self.capture_stop,on_stats=self.set_capture,on_preview=preview_once,on_connection=self.set_connection);break
      except Exception as exc:
       if self.capture_stop.is_set():break
       self.set_capture({'state':'reconnecting','error':type(exc).__name__});self.event('采集重连：'+type(exc).__name__)
       self.capture_stop.wait(3)
    finally:self.set_capture({'state':'stopped','upload_fps':0,'upload_mbps':0});self.capture_ws=None;self.event('采集已停止。')
   self.capture_thread=threading.Thread(target=work,daemon=True);self.capture_thread.start();self.event('开始采集：'+('摄像头 '+str(source) if kind=='camera' else Path(source).name))
 def stop_capture(self):
  self.capture_stop.set();self.set_capture({'state':'stopping'})
  ws=self.capture_ws
  if ws:
   threading.Thread(target=lambda:self.close_ws(ws),daemon=True).start()
 def close_ws(self,ws):
  with contextlib.suppress(Exception):ws.close()
 def start_receiver(self,port):
  port=int(port)
  if not 1024<=port<=65535:raise ValueError('UDP端口应为1024–65535。')
  with self.lock:
   if self.receiver_thread and self.receiver_thread.is_alive():raise ValueError('动作接收器已运行。')
   self.cfg['udp_port']=port;cfg=dict(self.cfg,udp_host='127.0.0.1',udp_port=port);self.receiver=Receiver(cfg);self.previous=(time.monotonic(),0,0,0)
   def work():
    try:self.receiver.run()
    except Exception as exc:self.event('动作接收异常：'+type(exc).__name__)
   self.receiver_thread=threading.Thread(target=work,daemon=True);self.receiver_thread.start();self.event('动作转发目标：127.0.0.1:'+str(port))
 def stop_receiver(self):
  if self.receiver:
   self.receiver.stop.set()
   if self.receiver.ws:threading.Thread(target=lambda:self.close_ws(self.receiver.ws),daemon=True).start()
 def snapshot(self):
  with self.lock:
   now=time.monotonic();r=self.receiver
   if r:
    t,rx,tx,byte=self.previous;dt=now-t
    if dt>=.5:
     self.receiver_rates={'motion_fps':round((r.rx-rx)/dt,2),'udp_fps':round((r.tx-tx)/dt,2),'down_mbps':round((r.byte_rx-byte)*8/dt/1e6,3)};self.previous=(now,r.rx,r.tx,r.byte_rx)
   received={'running':bool(self.receiver_thread and self.receiver_thread.is_alive()),'connected':bool(r and r.connected),'rx':r.rx if r else 0,'tx':r.tx if r else 0,'last_pose_age_s':round(now-r.last_received,2) if r and r.last_received else None,'error':r.error if r else '',**self.receiver_rates}
   remote=dict(self.remote)
   if self.parameter_result and self.parameter_result['revision']>remote.get('parameters',{}).get('revision',-1):remote['parameters']=self.parameter_result
   return {'client':dict(self.capture,thread_active=bool(self.capture_thread and self.capture_thread.is_alive())),'receiver':received,'server':remote,'server_online':self.remote_ok,'metrics_age_s':round(now-self.remote_at,2) if self.remote_at else None,'metrics_error':self.remote_error,'metrics_rtt_ms':self.metrics_rtt_ms,'config':{k:self.cfg.get(k) for k in ('max_edge','jpeg_quality','udp_port','codec','bitrate_kbps')},'endpoint':urlsplit(self.cfg['url']).netloc,'events':list(self.events)}
 def close(self):
  self.quit.set();self.stop_capture();self.stop_receiver()
  for thread in (self.capture_thread,self.receiver_thread,self.monitor):
   if thread:thread.join(timeout=6)
  self.temp.cleanup()
class Handler(BaseHTTPRequestHandler):
 server_version='MotionLocalUI/6'
 def log_message(self,*args):pass
 @property
 def app(self):return self.server.app
 def reply(self,code,data,kind='application/json'):
  if isinstance(data,dict):data=json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
  if isinstance(data,str):data=data.encode()
  self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'");self.end_headers()
  with contextlib.suppress(BrokenPipeError,ConnectionResetError):self.wfile.write(data)
 def allowed(self,api=False):
  host=self.headers.get('Host','');expected='127.0.0.1:'+str(self.server.server_port)
  if host!=expected:self.reply(403,{'error':'Host rejected'});return False
  origin=self.headers.get('Origin')
  if origin and origin!='http://'+expected:self.reply(403,{'error':'Origin rejected'});return False
  if api and not secrets.compare_digest(self.headers.get('X-UI-Key',''),self.app.key):self.reply(403,{'error':'UI session required'});return False
  return True
 def do_GET(self):
  if not self.allowed(self.path.startswith('/api/')):return
  if self.path=='/':return self.reply(200,(ROOT/'ui.html').read_text(encoding='utf-8').replace('__UI_KEY__',self.app.key),'text/html; charset=utf-8')
  if self.path in ('/ui.js','/ui.css','/frozen_preview.js'):
   p=ROOT/self.path[1:];return self.reply(200,p.read_bytes(),'text/javascript; charset=utf-8' if p.suffix=='.js' else 'text/css; charset=utf-8')
  if self.path=='/api/cameras':
   try:return self.reply(200,list_cameras())
   except Exception:return self.reply(503,{'error':'摄像头枚举失败；请检查FFmpeg与设备连接。'})
  if self.path=='/api/diagnostics':
   from portable_diagnostics import export
   return self.reply(200,export(self.app.snapshot()),'application/zip')
  if self.path=='/api/status':return self.reply(200,self.app.snapshot())
  if self.path=='/api/preview':
   with self.app.lock:
    requested=self.headers.get('X-Preview-Session');current=self.app.capture.get('preview_session')
    if requested and requested!=current:return self.reply(409,{'error':'Preview session changed'})
    data=self.app.preview
   return self.reply(200 if data else 204,data,'image/jpeg')
  self.reply(404,{'error':'Not found'})
 def do_POST(self):
  if not self.allowed(True):return
  try:
   size=int(self.headers.get('Content-Length','-1'))
   if self.path=='/api/upload':
    if not 0<size<=2*1024**3:raise ValueError('视频应小于2 GiB。')
    suffix=self.headers.get('X-File-Suffix','.mp4').lower()
    if suffix not in ('.mp4','.mov','.avi','.mkv','.webm','.m4v'):raise ValueError('不支持此视频扩展名。')
    key=secrets.token_hex(12);target=Path(self.app.temp.name)/(key+suffix);remaining=size
    try:
     with target.open('xb') as out:
      while remaining:
       chunk=self.rfile.read(min(1024**2,remaining))
       if not chunk:raise ValueError('视频导入中断。')
       out.write(chunk);remaining-=len(chunk)
    except Exception:
     target.unlink(missing_ok=True);raise
    self.app.uploads[key]=str(target);return self.reply(200,{'source':key,'bytes':size})
   if not 0<=size<=16384:raise ValueError('请求大小错误。')
   data=json.loads(self.rfile.read(size) or b'{}')
   if self.path=='/api/settings/read':return self.reply(200,self.app.parameter_request('GET'))
   if self.path=='/api/settings/apply':return self.reply(200,self.app.apply_parameters(data))
   if self.path=='/api/capture/start':
    fps_values=(self.app.parameter_result or self.app.remote.get('parameters',{})).get('values',{})
    self.app.cfg['output_fps']=int(fps_values.get('target_fps',30))
    if self.app.receiver:self.app.receiver.cfg['output_fps']=self.app.cfg['output_fps']
    if not (self.app.receiver_thread and self.app.receiver_thread.is_alive()):self.app.start_receiver(data.get('port',39539))
    try:self.app.start_capture(data)
    except Exception:
     self.app.stop_receiver();raise
   elif self.path=='/api/capture/stop':self.app.stop_capture();self.app.stop_receiver()
   elif self.path=='/api/receiver/start':self.app.start_receiver(data.get('port',39539))
   elif self.path=='/api/receiver/stop':self.app.stop_receiver()
   else:return self.reply(404,{'error':'Not found'})
   self.reply(200,{'ok':True})
  except SettingsError as exc:self.reply(exc.status,{'error':str(exc)})
  except (ValueError,TypeError,json.JSONDecodeError):self.reply(400,{'error':'操作参数有误；检查输入、端口或任务是否已在运行。'})
  except Exception as exc:self.reply(500,{'error':type(exc).__name__})
 def setup(self):super().setup();self.connection.settimeout(120)
def main():
 p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=18890);p.add_argument('--no-browser',action='store_true');args=p.parse_args()
 config_path=ROOT/'receiver.json'
 if not config_path.exists():p.error('Missing receiver.json. Remote: run configure-client.py; local: use the root start-local.cmd launcher. See the repository README.')
 cfg=json.loads(config_path.read_text(encoding='utf-8'));app=App(cfg)
 server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);server.daemon_threads=True;server.app=app
 url='http://127.0.0.1:'+str(args.port);print('Motion UI: '+url,flush=True)
 if not args.no_browser:webbrowser.open(url)
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:server.server_close();app.close()
if __name__=='__main__':main()
