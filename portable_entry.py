"""Entrypoint invoked with runtime/python.exe -I."""
import runpy
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from portable_runtime import configure
configure()
target=sys.argv.pop(1) if len(sys.argv)>1 else 'launch_local.py'
path=(ROOT/target).resolve()
if not path.is_relative_to(ROOT):
    raise ValueError('Entrypoint must be inside the bundle')
sys.argv[0]=str(path)
sys.path.insert(0,str(path.parent))
runpy.run_path(str(path),run_name='__main__')
