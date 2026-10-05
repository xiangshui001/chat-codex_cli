"""Private, task-scoped consultation results retained across MCP restarts."""
import json
import os
from pathlib import Path
import tempfile
import uuid

from .mvp0_runner import MvpError
from .process_identity import alive, identity


class ConsultationJobs:
    schema_version = 1

    def __init__(self, directory):
        self.directory = Path(directory)
        if self.directory.is_symlink():
            raise MvpError('invalid_consultation_directory')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, job_id):
        try:
            if not isinstance(job_id, str) or str(uuid.UUID(job_id)) != job_id:
                raise ValueError
        except (ValueError, AttributeError):
            raise MvpError('invalid_consultation_id') from None
        return self.directory / (job_id + '.json')

    def _write(self, job_id, payload):
        destination = self.path(job_id)
        fd, temporary = tempfile.mkstemp(dir=self.directory, prefix='.consultation-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(payload, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def start(self, job_id, result, request):
        self._write(job_id, {'version': self.schema_version, 'worker': identity(os.getpid()),
                             'request': request, 'result': result})

    def __setitem__(self, job_id, result):
        path = self.path(job_id)
        payload = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {
            'version': self.schema_version, 'worker': identity(os.getpid())}
        payload['result'] = result
        self._write(job_id, payload)

    def get(self, job_id, default=None):
        try:
            path = self.path(job_id)
        except MvpError:
            return default
        try:
            if path.is_symlink():
                raise ValueError
            payload = json.loads(path.read_text(encoding='utf-8'))
            if payload.get('version') != self.schema_version or not isinstance(payload.get('result'), dict):
                raise ValueError
        except FileNotFoundError:
            return default
        except (OSError, ValueError, AttributeError):
            return {'job_id': job_id, 'status': 'interrupted', 'error': 'consultation_record_unreadable'}
        result = dict(payload['result'])
        if result.get('status') == 'running' and not alive(payload.get('worker')):
            result.update(status='interrupted', error='consultation_outcome_unknown')
        return result

    def __getitem__(self, job_id):
        result = self.get(job_id)
        if result is None:
            raise KeyError(job_id)
        return result
