import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Store, handler_for


class MeetingAPI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'test.sqlite3'
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(Store(self.db)))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, method='GET', data=None, **headers):
        body = json.dumps(data).encode() if data is not None else None
        request = Request(self.base + path, data=body, method=method,
                          headers={'Content-Type': 'application/json', **headers})
        try:
            response = urlopen(request)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read())

    def create(self):
        status, meeting = self.request('/api/meetings', 'POST',
                                       {'title': '  CP2 分工  ', 'transcript': '小明：週五交付。\n小華：我負責測試。'})
        self.assertEqual(status, 201)
        return meeting

    def test_create_load_list_and_persist(self):
        meeting = self.create()
        self.assertEqual(meeting['title'], 'CP2 分工')
        self.assertEqual(self.request('/api/meetings/' + meeting['id'])[1], meeting)
        items = self.request('/api/meetings')[1]['meetings']
        self.assertEqual(items[0]['id'], meeting['id'])
        self.assertNotIn('transcript', items[0])
        self.assertEqual(Store(self.db).get(meeting['id']), meeting)

    def test_update_and_reject_stale_write(self):
        meeting = self.create()
        path = '/api/meetings/' + meeting['id']
        update = {**meeting, 'transcript': '新版本內容'}
        status, saved = self.request(path, 'PUT', update)
        self.assertEqual(status, 200)
        self.assertEqual(saved['revision'], 2)
        self.assertEqual(self.request(path, 'PUT', update)[0], 409)
        self.assertEqual(self.request(path)[1]['transcript'], '新版本內容')

    def test_invalid_input_does_not_create_records(self):
        for data in [[], {}, {'title': ' ', 'transcript': '內容'},
                     {'title': '標題', 'transcript': '\n '},
                     {'title': 'a' * 121, 'transcript': '內容'},
                     {'title': '標題', 'transcript': 'a' * 100001}]:
            with self.subTest(data_type=type(data).__name__):
                self.assertEqual(self.request('/api/meetings', 'POST', data)[0], 400)
        self.assertEqual(self.request('/api/meetings')[1]['meetings'], [])

    def test_delete_requires_latest_revision(self):
        meeting = self.create()
        path = '/api/meetings/' + meeting['id']
        self.assertEqual(self.request(path, 'DELETE', {'revision': True})[0], 400)
        self.assertEqual(self.request(path, 'DELETE', {'revision': 1}, Origin='https://example.com')[0], 403)
        self.assertEqual(self.request(path, 'PUT', {**meeting, 'transcript': '最新內容'})[0], 200)
        self.assertEqual(self.request(path, 'DELETE', {'revision': 1})[0], 409)
        self.assertEqual(self.request(path)[1]['transcript'], '最新內容')
        self.assertEqual(self.request(path, 'DELETE', {'revision': 2}), (200, {'id': meeting['id']}))
        self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request(path, 'DELETE', {'revision': 2})[0], 404)
        self.assertEqual(self.request('/api/meetings')[1]['meetings'], [])

    def test_parallel_update_and_delete_cannot_both_win(self):
        meeting = self.create()
        path = '/api/meetings/' + meeting['id']
        start = threading.Barrier(2)

        def write(method, data):
            start.wait(timeout=5)
            return self.request(path, method, data)[0]

        with ThreadPoolExecutor(max_workers=2) as pool:
            update = pool.submit(write, 'PUT', {**meeting, 'transcript': '並行更新'})
            delete = pool.submit(write, 'DELETE', {'revision': meeting['revision']})
            statuses = update.result(), delete.result()
        self.assertIn(statuses, [(200, 409), (404, 200)])
        self.assertEqual(self.request(path)[0], 200 if statuses[0] == 200 else 404)

    def test_missing_record_and_cross_origin(self):
        self.assertEqual(self.request('/api/meetings/missing')[0], 404)
        self.assertEqual(self.request('/api/meetings/missing', 'PUT',
                                     {'title': '標題', 'transcript': '內容', 'revision': 1})[0], 404)
        self.assertEqual(self.request('/api/meetings', 'POST',
                                     {'title': '標題', 'transcript': '內容'}, Origin='https://example.com')[0], 403)

    def test_ui_assets_are_served(self):
        for path, expected in [('/', b'<!doctype html>'), ('/app.js', b'loadList'), ('/style.css', b':root')]:
            with urlopen(self.base + path) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(expected, response.read())


if __name__ == '__main__':
    unittest.main()
