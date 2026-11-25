"""Export useful local evidence without connection tokens or original video."""
import io
import json
from pathlib import Path
import re
import zipfile

ROOT=Path(__file__).resolve().parent


def export(snapshot=None):
    secrets=[]
    for name in ('state/backend.json','client/receiver.json'):
        p=ROOT/name
        if p.exists():
            cfg=json.loads(p.read_text(encoding='utf8'))
            secrets.extend(str(v) for k,v in cfg.items() if 'token' in k and isinstance(v,str))
    def redact(text):
        for secret in secrets:
            text=text.replace(secret,'[REDACTED]')
        return re.sub(r'Bearer\s+[\w.\-]+','Bearer [REDACTED]',text)
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        if snapshot is not None:
            z.writestr('status.json',redact(json.dumps(snapshot,ensure_ascii=False,indent=2)))
        for folder in ['logs','reports']:
            p=ROOT/folder
            if p.exists():
                for f in p.rglob('*'):
                    if f.is_file() and f.suffix in ('.log','.json','.txt','.md','.jsonl'):
                        z.writestr(f.relative_to(ROOT).as_posix(),redact(f.read_text(encoding='utf8',errors='replace')[-2_000_000:]))
        p=ROOT/'state/offline-blocked.jsonl'
        if p.exists():z.writestr('offline-blocked.jsonl',redact(p.read_text(encoding='utf8')))
        z.writestr('README.txt','Includes local status and recent logs. No model weights, source video, or authentication configuration. Review paths before sharing.')
    return out.getvalue()


if __name__=='__main__':
    p=ROOT/'logs/diagnostics.zip';p.parent.mkdir(exist_ok=True);p.write_bytes(export());print(p)
