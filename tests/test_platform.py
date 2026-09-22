"""功能说明：四模块真实 HTTP/C++ 回归测试，使用临时点云和独立后端进程。"""
import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


class PlatformIntegrationTest(unittest.TestCase):
    """覆盖页面路由、模块裁剪、点云处理和审核后的真实描述子输出。"""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='ros-platform-test-')
        cls.directory = Path(cls.temp.name)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        cls.url = f'http://127.0.0.1:{port}'
        cls.server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT/'backend', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                cls.get('/api/health')
                break
            except OSError:
                time.sleep(.1)
        else:
            cls.server.terminate()
            raise RuntimeError('测试后端启动失败')
        points = [(x*.2, y*.2, 0) for x in range(-20,21) for y in range(-20,21)]
        points += [(x*.2, 3, z*.2) for x in range(-20,21) for z in range(1,16)]
        points += [(3, y*.2, z*.2) for y in range(-20,21) for z in range(1,16)]
        cls.pcd = cls.directory/'room.pcd'
        cls.pcd.write_text(f'VERSION .7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\nWIDTH {len(points)}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {len(points)}\nDATA ascii\n'+'\n'.join(' '.join(map(str,p)) for p in points))

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.temp.cleanup()

    @classmethod
    def get(cls, path, payload=None):
        req = Request(cls.url+path, data=None if payload is None else json.dumps(payload).encode(), headers={'Content-Type':'application/json'})
        with urlopen(req, timeout=90) as response:
            return json.load(response)

    def run_tool(self, key, **values):
        result = self.get('/api/tools/'+key+'/run', {'values':{'input_pcd':str(self.pcd), 'output_dir':str(self.directory/key), **values}})
        self.assertEqual(result['status'], 'success', result)
        return result

    def test_four_modules_and_routes(self):
        self.assertEqual({t['key'] for t in self.get('/api/tools')}, {'pcd_map','pcd_tile','global_relocalization_candidates','ros_nav_test'})
        for path in ['/', '/tools/pcd-map', '/tools/pcd-tile', '/tools/global-relocalization']:
            with urlopen(self.url+path) as response:
                self.assertIn(b'<div id="app">', response.read())
        for key in ['network_scan','costmap','mtslash_export']:
            with self.assertRaises(HTTPError) as error:
                self.get('/api/tools/'+key+'/run', {'values':{}})
            self.assertEqual(error.exception.code, 404)

    def test_map_and_tile(self):
        result = self.run_tool('pcd_map', resolution='.2')
        self.assertTrue(Path(result['data']['pgm_path']).is_file())
        self.assertTrue(Path(result['data']['yaml_path']).is_file())
        self.run_tool('pcd_tile', tile_size='3', overlap='.2', format='binary')
        self.assertTrue(list((self.directory/'pcd_tile').rglob('*.pcd')))
        self.assertTrue(list((self.directory/'pcd_tile').rglob('*metadata*')))

    def test_reviewed_candidates_real_descriptors(self):
        candidates = [{'candidate_id':i+1,'x':x,'y':y,'z':.35,'yaw_deg':yaw,'roll_deg':0,'pitch_deg':0,'source':'manual_added','locked':True} for i,(x,y,yaw) in enumerate([(0,0,0),(1,0,90)])]
        result = self.run_tool('global_relocalization_candidates', final_candidates_json=json.dumps(candidates), config_json=json.dumps({'virtual_lidar':{'horizontal_step_deg':5,'vertical_step_deg':5}}))
        arrays = {key:np.load(result['data'][key]) for key in ['candidates_npy_path','descriptors_npy_path','ring_keys_npy_path']}
        self.assertEqual({a.shape[0] for a in arrays.values()}, {2})
        self.assertTrue(np.isfinite(arrays['descriptors_npy_path']).all())
        self.assertGreater(np.count_nonzero(arrays['descriptors_npy_path']), 0)

    def test_offline_map_and_ground_raycast(self):
        from urllib.parse import urlencode
        result = self.get('/api/tools/ros_nav_test/offline-map-preview?'+urlencode({'pcd_path':str(self.pcd),'voxel_leaf_m':.2,'max_points':6000}))
        self.assertTrue(result)
        hit = self.get('/api/tools/ros_nav_test/offline-map-raycast', {'origin':[0,0,3], 'direction':[0,0,-1]})
        self.assertTrue(hit.get('hit'), hit)


if __name__ == '__main__':
    unittest.main(verbosity=2)
