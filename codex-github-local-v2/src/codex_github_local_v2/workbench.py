"""Loopback-only, read-only projection of real MVP-1 / MVP-2 state and JSONL."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
from urllib.parse import unquote, urlsplit
import uuid

from .mvp1 import AccountConfig


def clean(value, limit=8000):
    text = str(value or '')
    text = re.sub(r'\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{12,})', '[REDACTED]', text)
    text = re.sub(r'(?i)(bearer\s+|(?:api[_-]?key|access[_-]?token|password|secret)\s*[=:]\s*)[^\s,;]+', r'\1[REDACTED]', text)
    return text[:limit] + ('\n…已截断' if len(text) > limit else '')


def tail(path: Path, size=512 * 1024):
    if not path.is_file() or path.is_symlink():
        return '', False
    with path.open('rb') as stream:
        length = stream.seek(0, 2)
        stream.seek(max(0, length - size))
        data = stream.read(size)
    truncated = length > size
    if truncated:
        data = data.partition(b'\n')[2]
    return data.decode('utf-8', errors='replace'), truncated


def progress(path: Path):
    raw, truncated = tail(path)
    items, malformed = [], 0
    for line in raw.splitlines():
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError()
        except ValueError:
            malformed += 1  # A writer's last partial line is retried on the next refresh.
            continue
        kind = event.get('type')
        item = event.get('item')
        if kind in ('item.started', 'item.updated', 'item.completed') and isinstance(item, dict):
            typ = item.get('type')
            entry = {'id': 'item-' + str(item.get('id', len(items))), 'kind': typ,
                     'status': clean(item.get('status') or kind.split('.')[-1], 60)}
            if typ == 'command_execution':
                entry.update(title=clean(item.get('command'), 2000), text=clean(item.get('aggregated_output')),
                             exit_code=item.get('exit_code') if type(item.get('exit_code')) is int else None)
            elif typ == 'agent_message':
                entry.update(title='Codex 回复', text=clean(item.get('text')))
            elif typ == 'file_change':
                changes = item.get('changes') or []
                entry.update(title='文件修改', text=clean('\n'.join(str(x.get('path', '')) for x in changes if isinstance(x, dict))))
            elif typ == 'mcp_tool_call':
                entry.update(title='工具调用', text=clean(str(item.get('server', '')) + ' / ' + str(item.get('tool', '')), 300))
            else:
                continue  # Never expose reasoning, arbitrary tool payloads or unknown event fields.
            previous = next((i for i, x in enumerate(items) if x['id'] == entry['id']), None)
            if previous is None:
                items.append(entry)
            else:
                items[previous] = entry
        elif kind in ('thread.started', 'turn.started', 'turn.completed', 'turn.failed', 'error'):
            items.append({'id': f'event-{len(items)}', 'kind': kind, 'status': kind,
                          'title': {'thread.started': 'Codex 会话已创建', 'turn.started': 'Codex 开始处理',
                                    'turn.completed': 'Codex 本轮完成', 'turn.failed': 'Codex 本轮失败',
                                    'error': 'Codex 报告错误'}[kind],
                          'text': clean(event.get('message'), 1000) if kind == 'error' else ''})
    return {'items': items[-150:], 'truncated': truncated or len(items) > 150,
            'partial_lines': malformed}


class Reader:
    database_name = 'mvp1.sqlite3'
    schema_version = 2
    source = 'local-mvp1'
    task_select = 'SELECT * FROM tasks'
    def __init__(self, config: AccountConfig):
        self.config = config

    def connect(self):
        path = self.config.state_dir / self.database_name
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        try:
            if db.execute('PRAGMA user_version').fetchone()[0] != self.schema_version:
                raise ValueError('Unsupported state schema')
            binding = db.execute('SELECT owner,host_id,workspace_root FROM settings WHERE id=1').fetchone()
            if binding is None or tuple(binding) != (self.config.owner, self.config.host_id, str(self.config.workspace_root)):
                raise ValueError('State binding mismatch')
        except Exception:
            db.close()
            raise
        return db

    def listener(self):
        if os.name != 'posix':
            return 'unknown'
        import fcntl
        try:
            with (self.config.state_dir / 'poller.lock').open('rb') as stream:
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return 'running'
                fcntl.flock(stream, fcntl.LOCK_UN)
                return 'stopped'
        except FileNotFoundError:
            return 'stopped'

    @staticmethod
    def task(row):
        keys = ('request_id', 'repo', 'issue_number', 'state', 'created_at', 'started_at',
                'finished_at', 'exit_code', 'cli_version', 'diff_nonempty', 'receipt_comment_id')
        value = {key: row[key] for key in keys}
        value.update(prompt=clean(row['prompt']), summary=clean(row['summary']), error=clean(row['error']),
                     issue_url=f"https://github.com/{row['repo']}/issues/{row['issue_number']}")
        return value

    def overview(self):
        db = self.connect()
        try:
            db.execute('BEGIN')
            counts = dict(db.execute('SELECT state,COUNT(*) FROM tasks GROUP BY state'))
            tasks = [self.task(r) for r in db.execute(self.task_select + ' ORDER BY tasks.id DESC LIMIT 100')]
        finally:
            db.close()
        return {'source': self.source, 'observed_at': datetime.now(timezone.utc).isoformat(),
                'host_id': self.config.host_id, 'owner': self.config.owner, 'listener': self.listener(),
                'counts': counts, 'tasks': tasks, 'limit': 100}

    def detail(self, request_id):
        if str(uuid.UUID(request_id)) != request_id:
            raise ValueError('Invalid request ID')
        db = self.connect()
        try:
            db.execute('BEGIN')
            row = db.execute(self.task_select + ' WHERE tasks.request_id=?', (request_id,)).fetchone()
            if row is None:
                raise KeyError(request_id)
            result = self.task(row)
            result.update(write_paths=json.loads(row['write_paths']), cwd=row['cwd'],
                          events=[{'kind': r['kind'], 'at': r['at']} for r in db.execute(
                              'SELECT kind,at FROM events WHERE task_id=? ORDER BY id LIMIT 500', (row['id'],))])
            repository_id = row['target_id'] if self.schema_version == 3 else row['repository_id']
            diff_base = row['base_sha'] if self.schema_version == 3 else 'HEAD'
        finally:
            db.close()
        evidence = self.config.state_dir / 'runs' / request_id
        if evidence.is_symlink() or not evidence.resolve().is_relative_to(self.config.state_dir.resolve()):
            raise ValueError('Invalid evidence path')
        result['progress'] = progress(evidence / 'stdout.jsonl')
        stderr, truncated = tail(evidence / 'stderr.log', 8192)
        result['stderr'] = clean(stderr)
        result['stderr_truncated'] = truncated
        workspace = self.config.workspace_root / str(repository_id) / request_id
        result.update(files=[], files_error=None)
        if (workspace.is_symlink() or not workspace.resolve().is_relative_to(self.config.workspace_root.resolve())
                or (result['cwd'] and Path(result['cwd']) != workspace)):
            result['cwd'] = None
            result['files_error'] = '工作目录不符合登记范围'
        elif workspace.is_dir():
            try:
                def git(*args):
                    return subprocess.run(['git', '--no-optional-locks', '-C', str(workspace), *args],
                        check=True, capture_output=True, timeout=3).stdout.decode('utf-8', errors='replace')
                files = set(git('diff', '--name-only', '--no-renames', '-z', diff_base, '--').split('\0'))
                files.update(git('ls-files', '--others', '--exclude-standard', '-z').split('\0'))
                result['files'] = [clean(x, 500) for x in sorted(files - {''})][:500]
            except (OSError, subprocess.SubprocessError):
                result['files_error'] = '暂时无法读取 Git 文件变化'
        return result


class DesktopReader(Reader):
    database_name = 'mvp2.sqlite3'
    schema_version = 3
    source = 'local-mvp2'
    task_select = 'SELECT tasks.*,deliveries.* FROM tasks JOIN deliveries ON deliveries.task_id=tasks.id'

    @staticmethod
    def task(row):
        value = Reader.task(row)
        options = json.loads(row['options_json'])
        value.update(issue_url=f"https://github.com/{row['source_repo']}/issues/{row['issue_number']}",
                     session_id=row['session_id'], mode=options['models']['mode'],
                     model=options['models']['primary']['model'], effort=options['models']['primary']['effort'],
                     pr_url=row['pr_url'], commit_sha=row['commit_sha'], publication_state=row['publication_state'])
        return value


def create_server(reader: Reader, dist: Path, port: int):
    dist = dist.resolve()
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(dist), **kwargs)

        def log_message(self, *_):
            pass

        def end_headers(self):
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            super().end_headers()

        def reply(self, code, value):
            data = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def allowed(self):
            host = self.headers.get('Host', '')
            return host in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'} and (
                not self.headers.get('Origin') or self.headers['Origin'] == 'http://' + host)

        def do_GET(self):
            if not self.allowed():
                return self.reply(403, {'error': '仅允许本机同源访问'})
            path = unquote(urlsplit(self.path).path)
            if path.startswith('/api/'):
                if self.headers.get('X-Chat-Codex-Local') != '1':
                    return self.reply(403, {'error': '缺少本机请求标记'})
                try:
                    if path == '/api/mvp1/overview':
                        data = reader.overview()
                    elif path.startswith('/api/mvp1/tasks/'):
                        data = reader.detail(path.removeprefix('/api/mvp1/tasks/'))
                    else:
                        return self.reply(404, {'error': '未知接口'})
                    return self.reply(200, data)
                except (KeyError, ValueError):
                    return self.reply(404, {'error': '任务不存在或状态不匹配'})
                except (OSError, sqlite3.Error):
                    return self.reply(503, {'error': '本机记录暂不可读；不会显示模拟数据'})
            if path == '/' and not urlsplit(self.path).query:
                self.send_response(302)
                self.send_header('Location', '/?view=live')
                return self.end_headers()
            target = (dist / path.lstrip('/')).resolve()
            if path == '/':
                self.path = '/index.html'
                target = dist / 'index.html'
            if not target.is_relative_to(dist) or not target.is_file() or any(p.startswith('.') for p in Path(path).parts if p not in ('/', '')):
                return self.reply(404, {'error': '文件不存在'})
            return super().do_GET()

        def do_POST(self):
            self.reply(405, {'error': '工作台只读；请通过 GitHub 授权任务'})

        do_PUT = do_DELETE = do_PATCH = do_POST
        do_HEAD = do_POST

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--dist', required=True, type=Path)
    parser.add_argument('--port', default=8791, type=int)
    parser.add_argument('--protocol', choices=('mvp1', 'mvp2'), default='mvp2')
    args = parser.parse_args(argv)
    if not (args.dist / 'index.html').is_file():
        parser.error('Build web/app first (npm run build)')
    if args.protocol == 'mvp2':
        from .mvp2_contract import DesktopConfig
        reader = DesktopReader(DesktopConfig.load(args.config))
    else:
        reader = Reader(AccountConfig.load(args.config))
    reader.overview()  # Refuse a wrong database before opening the server.
    with create_server(reader, args.dist, args.port) as server:
        print(f'本机真实任务工作台：http://127.0.0.1:{server.server_port}/?view=live', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
