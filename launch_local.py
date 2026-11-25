"""Start only this copy's loopback backend and enhanced UI; no SSH/cloud traffic."""
import argparse,hashlib,json,os,pathlib,secrets,socket,subprocess,sys,time,urllib.request,contextlib
ROOT=pathlib.Path(__file__).resolve().parent

def free(port):
 with socket.socket() as s:
  try:s.bind(('127.0.0.1',port))
  except OSError:raise RuntimeError(f'Port {port} is occupied. Stop the other local copy first.') from None

def prepare(root,backend_port):
 root=pathlib.Path(root);state=root/'state';state.mkdir(exist_ok=True);path=state/'backend.json'
 if not path.exists():
  config=dict(read_token=secrets.token_urlsafe(36),input_token=secrets.token_urlsafe(36),deployment_mode='local',torch_compile=True,flow_cuda_graphs=True,sam_fused_crop=True,sam_no_mask_prompt=True,parameters=dict(sam_stride=4,body_decoder_layers=4,ode_steps=2,yolo_size=416,hand_mode='fast',hand_decoder_layers=1))
  path.write_text(json.dumps(config,indent=2));path.chmod(0o600)
 config=json.loads(path.read_text());assert config['deployment_mode']=='local'
 from compile_profile import migrate
 config=migrate(path,config)
 added=False
 for key in ('fast_sam_enabled','fast_sam_compile_crop','fast_sam_zero_mask_contract','fast_sam_feedback','fast_sam_prompt_cache'):
  if key not in config:config[key]=True;added=True
 if added:path.write_text(json.dumps(config,indent=2))
 cfg=dict(url=f'ws://127.0.0.1:{backend_port}/motion',input_url=f'ws://127.0.0.1:{backend_port}/input',token=config['read_token'],input_token=config['input_token'],deployment_mode='local',udp_host='127.0.0.1',udp_port=39539,output_fps=30,stale_timeout_s=2,max_edge=960,jpeg_quality=85,codec='h264',bitrate_kbps=1500)
 dest=root/'client/receiver.json';dest.write_text(json.dumps(cfg,indent=2));dest.chmod(0o600)
 return path

def main():
 p=argparse.ArgumentParser();p.add_argument('--ui-port',type=int,default=18990);p.add_argument('--backend-port',type=int,default=18991);p.add_argument('--no-compile',action='store_true');p.add_argument('--no-cuda-graphs',action='store_true');p.add_argument('--no-browser',action='store_true');a=p.parse_args()
 free(a.ui_port);free(a.backend_port)
 root=ROOT;engine=root/'engine';python=pathlib.Path(sys.executable)
 if not python.exists():raise RuntimeError('Python environment missing; activate your environment first.')
 config=prepare(root,a.backend_port);logs=root/'logs';logs.mkdir(exist_ok=True)
 env=dict(os.environ,PERSONA_FLOWHMR_MODELS=str(engine/'models'),OMP_NUM_THREADS='8',PYTHONUNBUFFERED='1',PYTHONFAULTHANDLER='1')
 cmd=[str(python),'-I',str(root/'portable_entry.py'),'server/backend.py','--config',str(config),'--port',str(a.backend_port)]
 if a.no_compile:cmd.append('--no-compile')
 if a.no_cuda_graphs:cmd.append('--no-cuda-graphs')
 processes=[]
 try:
  with (logs/'backend.log').open('a',encoding='utf-8') as log:
   backend=subprocess.Popen(cmd,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT);processes.append(backend)
   opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
   for _ in range(600):
    if backend.poll() is not None:raise RuntimeError('Backend exited. See logs/backend.log and run check-local.cmd.')
    try:
     with opener.open(f'http://127.0.0.1:{a.backend_port}/health',timeout=1) as r:
      health=json.load(r);assert health['service']=='motion-inference';break
    except (OSError,ValueError):time.sleep(.5)
   else:raise TimeoutError('Backend startup timed out; see logs/backend.log')
   cmd=[str(python),'-I',str(root/'portable_entry.py'),'client/ui.py','--port',str(a.ui_port)]
   if a.no_browser:cmd.append('--no-browser')
   ui_log=(logs/'ui.log').open('a',encoding='utf-8');ui=subprocess.Popen(cmd,cwd=root/'client',env=env,stdout=ui_log,stderr=subprocess.STDOUT);processes.append(ui)
   print(f'Local UI: http://127.0.0.1:{a.ui_port}; Warudo VMC: 127.0.0.1:39539',flush=True)
   print('Start capture to automatically connect Warudo motion. Ctrl+C stops this local bundle only.',flush=True)
   while all(p.poll() is None for p in processes):time.sleep(.5)
   if any(p.returncode not in (None,0) for p in processes):
    exits=[]
    for name,child in zip(('backend','ui'),processes):
     code=child.poll();exits.append({'name':name,'pid':child.pid,'exit_code':code,'exit_hex':hex(code & 0xffffffff) if code is not None else None})
    record={'at':time.strftime('%Y-%m-%d %H:%M:%S'),'processes_before_cleanup':exits,'note':'A still-running sibling is terminated by launcher cleanup, not necessarily the original failure.'}
    (logs/'last-process-exit.json').write_text(json.dumps(record,indent=2),encoding='utf8')
    raise RuntimeError('Child process exited: '+str(exits)+'; see logs/last-process-exit.json and corresponding backend.log/ui.log')
 finally:
  for child in reversed(processes):
   if child.poll() is None:child.terminate()
  for child in reversed(processes):
   try:child.wait(timeout=15)
   except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
if __name__=='__main__':
 try:main()
 except KeyboardInterrupt:pass
 except Exception as e:print(type(e).__name__+': '+str(e),file=sys.stderr);sys.exit(1)
