"""MVP-2 task contract. The Issue carries selections, never credentials or URLs."""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import re
import uuid

from .mvp0 import Task, fields, parse_task, read_json, text
from .mvp0_runner import MvpError
from .mvp1 import AccountConfig, REPO

TITLE_PREFIX = "[codex-v2-mvp2]"
MARKER = "/codex-v2-mvp2 run"
MODES = {"gpt", "api", "gpt-led"}
EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")


def canonical_id(value, code="invalid_session_id"):
    value = text(value, 36, code)
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError()
    except ValueError as exc:
        raise MvpError(code) from exc
    return value


def selection(value):
    fields(value, {"provider", "model", "effort"})
    for key in ("provider", "model"):
        if not NAME.fullmatch(text(value[key], 128, "invalid_" + key)):
            raise MvpError("invalid_" + key)
    if text(value["effort"], 16, "invalid_effort") not in EFFORTS:
        raise MvpError("invalid_effort")
    return dict(value)


def model_options(value, *, cli=True):
    fields(value, {"mode", "primary"}, {"collaborators"})
    if text(value["mode"], 16, "invalid_model_mode") not in MODES:
        raise MvpError("invalid_model_mode")
    primary = selection(value["primary"])
    if cli and ((value["mode"] == "api") == (primary["provider"] == "codex")):
        raise MvpError("primary_provider_mode_mismatch")
    if value["mode"] != "api" and not primary["model"].startswith("gpt-"):
        raise MvpError("gpt_model_required")
    collaborators = value.get("collaborators", [])
    if not isinstance(collaborators, list):
        raise MvpError("invalid_collaborators")
    collaborators = [selection(c) for c in collaborators]
    if (value["mode"] == "gpt-led") != bool(collaborators):
        raise MvpError("collaborators_mode_mismatch")
    if any(c["provider"] == "codex" for c in collaborators):
        raise MvpError("external_collaborator_required")
    if len({(c["provider"], c["model"], c["effort"]) for c in collaborators}) != len(collaborators):
        raise MvpError("duplicate_collaborator")
    return {"mode": value["mode"], "primary": primary, "collaborators": collaborators}


def session_options(value):
    fields(value, {"mode"}, {"id"})
    text(value["mode"], 16, "invalid_session_selection")
    if value["mode"] == "new" and "id" not in value:
        return {"mode": "new"}
    if value["mode"] == "resume" and "id" in value:
        return {"mode": "resume", "id": canonical_id(value["id"])}
    raise MvpError("invalid_session_selection")


@dataclass(frozen=True)
class DesktopConfig(AccountConfig):
    timeout_seconds: int | None = None
    hub_repo: str = ""
    models_file: Path | None = None
    config_file: Path | None = None
    max_parallel_tasks: int = 1
    full_access: bool = False
    auto_merge: bool = False
    progress_seconds: int = 900

    @classmethod
    def load(cls, path: Path):
        data = read_json(path.read_text(encoding="utf-8"))
        fields(data, {"owner", "host_id", "workspace_root", "state_dir", "hub_repo", "models_file"},
               {"poll_seconds", "timeout_seconds", "max_parallel_tasks", "full_access", "auto_merge", "progress_seconds"})
        for key in ('full_access','auto_merge'):
            if type(data.get(key,False)) is not bool:raise MvpError('invalid_' + key)
        progress = data.get('progress_seconds',900)
        if type(progress) is not int or progress < 1:raise MvpError('invalid_progress_seconds')
        parallel = data.get("max_parallel_tasks", 1)
        if type(parallel) is not int or parallel < 1:
            raise MvpError("invalid_max_parallel_tasks")
        timeout = data.get("timeout_seconds")
        if timeout is not None and (type(timeout) is not int or timeout < 1):
            raise MvpError("invalid_timeout_seconds")
        # Reuse the established path/owner validation without loosening MVP-1.
        account_keys = {"owner", "host_id", "workspace_root", "state_dir", "poll_seconds", "timeout_seconds"}
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False) as tmp:
            projection = {k: v for k, v in data.items() if k in account_keys}
            projection["timeout_seconds"] = 900
            json.dump(projection, tmp)
            tmp_path = Path(tmp.name)
        try:
            account = AccountConfig.load(tmp_path)
            account = replace(account, timeout_seconds=timeout)
        finally:
            tmp_path.unlink()
        hub = text(data["hub_repo"], 200, "invalid_hub_repo")
        if not REPO.fullmatch(hub) or hub.split("/")[0].lower() != account.owner:
            raise MvpError("invalid_hub_repo")
        models = Path(text(data["models_file"], 4096, "invalid_models_file"))
        if not models.is_absolute() or models.is_symlink() or not models.is_file():
            raise MvpError("invalid_models_file")
        models = models.resolve()
        if models.is_relative_to(account.workspace_root):
            raise MvpError("models_file_must_be_outside_workspaces")
        return cls(**account.__dict__, hub_repo=hub.lower(), models_file=models, config_file=path.resolve(),
                   max_parallel_tasks=parallel,full_access=data.get('full_access',False),
                   auto_merge=data.get('auto_merge',False),progress_seconds=progress)


