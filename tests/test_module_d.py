"""Module D: cross-meeting to-do overview and reconciliation on summary regeneration."""
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Store, handler_for

TRANSCRIPT = '小明：我負責前端畫面，週五前完成。\n小華：我負責後端 API。'


class ModuleDTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'test_d.sqlite3'
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(Store(self.db)))
        self.server.RequestHandlerClass.log_message = lambda *args: None
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
        req = Request(self.base + path, data=body, method=method,
                      headers={'Content-Type': 'application/json', **headers})
        try:
            response = urlopen(req)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read().decode('utf-8'))

    def meeting(self, transcript=TRANSCRIPT, title='分工'):
        status, meeting = self.request('/api/meetings', 'POST', {'title': title, 'transcript': transcript})
        self.assertEqual(status, 201)
        return meeting

    def update_transcript(self, meeting, transcript):
        status, updated = self.request(f"/api/meetings/{meeting['id']}", 'PUT', {
            'title': meeting['title'], 'transcript': transcript, 'revision': meeting['revision']})
        self.assertEqual(status, 200)
        return updated

    def generate(self, meeting_id):
        status, summary = self.request(f'/api/meetings/{meeting_id}/summary', 'POST', {'provider': 'heuristic'})
        self.assertEqual(status, 201)
        return summary

    def by_task(self, items):
        return {item['task']: item for item in items}

    def test_generated_items_get_ids_and_appear_in_overview(self):
        meeting = self.meeting()
        summary = self.generate(meeting['id'])
        items = self.by_task(summary['action_items'])
        self.assertEqual(set(items), {'前端畫面', '後端 API'})
        for item in items.values():
            self.assertTrue(item['id'])
            self.assertEqual(item['status'], 'open')
            self.assertEqual(item['origin'], 'ai')
            self.assertFalse(item['missing_from_source'])

        status, body = self.request('/api/action-items')
        self.assertEqual(status, 200)
        self.assertEqual(len(body['items']), 2)
        self.assertEqual(body['items'][0]['meeting_title'], '分工')
        self.assertFalse(body['items'][0]['summary_stale'])

    def test_done_status_survives_regeneration(self):
        meeting = self.meeting()
        front = self.by_task(self.generate(meeting['id'])['action_items'])['前端畫面']
        status, done = self.request(f"/api/action-items/{front['id']}", 'PUT', {'status': 'done'})
        self.assertEqual((status, done['status']), (200, 'done'))
        self.assertTrue(done['done_at'])

        meeting = self.update_transcript(meeting, TRANSCRIPT + '\n小美：我負責簡報。')
        _, overview = self.request('/api/action-items')
        self.assertTrue(all(item['summary_stale'] for item in overview['items']))

        items = self.by_task(self.generate(meeting['id'])['action_items'])
        self.assertEqual(items['前端畫面']['id'], front['id'])
        self.assertEqual(items['前端畫面']['status'], 'done')
        self.assertEqual(items['簡報']['status'], 'open')

    def test_reworded_task_for_same_person_keeps_status(self):
        meeting = self.meeting()
        front = self.by_task(self.generate(meeting['id'])['action_items'])['前端畫面']
        self.request(f"/api/action-items/{front['id']}", 'PUT', {'status': 'done'})
        meeting = self.update_transcript(meeting, TRANSCRIPT.replace('前端畫面', '前端畫面設計'))
        items = self.by_task(self.generate(meeting['id'])['action_items'])
        self.assertEqual(items['前端畫面設計']['id'], front['id'])
        self.assertEqual(items['前端畫面設計']['status'], 'done')

    def test_same_task_for_different_person_is_not_merged(self):
        meeting = self.meeting()
        front = self.by_task(self.generate(meeting['id'])['action_items'])['前端畫面']
        meeting = self.update_transcript(meeting, TRANSCRIPT.replace('小明', '小美'))
        items = self.by_task(self.generate(meeting['id'])['action_items'])
        self.assertNotEqual(items['前端畫面']['id'], front['id'])
        _, overview = self.request('/api/action-items')
        flagged = [item for item in overview['items'] if item['missing_from_source']]
        self.assertEqual([item['id'] for item in flagged], [front['id']])

    def test_item_missing_after_regeneration_is_flagged_not_deleted(self):
        meeting = self.meeting()
        backend = self.by_task(self.generate(meeting['id'])['action_items'])['後端 API']
        meeting = self.update_transcript(meeting, '小明：我負責前端畫面，週五前完成。')
        items = self.by_task(self.generate(meeting['id'])['action_items'])
        self.assertTrue(items['後端 API']['missing_from_source'])
        self.assertFalse(items['前端畫面']['missing_from_source'])

        status, kept = self.request(f"/api/action-items/{backend['id']}", 'PUT', {'keep': True})
        self.assertEqual(status, 200)
        self.assertFalse(kept['missing_from_source'])

        status, _ = self.request(f"/api/action-items/{backend['id']}", 'DELETE')
        self.assertEqual(status, 200)
        _, overview = self.request('/api/action-items')
        self.assertEqual([item['task'] for item in overview['items']], ['前端畫面'])

    def test_manual_edit_matches_by_id_and_deletes_omitted_items(self):
        meeting = self.meeting()
        items = self.by_task(self.generate(meeting['id'])['action_items'])
        front = items['前端畫面']
        self.request(f"/api/action-items/{front['id']}", 'PUT', {'status': 'done'})

        status, edited = self.request(f"/api/meetings/{meeting['id']}/summary", 'PUT', {
            'summary': '人工修正', 'decisions': [], 'provider': '人工微調',
            'action_items': [
                {'id': front['id'], 'assignee': '小明', 'task': '首頁與列表畫面', 'due': '下週一'},
                {'assignee': '小美', 'task': '簡報', 'due': None},
            ]})
        self.assertEqual(status, 200)
        result = self.by_task(edited['action_items'])
        self.assertEqual(set(result), {'首頁與列表畫面', '簡報'})
        self.assertEqual(result['首頁與列表畫面']['id'], front['id'])
        self.assertEqual(result['首頁與列表畫面']['status'], 'done')
        self.assertEqual(result['首頁與列表畫面']['origin'], 'manual')
        self.assertEqual(result['簡報']['origin'], 'manual')

    def test_regeneration_does_not_overwrite_manual_edit(self):
        meeting = self.meeting()
        front = self.by_task(self.generate(meeting['id'])['action_items'])['前端畫面']
        self.request(f"/api/meetings/{meeting['id']}/summary", 'PUT', {
            'summary': '人工修正', 'decisions': [], 'provider': '人工微調',
            'action_items': [{'id': front['id'], 'assignee': '小明', 'task': '前端畫面', 'due': '12/1'}]})
        meeting = self.update_transcript(meeting, TRANSCRIPT + '\n')
        items = self.by_task(self.generate(meeting['id'])['action_items'])
        self.assertEqual(items['前端畫面']['id'], front['id'])
        self.assertEqual(items['前端畫面']['due'], '12/1')
        self.assertEqual(items['前端畫面']['origin'], 'manual')

    def test_overview_filters(self):
        first = self.meeting()
        self.generate(first['id'])
        second = self.meeting('小明：我負責測試。', title='第二次')
        test_item = self.generate(second['id'])['action_items'][0]
        self.request(f"/api/action-items/{test_item['id']}", 'PUT', {'status': 'done'})

        _, mine = self.request('/api/action-items?assignee=' + quote('小明'))
        self.assertEqual({item['task'] for item in mine['items']}, {'前端畫面', '測試'})
        _, open_items = self.request('/api/action-items?status=open')
        self.assertEqual({item['task'] for item in open_items['items']}, {'前端畫面', '後端 API'})
        _, everything = self.request('/api/action-items')
        self.assertEqual(everything['items'][-1]['status'], 'done')
        status, _ = self.request('/api/action-items?status=later')
        self.assertEqual(status, 400)

    def test_invalid_updates(self):
        meeting = self.meeting()
        item = self.generate(meeting['id'])['action_items'][0]
        path = f"/api/action-items/{item['id']}"
        for body in ({'status': 'later'}, {'keep': False}, {}, ['done']):
            status, error = self.request(path, 'PUT', body)
            self.assertEqual(status, 400, body)
            self.assertIn('error', error)
        self.assertEqual(self.request('/api/action-items/missing', 'PUT', {'status': 'done'})[0], 404)
        self.assertEqual(self.request('/api/action-items/missing', 'DELETE')[0], 404)
        self.assertEqual(self.request(path, 'PUT', {'status': 'done'}, Origin='http://evil.example')[0], 403)
        self.assertEqual(self.request(path, 'PUT', {'status': 'done'}, **{'Content-Type': 'text/plain'})[0], 415)

    def test_deleting_meeting_removes_its_items(self):
        meeting = self.meeting()
        self.generate(meeting['id'])
        status, _ = self.request(f"/api/meetings/{meeting['id']}", 'DELETE', {'revision': meeting['revision']})
        self.assertEqual(status, 200)
        self.assertEqual(self.request('/api/action-items')[1]['items'], [])

    def test_summaries_saved_before_module_d_are_backfilled(self):
        legacy = Path(self.temp.name) / 'legacy.sqlite3'
        with sqlite3.connect(legacy) as db:
            db.execute('''CREATE TABLE meetings (id TEXT PRIMARY KEY, title TEXT NOT NULL,
                transcript TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL)''')
            db.execute('''CREATE TABLE summaries (meeting_id TEXT PRIMARY KEY, source_revision INTEGER NOT NULL,
                summary TEXT NOT NULL, decisions TEXT NOT NULL, action_items TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT 'heuristic', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
            db.execute("INSERT INTO meetings VALUES ('m1','舊會議','原文',1,'2026-11-20','2026-11-20')")
            db.execute("INSERT INTO summaries VALUES ('m1',1,'摘要','[]',?,'人工微調','2026-11-20','2026-11-20')",
                       (json.dumps([{'assignee': '小明', 'task': '舊待辦', 'due': None}, {'task': ''}],
                                   ensure_ascii=False),))
        db.close()
        store = Store(legacy)
        items = store.list_action_items()
        self.assertEqual([(i['task'], i['origin']) for i in items], [('舊待辦', 'manual')])
        Store(legacy)  # Re-opening must not duplicate the backfill.
        self.assertEqual(len(store.list_action_items()), 1)


if __name__ == '__main__':
    unittest.main()
