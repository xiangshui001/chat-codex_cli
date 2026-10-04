"""Versioned, private status projection; no task or database migration/replay."""
from datetime import datetime, timedelta, timezone
import json
import logging
import os
import uuid

from .mvp0_runner import utc_now


class ListenerStatus:
    def __init__(self, config):
        self.config = config
        self.path = config.state_dir / 'listener-status.json'
        self.value = {'version': 1, 'owner': config.owner, 'host_id': config.host_id,
                      'workspace_root': str(config.workspace_root), 'phase': 'starting',
                      'last_poll_started_at': None, 'last_poll_finished_at': None,
                      'next_poll_at': None, 'repository_count': 0, 'checked_repositories': 0,
                      'rejected': [], 'rejections_truncated': False, 'error_count': 0,
                      'last_error': None}

    def update(self, **values):
        self.value.update(values, updated_at=utc_now())
        temporary = self.path.with_name('.listener-status-' + str(uuid.uuid4()))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with temporary.open('x', encoding='utf-8') as stream:
                os.chmod(temporary, 0o600)
                json.dump(self.value, stream, ensure_ascii=False)
            os.replace(temporary, self.path)
        except OSError:
            logging.getLogger('codex-v2-mvp2').warning('listener_status_unavailable')
        finally:
            temporary.unlink(missing_ok=True)

    def begin(self):
        self.rejected = []
        self.rejections_truncated = False
        self.update(phase='checking', last_poll_started_at=utc_now(), next_poll_at=None,
                    repository_count=0, checked_repositories=0, error_count=0, last_error=None)

    def reject(self, source, issue, reason, task=None, registry=None):
        if len(self.rejected) >= 50:
            self.rejections_truncated = True
            return
        entry = {'repo': source.full_name, 'issue_number': issue['number'], 'reason': reason}
        if task is not None and reason in {'model_not_allowed', 'effort_not_supported', 'provider_not_allowed'}:
            chosen = task.models['primary']
            # A GPT-led task may be rejected because of a collaborator selection.
            for candidate in [chosen, *task.models.get('collaborators', [])]:
                provider = registry.providers.get(candidate['provider'])
                if candidate['provider'] != 'codex' and (
                        (reason == 'provider_not_allowed' and provider is None) or
                        (provider is not None and reason == 'model_not_allowed' and candidate['model'] not in provider['models']) or
                        (provider is not None and reason == 'effort_not_supported' and candidate['effort'] not in provider['effort_map'])):
                    chosen = candidate
                    break
            entry.update(provider=chosen['provider'], model=chosen['model'], effort=chosen['effort'])
            provider = registry.providers.get(chosen['provider'])
            if provider is not None:
                matches = [m for m in provider['models'] if m.lower() == chosen['model'].lower()]
                if len(matches) == 1:
                    entry['suggested_model'] = matches[0]
                entry['allowed_efforts'] = list(provider['effort_map'])[:8]
        self.rejected.append(entry)

    def finish(self, errors=0, error=None):
        self.update(phase='blocked' if error == 'unfinished_task_requires_manual_inspection' else
                    ('error' if error or errors else 'idle'), last_poll_finished_at=utc_now(),
                    next_poll_at=(datetime.now(timezone.utc) + timedelta(seconds=self.config.poll_seconds)).isoformat(),
                    rejected=self.rejected, rejections_truncated=self.rejections_truncated,
                    error_count=errors, last_error=error)
