import struct,uuid,math
HEADER=struct.Struct('!4s16sQd')
def pack(generation,seq,received_at,payload):
 return HEADER.pack(b'VMC1',uuid.UUID(generation).bytes,int(seq),float(received_at))+payload
def unpack(data):
 if not isinstance(data,bytes) or not HEADER.size<len(data)<=65535:raise ValueError('packet size')
 magic,g,seq,t=HEADER.unpack_from(data)
 if magic!=b'VMC1' or not math.isfinite(t) or not data[HEADER.size:].startswith(b'#bundle\0'):raise ValueError('packet format')
 return uuid.UUID(bytes=g).hex,seq,data[HEADER.size:]
