"""One-time correction for the previously shipped disabled-compile defaults."""
import json
REVISION='20261122-compile-restored'


def migrate(path,config):
    if config.get('compile_repair_revision')!=REVISION:
        config['torch_compile']=True
        config['flow_cuda_graphs']=True
        config['compile_repair_revision']=REVISION
        path.write_text(json.dumps(config,indent=2),encoding='utf8')
    return config
