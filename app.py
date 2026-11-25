"""A module: meeting text capture. Python standard library only."""
import argparse
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from difflib import SequenceMatcher
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from summarizer import analyze_transcript, test_llm_connection

ROOT = Path(__file__).resolve().parent
MAX_BODY = 1_000_000


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS meetings (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, transcript TEXT NOT NULL,
                revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS summaries (
                meeting_id TEXT PRIMARY KEY,
                source_revision INTEGER NOT NULL,
                summary TEXT NOT NULL,
                decisions TEXT NOT NULL,
                action_items TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT 'heuristic',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE)''')
            try:
                db.execute("ALTER TABLE summaries ADD COLUMN provider TEXT DEFAULT 'heuristic'")
            except sqlite3.OperationalError:
                pass
            # Module D: to-dos get stable ids so status survives summary regeneration.
            db.execute('''CREATE TABLE IF NOT EXISTS action_items (
                id TEXT PRIMARY KEY,
                meeting_id TEXT NOT NULL,
                assignee TEXT NOT NULL,
                task TEXT NOT NULL,
                due TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                origin TEXT NOT NULL DEFAULT 'ai',
                missing_from_source INTEGER NOT NULL DEFAULT 0,
                position INTEGER NOT NULL DEFAULT 0,
                done_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE)''')
            self._backfill_action_items(db)

    def _backfill_action_items(self, db):
        """Copy to-dos from summaries saved before the action_items table existed."""
        rows = db.execute('''SELECT meeting_id, action_items, provider, updated_at FROM summaries
            WHERE meeting_id NOT IN (SELECT DISTINCT meeting_id FROM action_items)''').fetchall()
        for row in rows:
            try:
                items = json.loads(row['action_items'])
            except (TypeError, ValueError):
                continue
            origin = 'manual' if row['provider'] in ('manual', '人工微調') else 'ai'
            for position, item in enumerate(_clean_items(items)):
                db.execute('''INSERT INTO action_items (id, meeting_id, assignee, task, due, origin,
                    position, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)''',
                    (str(uuid.uuid4()), row['meeting_id'], item['assignee'], item['task'], item['due'],
                     origin, position, row['updated_at'], row['updated_at']))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def list(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                'SELECT id,title,revision,created_at,updated_at FROM meetings ORDER BY updated_at DESC,id')]

    def get(self, meeting_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM meetings WHERE id=?', (meeting_id,)).fetchone()
        return dict(row) if row else None

    def save(self, data, meeting_id=None):
        if not isinstance(data, dict):
            raise ValueError('請提供 JSON 物件。')
        title, transcript = data.get('title'), data.get('transcript')
        if not isinstance(title, str) or not title.strip():
            raise ValueError('請填寫會議標題。')
        if len(title.strip()) > 120:
            raise ValueError('標題最多 120 字。')
        if not isinstance(transcript, str) or not transcript.strip():
            raise ValueError('請貼上會議內容。')
        if len(transcript) > 100_000:
            raise ValueError('會議內容最多 100,000 字。')
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            if meeting_id:
                revision = data.get('revision')
                if type(revision) is not int or revision < 1:
                    raise ValueError('更新會議時需提供正確的 revision。')
                result = db.execute('''UPDATE meetings SET title=?,transcript=?,revision=revision+1,
                    updated_at=? WHERE id=? AND revision=?''',
                    (title.strip(), transcript, now, meeting_id, revision))
                if result.rowcount == 0:
                    exists = db.execute('SELECT 1 FROM meetings WHERE id=?', (meeting_id,)).fetchone()
                    if not exists:
                        raise KeyError(meeting_id)
                    raise Conflict('此會議已被更新。請先另存輸入內容，再重新載入最新版本。')
            else:
                meeting_id = str(uuid.uuid4())
                db.execute('INSERT INTO meetings VALUES (?,?,?,?,?,?)',
                           (meeting_id, title.strip(), transcript, 1, now, now))
            row = db.execute('SELECT * FROM meetings WHERE id=?', (meeting_id,)).fetchone()
            return dict(row)

    def delete(self, meeting_id, data):
        revision = data.get('revision') if isinstance(data, dict) else None
        if type(revision) is not int or revision < 1:
            raise ValueError('刪除會議時需提供正確的 revision。')
        with self.connect() as db:
            result = db.execute('DELETE FROM meetings WHERE id=? AND revision=?', (meeting_id, revision))
            if result.rowcount:
                db.execute('DELETE FROM summaries WHERE meeting_id=?', (meeting_id,))
                db.execute('DELETE FROM action_items WHERE meeting_id=?', (meeting_id,))
                return
            if db.execute('SELECT 1 FROM meetings WHERE id=?', (meeting_id,)).fetchone():
                raise Conflict('此會議已被更新。請載入最新版後再確認是否刪除。')
            raise KeyError(meeting_id)

    def get_summary(self, meeting_id):
        with self.connect() as db:
            meeting = db.execute('SELECT revision FROM meetings WHERE id=?', (meeting_id,)).fetchone()
            if not meeting:
                return None
            row = db.execute('SELECT * FROM summaries WHERE meeting_id=?', (meeting_id,)).fetchone()
            if not row:
                return None
            return self._summary_response(db, row, meeting)

    def _summary_response(self, db, row, meeting):
        data = dict(row)
        data['is_stale'] = (data['source_revision'] < meeting['revision'])
        data['decisions'] = json.loads(data['decisions'])
        data['action_items'] = [_item_response(r) for r in db.execute(
            'SELECT * FROM action_items WHERE meeting_id=? ORDER BY position, created_at',
            (data['meeting_id'],))]
        data['provider'] = data.get('provider') or 'heuristic'
        return data

    def _reconcile_action_items(self, db, meeting_id, new_items, manual, now):
        """Merge a freshly generated or edited list into stored to-dos.

        Matching order: explicit id (manual edits), then same assignee + task after
        normalisation, then same assignee + similar task. Matched items keep their id
        and status. AI output never overwrites a manually edited item, and items the
        AI no longer finds are flagged for a person to keep or remove, not deleted.
        A manual edit is a human decision, so items left out of it are deleted.
        """
        existing = [dict(r) for r in db.execute(
            'SELECT * FROM action_items WHERE meeting_id=?', (meeting_id,))]
        unclaimed = {row['id']: row for row in existing}
        for position, item in enumerate(_clean_items(new_items)):
            match = _find_match(item, unclaimed)
            if match is None:
                db.execute('''INSERT INTO action_items (id, meeting_id, assignee, task, due, origin,
                    position, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)''',
                    (str(uuid.uuid4()), meeting_id, item['assignee'], item['task'], item['due'],
                     'manual' if manual else 'ai', position, now, now))
                continue
            del unclaimed[match['id']]
            content = (item['assignee'], item['task'], item['due'])
            changed = content != (match['assignee'], match['task'], match['due'])
            if manual:
                origin = 'manual' if changed else match['origin']
            elif match['origin'] == 'manual':
                content, origin = (match['assignee'], match['task'], match['due']), 'manual'
            else:
                origin = 'ai'
            db.execute('''UPDATE action_items SET assignee=?, task=?, due=?, origin=?,
                missing_from_source=0, position=?, updated_at=? WHERE id=?''',
                (*content, origin, position, now, match['id']))
        for row in unclaimed.values():
            if manual:
                db.execute('DELETE FROM action_items WHERE id=?', (row['id'],))
            else:
                db.execute('UPDATE action_items SET missing_from_source=1, updated_at=? WHERE id=?',
                           (now, row['id']))

    def list_action_items(self, assignee=None, status=None):
        query = '''SELECT a.*, m.title AS meeting_title,
                (s.source_revision < m.revision) AS summary_stale
            FROM action_items a
            JOIN meetings m ON m.id = a.meeting_id
            LEFT JOIN summaries s ON s.meeting_id = a.meeting_id'''
        clauses, params = [], []
        if assignee:
            clauses.append('a.assignee = ?')
            params.append(assignee)
        if status:
            if status not in ACTION_STATUSES:
                raise ValueError('status 只能是 open 或 done。')
            clauses.append('a.status = ?')
            params.append(status)
        if clauses:
            query += ' WHERE ' + ' AND '.join(clauses)
        query += " ORDER BY a.status = 'done', m.updated_at DESC, a.position, a.created_at"
        with self.connect() as db:
            return [_item_response(row, with_meeting=True) for row in db.execute(query, params)]

    def update_action_item(self, item_id, data):
        if not isinstance(data, dict):
            raise ValueError('請提供 JSON 物件。')
        status, keep = data.get('status'), data.get('keep')
        if status is None and keep is None:
            raise ValueError('請提供 status 或 keep。')
        if status is not None and status not in ACTION_STATUSES:
            raise ValueError('status 只能是 open 或 done。')
        if keep is not None and keep is not True:
            raise ValueError('keep 只能是 true；要移除請使用 DELETE。')
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            row = db.execute('SELECT * FROM action_items WHERE id=?', (item_id,)).fetchone()
            if not row:
                raise KeyError(item_id)
            if status is not None and status != row['status']:
                db.execute('UPDATE action_items SET status=?, done_at=?, updated_at=? WHERE id=?',
                           (status, now if status == 'done' else None, now, item_id))
            if keep:
                db.execute('UPDATE action_items SET missing_from_source=0, updated_at=? WHERE id=?',
                           (now, item_id))
            return _item_response(db.execute('SELECT * FROM action_items WHERE id=?', (item_id,)).fetchone())

    def delete_action_item(self, item_id):
        with self.connect() as db:
            if not db.execute('DELETE FROM action_items WHERE id=?', (item_id,)).rowcount:
                raise KeyError(item_id)

    def save_summary(self, meeting_id, source_revision, summary, decisions, action_items, provider='heuristic', manual=False):
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError('摘要內容不能為空。')
        if not isinstance(decisions, list):
            raise ValueError('決策事項需為列表。')
        if not isinstance(action_items, list):
            raise ValueError('行動項目需為列表。')
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            meeting = db.execute('SELECT revision FROM meetings WHERE id=?', (meeting_id,)).fetchone()
            if not meeting:
                raise KeyError(meeting_id)
            db.execute('''INSERT INTO summaries (meeting_id, source_revision, summary, decisions, action_items, provider, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(meeting_id) DO UPDATE SET
                    source_revision=excluded.source_revision,
                    summary=excluded.summary,
                    decisions=excluded.decisions,
                    action_items=excluded.action_items,
                    provider=excluded.provider,
                    updated_at=excluded.updated_at
            ''', (
                meeting_id,
                source_revision,
                summary.strip(),
                json.dumps(decisions, ensure_ascii=False),
                json.dumps(action_items, ensure_ascii=False),
                provider,
                now,
                now
            ))
            self._reconcile_action_items(db, meeting_id, action_items, manual, now)
            row = db.execute('SELECT * FROM summaries WHERE meeting_id=?', (meeting_id,)).fetchone()
            return self._summary_response(db, row, meeting)


class Conflict(Exception):
    pass


ACTION_STATUSES = ('open', 'done')
MATCH_THRESHOLD = 0.6


def _clean_items(items):
    """Normalise raw action items from B (AI output or the edit form)."""
    cleaned = []
    for item in items:
        if not isinstance(item, dict):
            continue
        task = str(item.get('task') or '').strip()
        if not task:
            continue
        assignee = str(item.get('assignee') or '').strip() or '未指派'
        due = item.get('due')
        due = str(due).strip() if due is not None and str(due).strip() else None
        cleaned.append({'id': item.get('id'), 'assignee': assignee, 'task': task, 'due': due})
    return cleaned


def _norm(text):
    return re.sub(r'[\s，。、；：,.;:!?！？「」"\'()（）]+', '', text or '').lower()


def _find_match(item, unclaimed):
    if item['id'] and item['id'] in unclaimed:
        return unclaimed[item['id']]
    assignee, task = _norm(item['assignee']), _norm(item['task'])
    same_person = [row for row in unclaimed.values() if _norm(row['assignee']) == assignee]
    for row in same_person:
        if _norm(row['task']) == task:
            return row
    best, best_score = None, MATCH_THRESHOLD
    for row in same_person:
        score = SequenceMatcher(None, task, _norm(row['task'])).ratio()
        if score >= best_score:
            best, best_score = row, score
    return best


def _item_response(row, with_meeting=False):
    data = {key: row[key] for key in ('id', 'meeting_id', 'assignee', 'task', 'due', 'status',
                                      'origin', 'done_at', 'created_at', 'updated_at')}
    data['missing_from_source'] = bool(row['missing_from_source'])
    if with_meeting:
        data['meeting_title'] = row['meeting_title']
        data['summary_stale'] = bool(row['summary_stale'])
    return data


def handler_for(store):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, data):
            body = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def cross_origin(self):
            origin = self.headers.get('Origin')
            return bool(origin) and origin != 'http://' + self.headers.get('Host', '')

        def action_item(self):
            """PUT / DELETE /api/action-items/{id} (module D)."""
            item_id = self.path.split('?', 1)[0].removeprefix('/api/action-items/')
            if not item_id or '/' in item_id:
                return self.reply(404, {'error': '找不到 API。'})
            if self.cross_origin():
                return self.reply(403, {'error': '不接受跨來源請求。'})
            try:
                if self.command == 'DELETE':
                    store.delete_action_item(item_id)
                    return self.reply(200, {'id': item_id})
                if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
                    return self.reply(415, {'error': '請使用 application/json。'})
                length = int(self.headers.get('Content-Length', '0'))
                if length < 1 or length > MAX_BODY:
                    return self.reply(413, {'error': '請求內容過大或為空。'})
                data = json.loads(self.rfile.read(length).decode('utf-8'))
                return self.reply(200, store.update_action_item(item_id, data))
            except KeyError:
                return self.reply(404, {'error': '找不到待辦事項。'})
            except (ValueError, UnicodeDecodeError) as error:
                return self.reply(400, {'error': str(error)})

        def do_GET(self):
            path = self.path.split('?', 1)[0]
            if path == '/api/action-items':
                query = parse_qs(urlsplit(self.path).query)
                try:
                    items = store.list_action_items(
                        assignee=query.get('assignee', [None])[0],
                        status=query.get('status', [None])[0])
                except ValueError as error:
                    return self.reply(400, {'error': str(error)})
                return self.reply(200, {'items': items})
            if path == '/api/meetings':
                return self.reply(200, {'meetings': store.list()})
            if path.startswith('/api/meetings/') and path.endswith('/summary'):
                meeting_id = path.removeprefix('/api/meetings/').removesuffix('/summary')
                meeting = store.get(meeting_id)
                if not meeting:
                    return self.reply(404, {'error': '找不到會議。'})
                summary = store.get_summary(meeting_id)
                if not summary:
                    return self.reply(404, {'error': '此會議尚未產生 AI 摘要。'})
                return self.reply(200, summary)
            if path.startswith('/api/meetings/'):
                meeting = store.get(path.removeprefix('/api/meetings/'))
                return self.reply(200, meeting) if meeting else self.reply(404, {'error': '找不到會議。'})
            files = {'/': ('index.html', 'text/html; charset=utf-8'),
                     '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                     '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if path not in files:
                return self.reply(404, {'error': '找不到頁面。'})
            filename, content_type = files[path]
            body = (ROOT / 'static' / filename).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def write_meeting(self):
            update = self.command != 'POST'
            path = self.path.split('?', 1)[0]
            expected = '/api/meetings/' if update else '/api/meetings'
            if (update and not path.startswith(expected)) or (not update and path != expected):
                return self.reply(404, {'error': '找不到 API。'})
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + self.headers.get('Host', ''):
                return self.reply(403, {'error': '不接受跨來源請求。'})
            if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
                return self.reply(415, {'error': '請使用 application/json。'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length < 1 or length > MAX_BODY:
                    return self.reply(413, {'error': '請求內容過大或為空。'})
                data = json.loads(self.rfile.read(length).decode('utf-8'))
                meeting_id = path.removeprefix(expected) if update else None
                if update and not meeting_id:
                    return self.reply(404, {'error': '找不到會議。'})
                if self.command == 'DELETE':
                    store.delete(meeting_id, data)
                    return self.reply(200, {'id': meeting_id})
                meeting = store.save(data, meeting_id)
                return self.reply(200 if update else 201, meeting)
            except Conflict as error:
                return self.reply(409, {'error': str(error)})
            except KeyError:
                return self.reply(404, {'error': '找不到會議。'})
            except (ValueError, UnicodeDecodeError) as error:
                return self.reply(400, {'error': str(error)})

        def do_POST(self):
            path = self.path.split('?', 1)[0]
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + self.headers.get('Host', ''):
                return self.reply(403, {'error': '不接受跨來源請求。'})

            if path == '/api/test-llm':
                length = int(self.headers.get('Content-Length', '0'))
                try:
                    data = json.loads(self.rfile.read(length).decode('utf-8')) if length > 0 else {}
                    res = test_llm_connection(data.get('provider'), data.get('api_key'), data.get('model'))
                    return self.reply(200, res)
                except Exception as err:
                    return self.reply(400, {'error': str(err)})

            if path.startswith('/api/meetings/') and path.endswith('/summary'):
                meeting_id = path.removeprefix('/api/meetings/').removesuffix('/summary')
                meeting = store.get(meeting_id)
                if not meeting:
                    return self.reply(404, {'error': '找不到會議。'})
                if not meeting['transcript'].strip():
                    return self.reply(400, {'error': '會議內容為空，無法產生摘要。'})

                req_data = {}
                length = int(self.headers.get('Content-Length', '0'))
                if length > 0 and 'application/json' in self.headers.get('Content-Type', ''):
                    try:
                        req_data = json.loads(self.rfile.read(length).decode('utf-8'))
                    except Exception:
                        req_data = {}

                provider = req_data.get('provider') or self.headers.get('X-Provider')
                api_key = req_data.get('api_key') or self.headers.get('X-API-Key')
                model = req_data.get('model') or self.headers.get('X-Model')

                try:
                    analysis = analyze_transcript(
                        meeting['transcript'],
                        meeting['title'],
                        provider=provider,
                        api_key=api_key,
                        model=model
                    )
                    saved = store.save_summary(
                        meeting_id,
                        meeting['revision'],
                        analysis['summary'],
                        analysis['decisions'],
                        analysis['action_items'],
                        provider=analysis.get('provider', 'heuristic')
                    )
                    return self.reply(201, saved)
                except Exception as error:
                    return self.reply(400, {'error': str(error)})

            self.write_meeting()

        def do_PUT(self):
            path = self.path.split('?', 1)[0]
            if path.startswith('/api/action-items/'):
                return self.action_item()
            if path.startswith('/api/meetings/') and path.endswith('/summary'):
                meeting_id = path.removeprefix('/api/meetings/').removesuffix('/summary')
                origin = self.headers.get('Origin')
                if origin and origin != 'http://' + self.headers.get('Host', ''):
                    return self.reply(403, {'error': '不接受跨來源請求。'})
                meeting = store.get(meeting_id)
                if not meeting:
                    return self.reply(404, {'error': '找不到會議。'})
                if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
                    return self.reply(415, {'error': '請使用 application/json。'})
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if length < 1 or length > MAX_BODY:
                        return self.reply(413, {'error': '請求內容過大或為空。'})
                    data = json.loads(self.rfile.read(length).decode('utf-8'))
                    if not isinstance(data, dict):
                        return self.reply(400, {'error': '請提供 JSON 物件。'})
                    saved = store.save_summary(
                        meeting_id,
                        meeting['revision'],
                        data.get('summary', ''),
                        data.get('decisions', []),
                        data.get('action_items', []),
                        provider=data.get('provider', 'manual'),
                        manual=True
                    )
                    return self.reply(200, saved)
                except (ValueError, KeyError) as error:
                    return self.reply(400, {'error': str(error)})
            self.write_meeting()

        def do_DELETE(self):
            if self.path.split('?', 1)[0].startswith('/api/action-items/'):
                return self.action_item()
            self.write_meeting()

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--db', type=Path, default=ROOT / 'data' / 'meetings.sqlite3')
    args = parser.parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(Store(args.db)))
    print(f'會議輸入：http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
