"""Windows/Linux receiver: bounded latest-pose slot -> local Warudo VMC UDP.
30 Hz UDP heartbeat is not a claim of 30 unique inference poses per second.
"""
import argparse,json,socket,threading,time
from pathlib import Path
from websockets.sync.client import connect
from protocol import unpack
from transport import tls_options
class Receiver:
 def __init__(self,cfg):
  self.cfg=cfg;self.stop=threading.Event();self.lock=threading.Lock();self.latest=None;self.rx=0;self.tx=0;self.sessions=0;self.last_key=None;self.error=''
  self.connected=False;self.ws=None;self.last_received=None;self.byte_rx=0
  self.sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
 def receive(self):
  backoff=1
  while not self.stop.is_set():
   try:
    with connect(self.cfg['url'],**tls_options(self.cfg,'url'),additional_headers={'Authorization':'Bearer '+self.cfg['token']},max_size=65535,max_queue=1,compression=None,open_timeout=10,ping_interval=10,ping_timeout=10) as ws:
     self.connected=True;self.ws=ws
     self.sessions+=1;backoff=1;self.error='';self.last_key=None
     with self.lock:self.latest=None
     while not self.stop.is_set():
      try:data=ws.recv(timeout=1)
      except TimeoutError:continue
      gen,seq,payload=unpack(data)
      if self.last_key and self.last_key[0]==gen and seq<=self.last_key[1]:continue
      self.last_key=(gen,seq)
      with self.lock:self.latest=(time.monotonic(),payload)
      self.rx+=1;self.byte_rx+=len(data);self.last_received=time.monotonic()
   except Exception as e:
    self.connected=False;self.ws=None;self.error='' if self.stop.is_set() else type(e).__name__
    with self.lock:self.latest=None
    self.stop.wait(backoff);backoff=min(backoff*2,10)
 def run(self,duration=None):
  thread=threading.Thread(target=self.receive,daemon=True);thread.start();start=time.monotonic();tick=start;last_log=start;old_rx=old_tx=0;fps=self.cfg.get('output_fps',30)
  try:
   while not self.stop.is_set() and (duration is None or time.monotonic()-start<duration):
    now=time.monotonic()
    with self.lock:p=self.latest
    if p and now-p[0]<=self.cfg.get('stale_timeout_s',2):self.sock.sendto(p[1],(self.cfg.get('udp_host','127.0.0.1'),int(self.cfg.get('udp_port',39539))));self.tx+=1
    if now-last_log>=5:
     print(json.dumps(dict(unique_rx_per_s=round((self.rx-old_rx)/(now-last_log),1),udp_per_s=round((self.tx-old_tx)/(now-last_log),1),sessions=self.sessions,error=self.error)),flush=True);last_log=now;old_rx=self.rx;old_tx=self.tx
    tick+=1/self.cfg.get('output_fps',30)
    if tick<now:tick=now
    self.stop.wait(max(0,tick-time.monotonic()))
  finally:
   self.stop.set()
   if self.ws:
    try:self.ws.close()
    except Exception:pass
   thread.join(timeout=3);self.sock.close();self.connected=False
  return dict(received_unique=self.rx,sent_udp=self.tx,sessions=self.sessions,error=self.error)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--config',default=str(Path(__file__).with_name('receiver.json')));p.add_argument('--seconds',type=float);args=p.parse_args();c=json.loads(Path(args.config).read_text(encoding='utf-8'));print('Receiving motion; Warudo UDP target:',c.get('udp_host','127.0.0.1'),c.get('udp_port',39539),flush=True)
 tls_options(c,'url')
 try:print(json.dumps(Receiver(c).run(args.seconds)),flush=True)
 except KeyboardInterrupt:pass
