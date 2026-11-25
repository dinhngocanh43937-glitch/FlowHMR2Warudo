"""Local video preparation and camera enumeration. Never sends media to a server."""
import hashlib,json,os,re,shutil,subprocess,time
from pathlib import Path
FLAGS=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
class PreparationCancelled(Exception):pass

def tool(name):
 p=str(Path(__file__).resolve().parents[1]/'tools/bin'/(name+'.exe'))
 if not Path(p).is_file():p=shutil.which(name)
 if not p:raise RuntimeError('未找到 '+name+'；请先安装 FFmpeg 并加入 PATH。')
 return p

def probe(path):
 r=subprocess.run([tool('ffprobe'),'-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,timeout=30,creationflags=FLAGS)
 if r.returncode:raise RuntimeError('读取视频信息失败；请确认文件完整。')
 d=json.loads(r.stdout);v=next((s for s in d.get('streams',[]) if s.get('codec_type')=='video'),None)
 if not v:raise ValueError('文件没有可用的视频轨道。')
 return d,v

def target_size(width,height):
 if height>width:return 486,864
 if width>height:return 864,486
 return 486,486

def prepare_video(source,cache_dir,stop,on_progress=None):
 source=Path(source).resolve();cache=Path(cache_dir).resolve();cache.mkdir(parents=True,exist_ok=True)
 if stop.is_set():raise PreparationCancelled()
 d,v=probe(source);sw,sh=v['width'],v['height']
 rotation=next((float(x.get('rotation',0)) for x in v.get('side_data_list',[]) if 'rotation' in x),float(v.get('tags',{}).get('rotate',0) or 0))
 if round(rotation)%180:sw,sh=sh,sw
 w,h=target_size(sw,sh);duration=float(d.get('format',{}).get('duration',0) or 0)
 n,den=v.get('avg_frame_rate','0/1').split('/');fps=float(n)/max(1,float(den))
 if (v['width'],v['height'])==(w,h) and v.get('codec_name')=='h264' and abs(fps-30)<.01 and v.get('pix_fmt')=='yuv420p':
  return source,dict(width=w,height=h,fps=30,codec='h264',reused=True,already_compatible=True)
 signature=f'{source}|{source.stat().st_size}|{source.stat().st_mtime_ns}|{w}x{h}|30|h264-crf19-v1'
 key=hashlib.sha256(signature.encode()).hexdigest()[:24];out=cache/(key+'.mp4')
 info=dict(width=w,height=h,fps=30,codec='h264',crf=19,reused=out.exists(),already_compatible=False)
 if out.exists():return out,info
 if shutil.disk_usage(cache).free<256*1024*1024:raise RuntimeError('预处理缓存磁盘空间不足，至少预留256MiB。')
 part=cache/(key+'.part.mp4');progress=cache/(key+'.progress');error=cache/(key+'.error.log')
 vf=f'scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30'
 cmd=[tool('ffmpeg'),'-nostdin','-hide_banner','-loglevel','error','-y','-i',str(source),'-map','0:v:0','-map','0:a?','-vf',vf,'-c:v','libx264','-preset','fast','-crf','19','-threads','4','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart','-progress','pipe:1',str(part)]
 with progress.open('wb') as pf,error.open('wb') as ef:
  proc=subprocess.Popen(cmd,stdout=pf,stderr=ef,creationflags=FLAGS)
  try:
   while proc.poll() is None:
    if stop.wait(.25):raise PreparationCancelled()
    if on_progress:
     text=progress.read_text(encoding='utf-8',errors='replace')[-4096:]
     values=re.findall(r'out_time_us=(\d+)',text)
     percent=min(99.,float(values[-1])/1e6/max(duration,.001)*100) if values and duration else 0.
     on_progress(round(percent,1))
   if proc.returncode:raise RuntimeError('视频预处理失败；请检查源文件、格式和可用磁盘空间。')
   _,verified=probe(part)
   if (verified['width'],verified['height'])!=(w,h) or verified.get('codec_name')!='h264':raise RuntimeError('预处理输出校验失败。')
   if stop.is_set():raise PreparationCancelled()
   part.replace(out)
   if on_progress:on_progress(100.)
  finally:
   if proc.poll() is None:
    proc.terminate()
    try:proc.wait(timeout=5)
    except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
   if part.exists():part.unlink()
 return out,info

def list_cameras():
 if os.name!='nt':return {'devices':[],'error':'当前设备名称枚举适配 Windows DirectShow。'}
 r=subprocess.run([tool('ffmpeg'),'-hide_banner','-list_devices','true','-f','dshow','-i','dummy'],capture_output=True,timeout=15,creationflags=FLAGS)
 text=r.stderr.decode('utf-8',errors='replace')
 names=re.findall(r'"([^"\r\n]+)" \(video\)',text)
 devices=[dict(index=i,name=name) for i,name in enumerate(names)]
 return {'devices':devices,'error':'' if devices else '未找到摄像头；请确认设备连接后刷新。','note':'列出DirectShow设备顺序；DroidCam保留MSMF兼容回退。'}
