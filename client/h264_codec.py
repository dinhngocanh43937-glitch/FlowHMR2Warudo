"""Annex-B H.264 access units: zero reordering, explicit VBV, one AU per call."""
from fractions import Fraction
import av
TIME_BASE=Fraction(1,30)
class H264Encoder:
 def __init__(self,width,height,bitrate_kbps=1500):
  if width%2 or height%2 or not 16<=width<=1920 or not 16<=height<=1920:raise ValueError('H264 dimensions')
  if not 300<=bitrate_kbps<=5000:raise ValueError('H264 bitrate')
  self.width=width;self.height=height;self.last_key=None
  c=av.CodecContext.create('libx264','w');c.width=width;c.height=height;c.pix_fmt='yuv420p';c.time_base=TIME_BASE;c.framerate=Fraction(30,1);c.bit_rate=bitrate_kbps*1000;c.gop_size=30;c.max_b_frames=0;c.thread_count=2;c.thread_type='SLICE'
  c.options={'preset':'veryfast','tune':'zerolatency','profile':'baseline','x264-params':f'bframes=0:rc-lookahead=0:sync-lookahead=0:scenecut=0:repeat-headers=1:annexb=1:keyint=30:min-keyint=1:vbv-maxrate={bitrate_kbps}:vbv-bufsize={max(60,bitrate_kbps//5)}'}
  c.open();self.codec=c
 def encode(self,bgr,seq,force_key=False):
  if (bgr.shape[1],bgr.shape[0])!=(self.width,self.height):raise ValueError('Source dimensions changed; reconnect encoder')
  frame=av.VideoFrame.from_ndarray(bgr,format='bgr24');frame.pts=seq;frame.time_base=TIME_BASE
  if force_key or self.last_key is None or seq-self.last_key>=30:frame.pict_type=av.video.frame.PictureType.I
  packets=self.codec.encode(frame)
  if len(packets)!=1 or packets[0].pts!=seq or packets[0].dts!=seq:raise RuntimeError('Encoder introduced buffering/reordering')
  p=packets[0]
  if p.is_keyframe:self.last_key=seq
  return bytes(p),p.is_keyframe
 def finish(self):
  pending=self.codec.encode(None)
  if pending:raise RuntimeError('Unexpected delayed H264 packets')
class H264Decoder:
 def __init__(self):
  self.codec=av.CodecContext.create('h264','r');self.codec.thread_count=1;self.codec.thread_type='SLICE';self.codec.options={'flags':'low_delay','max_pixels':str(1920*1920)};self.codec.open();self.last_seq=-1
 def decode(self,payload,seq):
  if seq<=self.last_seq or not 0<len(payload)<=3*1024*1024:raise ValueError('H264 packet metadata')
  p=av.Packet(payload);p.pts=p.dts=seq;p.time_base=TIME_BASE;frames=self.codec.decode(p)
  if len(frames)!=1:raise ValueError('H264 requires exactly one low-delay frame per message')
  frame=frames[0]
  if frame.pts!=seq or not 16<=frame.width<=1920 or not 16<=frame.height<=1920:raise ValueError('H264 decoded dimensions/timing')
  self.last_seq=seq
  return frame.to_ndarray(format='rgb24')
