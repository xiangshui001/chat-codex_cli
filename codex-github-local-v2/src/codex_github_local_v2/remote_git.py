"""Disk-backed Git operations that remain cancellable without a timeout budget."""
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from .mvp0 import Workspace
from .mvp0_runner import CodexRunner, MvpError, utc_now
from .process_identity import identity


def run_remote_git(cwd, *args, pulse=lambda: None, evidence=None, record=lambda *_: None):
    folder=Path(evidence or Path(cwd)/'.git'/'codex-operations')/str(uuid.uuid4())
    folder.mkdir(parents=True,mode=0o700)
    operation=next((a for a in args if a in {'clone','checkout','status','commit','push','fetch','diff','add','ls-remote','rev-parse','remote','cat-file','symbolic-ref','ls-files','merge-base','show','rev-list'}),'operation')
    audit={'operation':operation,'argv':list(args),'cwd':str(cwd),'started_at':utc_now()}
    proc=None
    record('remote_git_started',{'operation':operation})
    try:
        with (folder/'stdout').open('wb') as out,(folder/'stderr').open('wb') as err:
            proc=subprocess.Popen(['git','-C',str(cwd),*args],stdout=out,stderr=err,stdin=subprocess.DEVNULL,start_new_session=True)
            audit['pid']=proc.pid
            audit['lease']=identity(proc.pid)
            (folder/'execution.json').write_text(json.dumps(audit),encoding='utf-8')
            while proc.poll() is None:
                pulse();time.sleep(.2)
        if proc.returncode:
            # The complete diagnostic stays private; the Issue receives the operation and error category.
            raise MvpError('workspace_git_'+operation+'_failed')
        return (folder/'stdout').read_text(encoding='utf-8',errors='replace').rstrip('\r\n')
    except OSError as exc:
        raise MvpError('workspace_git_'+operation+'_failed') from exc
    finally:
        if proc is not None:
            CodexRunner._stop_group(proc)
            audit.update(exit_code=proc.returncode,cleanup='process_group_terminated')
        audit['finished_at']=utc_now()
        (folder/'execution.json').write_text(json.dumps(audit),encoding='utf-8')
        record('remote_git_finished',{'operation':operation,'exit_code':audit.get('exit_code')})


class RemoteWorkspace(Workspace):
    def __init__(self,config,pulse=lambda:None,evidence=None,record=lambda *_:None):
        super().__init__(config)
        self.pulse,self.evidence,self.record=pulse,evidence,record

    def git(self,*args):
        return run_remote_git(self.config.workspace,*args,pulse=self.pulse,evidence=self.evidence,record=self.record)

    def safe_path(self,path):
        if not (self.config.workspace/path.rstrip('/')).resolve().is_relative_to(self.config.workspace.resolve()):
            raise MvpError('write_path_escapes_workspace')

    def check_changes(self,task,changes):
        head=self.git('rev-parse','HEAD')
        if head!=task.base_sha:
            self.git('merge-base','--is-ancestor',task.base_sha,head)
            committed=self.git('diff','--name-only','--no-renames','-z',task.base_sha,head,'--')
            changes=sorted(set(changes)|set(filter(None,committed.split('\0'))))
        for path in changes:
            self.safe_path(path)
            if not any(s=='.' or path==s.rstrip('/') or (s.endswith('/') and path.startswith(s)) for s in task.write_paths):
                raise MvpError('write_scope_violation')
