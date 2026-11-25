import importlib.util, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('params',ROOT/'server/runtime_parameters.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class SourceTests(unittest.TestCase):
    def test_delays(self):
        for n in [200,300,400,500,600,700,800,1000]:
            self.assertEqual(m.ParameterControl.validate({'playout_delay_ms':n}),{'playout_delay_ms':n})
    def test_invalid(self):
        for value in [True,0,250,1500]:
            with self.assertRaises(m.ParameterError):m.ParameterControl.validate({'playout_delay_ms':value})
    def test_legacy(self):
        old={k:v for k,v in m.DEFAULTS.items() if k not in ['playout_delay_ms','sam_chunk_size']}
        v=m.ParameterControl.validate(old,complete=True)
        self.assertEqual(v['playout_delay_ms'],800);self.assertEqual(v['sam_chunk_size'],2)
    def test_no_private_configs(self):
        self.assertFalse((ROOT/'state/backend.json').exists())
        self.assertFalse((ROOT/'client/receiver.json').exists())
if __name__=='__main__':unittest.main()
