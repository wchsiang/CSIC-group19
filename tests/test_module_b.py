import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from app import Store, handler_for
from summarizer import (
    analyze_transcript,
    extract_heuristics,
    test_llm_connection,
    _call_claude,
    _call_gemini,
    _call_openai,
)


def mock_http_response(content_dict):
    body_bytes = json.dumps(content_dict).encode('utf-8')
    mock = MagicMock()
    mock.__enter__.return_value = mock
    mock.read.return_value = body_bytes
    return mock


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
        self.assertFalse(any('使用者測試時間還沒有決定' in d for d in decisions))

        # 3. Action item validation
        action_items = result['action_items']
        self.assertEqual(len(action_items), 4)

        ming_task = next(i for i in action_items if i['assignee'] == '小明')
        self.assertEqual(ming_task['due'], '週五前')
        self.assertIn('建立會議與文字輸入', ming_task['task'])

        hua_task = next(i for i in action_items if i['assignee'] == '小華')
        self.assertIsNone(hua_task['due'])
        self.assertIn('AI 整理', hua_task['task'])

        mei_task = next(i for i in action_items if i['assignee'] == '小美')
        self.assertIsNone(mei_task['due'])

        jie_task = next(i for i in action_items if i['assignee'] == '小傑')
        self.assertIsNone(jie_task['due'])

    def test_summary_api_endpoints_and_persistence(self):
        sample_path = Path(__file__).resolve().parents[1] / 'docs' / 'sample_transcript.txt'
        transcript = sample_path.read_text(encoding='utf-8')
        status, meeting = self.request('/api/meetings', 'POST', {
            'title': 'CP2 功能分工',
            'transcript': transcript
        })
        self.assertEqual(status, 201)
        meeting_id = meeting['id']

        status, res = self.request(f'/api/meetings/{meeting_id}/summary')
        self.assertEqual(status, 404)

        status, summary = self.request(f'/api/meetings/{meeting_id}/summary', 'POST')
        self.assertEqual(status, 201)
        self.assertEqual(summary['meeting_id'], meeting_id)
        self.assertEqual(summary['source_revision'], 1)
        self.assertFalse(summary['is_stale'])
        self.assertGreater(len(summary['action_items']), 0)
        self.assertIn('離線規則', summary['provider'])

        status, fetched = self.request(f'/api/meetings/{meeting_id}/summary')
        self.assertEqual(status, 200)
        self.assertEqual(fetched['meeting_id'], meeting_id)
        self.assertEqual(fetched['summary'], summary['summary'])

        store = Store(self.db)
        direct = store.get_summary(meeting_id)
        self.assertIsNotNone(direct)
        self.assertEqual(direct['source_revision'], 1)

    def test_summary_staleness_lifecycle(self):
        status, meeting = self.request('/api/meetings', 'POST', {
            'title': '初始分工',
            'transcript': '小明：我負責前端。小華：我負責後端。'
        })
        meeting_id = meeting['id']

        status, summary_v1 = self.request(f'/api/meetings/{meeting_id}/summary', 'POST')
        self.assertEqual(status, 201)
        self.assertFalse(summary_v1['is_stale'])
        self.assertEqual(summary_v1['source_revision'], 1)

        status, updated_meeting = self.request(f'/api/meetings/{meeting_id}', 'PUT', {
            'title': '初始分工（修改）',
            'transcript': '小明：我改負責後端。小華：我改負責前端。',
            'revision': 1
        })
        self.assertEqual(status, 200)
        self.assertEqual(updated_meeting['revision'], 2)

        status, stale_summary = self.request(f'/api/meetings/{meeting_id}/summary')
        self.assertEqual(status, 200)
        self.assertTrue(stale_summary['is_stale'])
        self.assertEqual(stale_summary['source_revision'], 1)

        status, fresh_summary = self.request(f'/api/meetings/{meeting_id}/summary', 'POST')
        self.assertEqual(status, 201)
        self.assertFalse(fresh_summary['is_stale'])
        self.assertEqual(fresh_summary['source_revision'], 2)

    def test_manual_summary_edit_put(self):
        status, meeting = self.request('/api/meetings', 'POST', {
            'title': '測試手動編輯',
            'transcript': '小明：我負責測試。'
        })
        meeting_id = meeting['id']
        self.request(f'/api/meetings/{meeting_id}/summary', 'POST')

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
        status, _ = self.request('/api/meetings/non-existent-id/summary')
        self.assertEqual(status, 404)
        status, _ = self.request('/api/meetings/non-existent-id/summary', 'POST')
        self.assertEqual(status, 404)

        status, empty_meeting = self.request('/api/meetings', 'POST', {
            'title': '空內容測試',
            'transcript': ' '
        })
        self.assertEqual(status, 400)

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

    def test_test_llm_endpoint(self):
        # 1. Missing key
        status, res = self.request('/api/test-llm', 'POST', {'provider': 'gemini', 'api_key': ''})
        self.assertEqual(status, 400)
        self.assertIn('請輸入 API Key', res['error'])

        # 2. Unsupported provider
        status, res = self.request('/api/test-llm', 'POST', {'provider': 'unknown', 'api_key': 'abc'})
        self.assertEqual(status, 400)
        self.assertIn('不支援的模型提供商', res['error'])

        # 3. Successful test with mocked app.test_llm_connection
        with patch.object(app, 'test_llm_connection', return_value={'ok': True, 'message': 'Google Gemini API 連線驗證成功！'}):
            status, res = self.request('/api/test-llm', 'POST', {'provider': 'gemini', 'api_key': 'AIzaTestKey'})
            self.assertEqual(status, 200)
            self.assertTrue(res['ok'])
            self.assertIn('成功', res['message'])

    def test_mock_llm_providers_parsing(self):
        expected_json = {
            "summary": "模型萃取出的精確摘要段落。",
            "decisions": ["決策事項一", "決策事項二"],
            "action_items": [{"assignee": "小明", "task": "後端實作", "due": "下週三"}]
        }

        # 1. Test Gemini parsing
        gemini_raw = {
            "candidates": [{
                "content": {
                    "parts": [{"text": json.dumps(expected_json)}]
                }
            }]
        }
        with patch('urllib.request.urlopen', return_value=mock_http_response(gemini_raw)):
            res_gemini = _call_gemini("逐字稿", "標題", "AIzaTest")
            self.assertEqual(res_gemini['summary'], "模型萃取出的精確摘要段落。")
            self.assertEqual(len(res_gemini['decisions']), 2)
            self.assertEqual(res_gemini['action_items'][0]['assignee'], "小明")

        # 2. Test Claude parsing (with markdown backticks wrapping JSON)
        claude_raw = {
            "content": [{
                "text": f"```json\n{json.dumps(expected_json)}\n```"
            }]
        }
        with patch('urllib.request.urlopen', return_value=mock_http_response(claude_raw)):
            res_claude = _call_claude("逐字稿", "標題", "sk-ant-test")
            self.assertEqual(res_claude['summary'], "模型萃取出的精確摘要段落。")
            self.assertEqual(res_claude['action_items'][0]['due'], "下週三")

        # 3. Test OpenAI parsing
        openai_raw = {
            "choices": [{
                "message": {
                    "content": json.dumps(expected_json)
                }
            }]
        }
        with patch('urllib.request.urlopen', return_value=mock_http_response(openai_raw)):
            res_openai = _call_openai("逐字稿", "標題", "sk-test")
            self.assertEqual(res_openai['summary'], "模型萃取出的精確摘要段落。")
            self.assertEqual(len(res_openai['decisions']), 2)


if __name__ == '__main__':
    unittest.main()
