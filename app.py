"""A module: meeting text capture. Python standard library only."""
import argparse
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAX_BODY = 1_000_000


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS meetings (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, transcript TEXT NOT NULL,
                revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')

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
                return
            if db.execute('SELECT 1 FROM meetings WHERE id=?', (meeting_id,)).fetchone():
                raise Conflict('此會議已被更新。請載入最新版後再確認是否刪除。')
            raise KeyError(meeting_id)


class Conflict(Exception):
    pass


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

        def do_GET(self):
            path = self.path.split('?', 1)[0]
            if path == '/api/meetings':
                return self.reply(200, {'meetings': store.list()})
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
            expected = '/api/meetings/' if update else '/api/meetings'
            if (update and not self.path.startswith(expected)) or (not update and self.path != expected):
                return self.reply(404, {'error': '找不到 API。'})
            # This local API accepts same-origin JSON requests only.
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
                meeting_id = self.path.removeprefix(expected) if update else None
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
            self.write_meeting()

        def do_PUT(self):
            self.write_meeting()

        def do_DELETE(self):
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
