"""Portable runtime configuration; no system environment or cloud dependency."""
import ipaddress
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent


def configure():
    if os.environ.get('_FLOWHMR_INITIALIZED_PID') == str(os.getpid()):
        return
    os.environ['_FLOWHMR_INITIALIZED_PID'] = str(os.getpid())
    state = ROOT / 'state'
    state.mkdir(exist_ok=True)
    cache = state / 'cache'
    for key, suffix in {'HF_HOME':'hf','TORCH_HOME':'torch','TORCHINDUCTOR_CACHE_DIR':'inductor',
                        'TRITON_CACHE_DIR':'triton','TEMP':'temp','TMP':'temp',
                        'MPLCONFIGDIR':'matplotlib','XDG_CACHE_HOME':'xdg'}.items():
        path = cache / suffix
        path.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(path)
    for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy','PYTHONHOME','PYTHONPATH'):
        os.environ.pop(key, None)
    os.environ.update(PERSONA_FLOWHMR_MODELS=str(ROOT/'engine/models'),
                      HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
                      PYTHONNOUSERSITE='1', PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8',
                      OMP_NUM_THREADS='8', NO_PROXY='127.0.0.1,localhost,::1')
    os.environ.pop('TORCHDYNAMO_DISABLE', None)
    # Torch 2.8's static CUDA launcher uses a C long for a pointer on Windows.
    # Use Triton's native launcher; Inductor compilation/CUDA graphs remain on.
    os.environ['TORCHINDUCTOR_USE_STATIC_CUDA_LAUNCHER'] = '0'
    win = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    os.environ['PATH'] = os.pathsep.join([str(ROOT/'tools/bin'),str(Path(sys.executable).parent),os.environ.get('PATH','')])
    for p in [ROOT,ROOT/'engine/src']:
        if str(p) not in sys.path:
            sys.path.insert(0,str(p))
    if hasattr(os,'add_dll_directory'):
        handles=[]
        for p in [Path(sys.executable).parent,Path(sys.prefix)/'DLLs',Path(sys.prefix)/'Lib/site-packages/torch/lib']:
            if p.is_dir():
                handles.append(os.add_dll_directory(str(p)))
        sys._flowhmr_dll_handles=handles
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):
            stream.reconfigure(encoding='utf-8',errors='replace')
    # Audit all Python socket calls, including sockets created in extension modules.
    # This is an application-level offline guard, not evidence of a physical air gap.
    def allowed(host):
        if host in (None,'localhost',b'localhost'):
            return True
        try:
            return ipaddress.ip_address(host.decode() if isinstance(host,bytes) else host).is_loopback
        except ValueError:
            return False
    def audit(event,args):
        address=None
        if event=='socket.connect':address=args[1]
        elif event=='socket.sendto':address=args[1]
        elif event=='socket.getaddrinfo':address=(args[0],args[1])
        if isinstance(address,tuple) and not allowed(address[0]):
            record={'at':time.time(),'pid':os.getpid(),'event':event,'host':str(address[0])}
            with (state/'offline-blocked.jsonl').open('a',encoding='utf8') as f:
                f.write(json.dumps(record)+'\n')
            raise OSError('Offline bundle permits loopback network only')
    sys.addaudithook(audit)
