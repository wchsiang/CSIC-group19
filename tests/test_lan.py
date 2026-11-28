import json
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import lan_ip, parse_args

LAN_IP = lan_ip()
HAS_LAN_IP = bool(LAN_IP) and not LAN_IP.startswith('127.')


class LanArgs(unittest.TestCase):
    def test_lan_is_off_by_default(self):
        self.assertFalse(parse_args([]).lan)

    def test_lan_switch(self):
        self.assertTrue(parse_args(['--lan']).lan)


@unittest.skipUnless(HAS_LAN_IP, 'no non-loopback IPv4 address available')
class LanBinding(unittest.TestCase):
    """Starts the real app.py process and checks which addresses it accepts."""

    def start(self, *extra):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        db = Path(self.temp.name) / 'test.sqlite3'
        self.proc = subprocess.Popen(
            [sys.executable, str(ROOT / 'app.py'), '--port', '0', '--db', str(db), *extra],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8')
        self.addCleanup(self.stop)
        first = self.read_line()
        match = re.search(r'http://127\.0\.0\.1:(\d+)', first)
        self.assertIsNotNone(match, f'unexpected startup output: {first!r}')
        self.port = int(match.group(1))
        self.lines = [first]
        if extra:
            self.lines += [self.read_line(), self.read_line()]

    def read_line(self):
        result = []
        reader = threading.Thread(target=lambda: result.append(self.proc.stdout.readline()))
        reader.start()
        reader.join(10)
        if not result or not result[0]:
            self.fail('app.py did not print startup output within 10 seconds')
        return result[0]

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.proc.stdout.close()

    def get(self, host):
        with urlopen(f'http://{host}:{self.port}/', timeout=5) as response:
            return response.status

    def test_default_binds_loopback_only(self):
        self.start()
        self.assertEqual(self.get('127.0.0.1'), 200)
        with self.assertRaises(URLError):
            self.get(LAN_IP)

    def test_lan_accepts_network_address(self):
        self.start('--lan')
        self.assertIn(f'http://{LAN_IP}:{self.port}', self.lines[1])
        self.assertIn('警告', self.lines[2])
        self.assertEqual(self.get(LAN_IP), 200)
        base = f'http://{LAN_IP}:{self.port}'
        body = json.dumps({'title': 'LAN', 'transcript': '從區域網路建立'}).encode()
        request = Request(base + '/api/meetings', data=body, method='POST',
                          headers={'Content-Type': 'application/json', 'Origin': base})
        with urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 201)


if __name__ == '__main__':
    unittest.main()
