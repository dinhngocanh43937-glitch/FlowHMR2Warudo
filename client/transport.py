"""Local mode permits cleartext WS/HTTP only on literal loopback addresses."""
import ssl,urllib.request
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit
ROOT=Path(__file__).resolve().parent
LOOPBACK={'127.0.0.1','::1'}
def tls_options(cfg,key):
 url=urlsplit(cfg[key])
 if url.username or url.password or not url.hostname:raise ValueError('Endpoint format')
 if cfg.get('deployment_mode')=='local' and (url.scheme!='ws' or url.hostname not in LOOPBACK):raise ValueError('Local mode accepts only ws:// loopback endpoints')
 if url.scheme=='ws':
  if cfg.get('deployment_mode')!='local' or url.hostname not in LOOPBACK:raise ValueError('Cleartext transport is restricted to local loopback mode')
  return {'proxy':None}
 if url.scheme!='wss':raise ValueError('Use wss for remote endpoints')
 cert=Path(cfg.get('ca_file','server.crt'));cert=cert if cert.is_absolute() else ROOT/cert
 context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);context.minimum_version=ssl.TLSVersion.TLSv1_2;context.load_verify_locations(cafile=str(cert))
 return {'ssl':context,'proxy':None}
def http_connection(cfg,path):
 opts=tls_options(cfg,'url');url=urlsplit(cfg['url']);scheme='https' if url.scheme=='wss' else 'http'
 endpoint=urlunsplit((scheme,url.netloc,'/'+path.lstrip('/'),'',''))
 handlers=[urllib.request.ProxyHandler({})]
 if 'ssl' in opts:handlers.append(urllib.request.HTTPSHandler(context=opts['ssl']))
 return endpoint,urllib.request.build_opener(*handlers)
