import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Store, handler_for
from summarizer import analyze_transcript, extract_heuristics


class ModuleBTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'test_b.sqlite3'
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
        body = json.dumps(data).encode('utf-8') if data is not None else None
        req = Request(
            self.base + path,
            data=body,
            method=method,
            headers={'Content-Type': 'application/json', **headers}
        )
        try:
            response = urlopen(req)
        except HTTPError as error:
            response = error
        with response:
            try:
                res_body = json.loads(response.read().decode('utf-8'))
            except Exception:
                res_body = None
            return response.status, res_body

    def test_transcript_parser_heuristics(self):
        sample_path = Path(__file__).resolve().parents[1] / 'docs' / 'sample_transcript.txt'
        transcript = sample_path.read_text(encoding='utf-8')
        result = extract_heuristics(transcript)

        # 1. Summary validation
        self.assertIn('CP2 功能分工', result['summary'])
        self.assertIn('小明', result['summary'])
        self.assertIn('小華', result['summary'])

        # 2. Decision validation
        decisions = result['decisions']
        self.assertTrue(any('先使用文字逐字稿' in d for d in decisions))
        self.assertTrue(any('AI 不應替沒有明確期限的工作自行設定日期' in d for d in decisions))
        # Ensure undecided topics are NOT included as decisions
        self.assertFalse(any('使用者測試時間還沒有決定' in d for d in decisions))

        # 3. Action item validation
        action_items = result['action_items']
        self.assertEqual(len(action_items), 4)

        # Ming has an explicit deadline
        ming_task = next(i for i in action_items if i['assignee'] == '小明')
        self.assertEqual(ming_task['due'], '週五前')
        self.assertIn('建立會議與文字輸入', ming_task['task'])

        # Hua, Mei, and Jie have NO explicit deadline -> due must be None (no hallucinated dates)
        hua_task = next(i for i in action_items if i['assignee'] == '小華')
        self.assertIsNone(hua_task['due'])
        self.assertIn('AI 整理', hua_task['task'])

        mei_task = next(i for i in action_items if i['assignee'] == '小美')
        self.assertIsNone(mei_task['due'])

        jie_task = next(i for i in action_items if i['assignee'] == '小傑')
        self.assertIsNone(jie_task['due'])

    def test_summary_api_endpoints_and_persistence(self):
        # 1. Create a meeting
        sample_path = Path(__file__).resolve().parents[1] / 'docs' / 'sample_transcript.txt'
        transcript = sample_path.read_text(encoding='utf-8')
        status, meeting = self.request('/api/meetings', 'POST', {
            'title': 'CP2 功能分工',
            'transcript': transcript
        })
        self.assertEqual(status, 201)
        meeting_id = meeting['id']

        # 2. GET summary before generating should return 404
        status, res = self.request(f'/api/meetings/{meeting_id}/summary')
        self.assertEqual(status, 404)

        # 3. POST summary triggers extraction and persistence
        status, summary = self.request(f'/api/meetings/{meeting_id}/summary', 'POST')
        self.assertEqual(status, 201)
        self.assertEqual(summary['meeting_id'], meeting_id)
        self.assertEqual(summary['source_revision'], 1)
        self.assertFalse(summary['is_stale'])
        self.assertGreater(len(summary['action_items']), 0)

        # 4. GET summary returns the persisted summary
        status, fetched = self.request(f'/api/meetings/{meeting_id}/summary')
        self.assertEqual(status, 200)
        self.assertEqual(fetched['meeting_id'], meeting_id)
        self.assertEqual(fetched['summary'], summary['summary'])

        # 5. Verify direct store query
        store = Store(self.db)
        direct = store.get_summary(meeting_id)
        self.assertIsNotNone(direct)
        self.assertEqual(direct['source_revision'], 1)

    def test_summary_staleness_lifecycle(self):
        # 1. Create meeting
        status, meeting = self.request('/api/meetings', 'POST', {
            'title': '初始分工',
            'transcript': '小明：我負責前端。小華：我負責後端。'
        })
        meeting_id = meeting['id']

        # 2. Generate summary at revision 1
        status, summary_v1 = self.request(f'/api/meetings/{meeting_id}/summary', 'POST')
        self.assertEqual(status, 201)
        self.assertFalse(summary_v1['is_stale'])
        self.assertEqual(summary_v1['source_revision'], 1)

        # 3. Update meeting transcript -> revision becomes 2
        status, updated_meeting = self.request(f'/api/meetings/{meeting_id}', 'PUT', {
            'title': '初始分工（修改）',
            'transcript': '小明：我改負責後端。小華：我改負責前端。',
            'revision': 1
        })
        self.assertEqual(status, 200)
        self.assertEqual(updated_meeting['revision'], 2)

        # 4. GET summary should now indicate is_stale: True!
        status, stale_summary = self.request(f'/api/meetings/{meeting_id}/summary')
        self.assertEqual(status, 200)
        self.assertTrue(stale_summary['is_stale'])
        self.assertEqual(stale_summary['source_revision'], 1)

        # 5. Re-generate summary -> becomes up to date (is_stale: False, source_revision: 2)
        status, fresh_summary = self.request(f'/api/meetings/{meeting_id}/summary', 'POST')
        self.assertEqual(status, 201)
        self.assertFalse(fresh_summary['is_stale'])
        self.assertEqual(fresh_summary['source_revision'], 2)

    def test_manual_summary_edit_put(self):
        # Create meeting & generate summary
        status, meeting = self.request('/api/meetings', 'POST', {
            'title': '測試手動編輯',
            'transcript': '小明：我負責測試。'
        })
        meeting_id = meeting['id']
        self.request(f'/api/meetings/{meeting_id}/summary', 'POST')

        # Manually update summary and decisions via PUT
        update_payload = {
            'summary': '經過團隊討論修改後的摘要。',
            'decisions': ['團隊決策 A', '團隊決策 B'],
            'action_items': [{'assignee': '小明', 'task': '執行測試', 'due': '明天'}]
        }
        status, updated = self.request(f'/api/meetings/{meeting_id}/summary', 'PUT', update_payload)
        self.assertEqual(status, 200)
        self.assertEqual(updated['summary'], '經過團隊討論修改後的摘要。')
        self.assertEqual(len(updated['decisions']), 2)
        self.assertEqual(updated['action_items'][0]['due'], '明天')

    def test_summary_error_handling(self):
        # 1. Non-existent meeting
        status, _ = self.request('/api/meetings/non-existent-id/summary')
        self.assertEqual(status, 404)
        status, _ = self.request('/api/meetings/non-existent-id/summary', 'POST')
        self.assertEqual(status, 404)

        # 2. Meeting with empty transcript
        status, empty_meeting = self.request('/api/meetings', 'POST', {
            'title': '空內容測試',
            'transcript': ' '
        })
        self.assertEqual(status, 400)

        # 3. Cross origin request rejected
        status, meeting = self.request('/api/meetings', 'POST', {
            'title': '跨來源測試',
            'transcript': '小明：內容。'
        })
        meeting_id = meeting['id']
        status, _ = self.request(
            f'/api/meetings/{meeting_id}/summary',
            'POST',
            Origin='https://attacker.com'
        )
        self.assertEqual(status, 403)


if __name__ == '__main__':
    unittest.main()