@dataclass(frozen=True)
class DesktopTask(Task):
    session: dict
    models: dict


def parse_desktop_task(issue, comments, source, config):
    # Mobile-friendly owner Issue bodies are also an authorization, without UUID/SHA boilerplate.
    if str(issue.get('body','')).splitlines() and str(issue['body']).splitlines()[0].startswith('/codex run '):
        return parse_mobile_task(issue,source,config)
    # The old parser verifies authors, timestamps, IDs, base and write scopes.
    # Feed it the strict legacy projection after validating the new fields.
    matching = [c for c in comments if isinstance(c.get("body"), str)
                and c["body"].splitlines() and c["body"].splitlines()[0] == MARKER]
    if len(matching) != 1:
        raise MvpError("exactly_one_authorization_required")
    original = matching[0]
    body = text(original["body"], None, "authorization_too_large")
    payload = body.split("\n", 1)[1].strip() if "\n" in body else ""
    if payload.startswith("```"):
        match = re.fullmatch(r"```json\s*\n([\s\S]+)\n```", payload)
        if not match:
            raise MvpError("invalid_json_fence")
        payload = match[1]
    data = read_json(payload)
    fields(data, {"request_id", "host_id", "repo", "base_sha", "task", "session", "models"})
    repo = text(data["repo"], 200, "invalid_repo")
    if not REPO.fullmatch(repo) or repo.split("/")[0].lower() != config.owner:
        raise MvpError("target_owner_not_allowed")
    if source.full_name.lower() not in {repo.lower(), config.hub_repo.lower()}:
        raise MvpError("issue_source_not_allowed")
    session, models = session_options(data["session"]), model_options(data["models"])
    projection = {k: v for k, v in data.items() if k not in {"session", "models"}}
    projected_comments = [{**original, "body": MARKER + "\n" + json.dumps(projection, ensure_ascii=False)}]
    from dataclasses import replace
    task_config = replace(source.task_config(config), repo=repo)
    base = parse_task(issue, projected_comments, task_config, title_prefix=TITLE_PREFIX, marker=MARKER, remote=True)
    return DesktopTask(**{**base.__dict__, "contract_hash": hashlib.sha256(body.encode()).hexdigest()},
                       session=session, models=models)


def parse_mobile_task(issue,source,config):
    body=issue['body'];lines=body.splitlines()
    host=lines[0].removeprefix('/codex run ').strip()
    if host!=config.host_id:raise MvpError('wrong_host')
    if str((issue.get('user') or {}).get('login','')).lower()!=config.owner:raise MvpError('issue_author_not_allowed')
    if issue.get('state')!='open' or 'pull_request' in issue:raise MvpError('not_mvp_issue')
    settings={};prompt=[];header=True
    for line in lines[1:]:
        match=re.fullmatch(r'(repo|model|effort|mode|provider|session|paths|collaborators)\s*:\s*(.+)',line,flags=re.I)
        if header and match:settings[match[1].lower()]=match[2].strip()
        else:
            if line.strip():header=False
            prompt.append(line)
    repo=settings.get('repo',source.full_name).lower()
    if not REPO.fullmatch(repo) or repo.split('/')[0]!=config.owner:raise MvpError('target_owner_not_allowed')
    if source.full_name.lower() not in {repo,config.hub_repo.lower()}:raise MvpError('issue_source_not_allowed')
    mode=settings.get('mode','gpt')
    provider=settings.get('provider','codex' if mode!='api' else 'workbuddy')
    model_data={'mode':mode,'primary':{'provider':provider,'model':settings.get('model','gpt-6.1-sol'),'effort':settings.get('effort','medium')}}
    if 'collaborators' in settings:model_data['collaborators']=read_json(settings['collaborators'])
    models=model_options(model_data)
    session=session_options({'mode':'new'} if settings.get('session','new')=='new' else {'mode':'resume','id':settings['session']})
    from .mvp0 import write_path
    scopes=tuple('.' if p.strip() in {'.','./','*','/'} else write_path(p.strip(),remote=True) for p in settings.get('paths','.').split(','))
    prompt=text('\n'.join(prompt).strip(),None,'invalid_prompt')
    # Resolve the commit on the owning execution host immediately before freezing the claim.
    return DesktopTask(str(uuid.uuid5(uuid.NAMESPACE_URL,f"https://github.com/{source.full_name}/issues/{issue['number']}")),
        host,repo,'',prompt,scopes,issue['id'],hashlib.sha256(body.encode()).hexdigest(),session,models)
