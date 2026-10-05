"""Repository tools with paging and disk-backed command output, no size ceilings."""
import base64
import json
import os
from pathlib import Path
import signal
import subprocess
import uuid

from .mvp0 import fields, write_path
from .mvp0_runner import MvpError, CodexRunner
from .process_identity import identity


def tool(name, description, properties, required=()):
    return {'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}}

STR={'type':'string'}
INT={'type':'integer','minimum':0}
FILE_TOOLS=[
    tool('list_files','List repository files, including hidden/dependency directories. Use offset/limit to page; omitted limit returns all.',
         {'offset':INT,'limit':{'type':'integer','minimum':1}}),
    tool('read_file','Read any repository file. Optional byte offset/length for chunks; encoding utf-8 or base64. No file size ceiling.',
         {'path':STR,'offset':INT,'length':{'type':'integer','minimum':1},'encoding':{'type':'string','enum':['utf-8','base64']}},('path',)),
    tool('write_file','Write UTF-8 or base64 content to an authorized path. append=true supports arbitrarily large files in chunks.',
         {'path':STR,'content':STR,'append':{'type':'boolean'},'encoding':{'type':'string','enum':['utf-8','base64']}},('path','content')),
    tool('delete_file','Delete a regular file in an authorized path.',{'path':STR},('path',)),
    tool('run_command','Run commands, scripts, tests or local commits in the current repository/task branch. Output goes to private local files; no implicit timeout. Use read_command_output to page output. The controller handles remote publication.',
         {'argv':{'type':'array','items':STR,'minItems':1},'cwd':STR,'timeout':{'type':['integer','null'],'minimum':1}},('argv',)),
    tool('read_session_history','Retrieve the full preserved conversation after provider context window recovery. Without entry returns a message index. With entry returns its JSON content, optionally paged by byte offset/length.',
         {'entry':INT,'offset':INT,'length':{'type':'integer','minimum':1}}),
    tool('read_command_output','Read a byte range of command stdout/stderr. Omitted length returns all; use chunks for large output.',
         {'command_id':STR,'stream':{'type':'string','enum':['stdout','stderr']},'offset':INT,'length':{'type':'integer','minimum':1}},('command_id',))
]


class RepositoryTools:
    def __init__(self, workspace, write_paths, evidence=None, pulse=lambda:None):
        self.workspace=Path(workspace).resolve()
        self.write_paths=write_paths
        self.evidence=Path(evidence) if evidence else None
        self.pulse=pulse

    def path(self, raw, *, write=False):
        name=write_path(raw, remote=True)
        path=self.workspace/name
        if not path.resolve().is_relative_to(self.workspace):
            raise MvpError('tool_path_escape')
        if write and not any(scope=='.' or name==scope.rstrip('/') or (scope.endswith('/') and name.startswith(scope)) for scope in self.write_paths):
            raise MvpError('write_scope_violation')
        return path

    @staticmethod
    def integer(args,key,default=None):
        value=args.get(key,default)
        if value is not None and (type(value) is not int or value<0 or (key in {'length','limit','timeout'} and value==0)):
            raise MvpError('invalid_tool_arguments')
        return value

    @classmethod
    def read(cls,path,args):
        if args.get('encoding','utf-8') not in {'utf-8','base64'}:raise MvpError('invalid_encoding')
        offset=cls.integer(args,'offset',0);length=cls.integer(args,'length')
        with path.open('rb') as stream:
            stream.seek(offset);data=stream.read() if length is None else stream.read(length)
        encoded=base64.b64encode(data).decode() if args.get('encoding')=='base64' else data.decode('utf-8',errors='replace')
        return {'content':encoded,'offset':offset,'next_offset':offset+len(data),'eof':offset+len(data)>=path.stat().st_size,'size':path.stat().st_size}

    def call(self,name,args):
        schema=next((t for t in FILE_TOOLS if t['name']==name),None)
        if not schema:raise MvpError('model_tool_not_allowed')
        fields(args,set(schema['parameters']['required']),set(schema['parameters']['properties'])-set(schema['parameters']['required']))
        if name=='list_files':
            offset=self.integer(args,'offset',0);limit=self.integer(args,'limit')
            files=[];seen=0;more=False
            for base,dirs,names in os.walk(self.workspace,followlinks=False):
                dirs[:]=sorted(d for d in dirs if d!='.git' and not (Path(base)/d).is_symlink())
                for item in sorted(names):
                    path=(Path(base)/item).relative_to(self.workspace).as_posix()
                    try:self.path(path)
                    except MvpError:continue
                    if seen>=offset:
                        if limit is not None and len(files)>=limit:more=True;break
                        files.append(path)
                    seen+=1
                if more:break
            return {'files':files,'truncated':more,'next_offset':offset+len(files) if more else None}
        if name=='read_session_history':
            if self.evidence is None:raise MvpError('session_evidence_required')
            history=json.loads((self.evidence/'context.json').read_text(encoding='utf-8'))
            if 'entry' not in args:return {'messages':[{'entry':i,'role':m.get('role',m.get('type')),'bytes':len(json.dumps(m,ensure_ascii=False).encode())} for i,m in enumerate(history)]}
            index=self.integer(args,'entry')
            if index>=len(history):raise MvpError('invalid_history_entry')
            path=self.evidence/'history-entry.json'
            path.write_text(json.dumps(history[index],ensure_ascii=False),encoding='utf-8')
            return {'entry':index,**self.read(path,args)}
        if name=='run_command':
            if self.evidence is None:raise MvpError('command_evidence_required')
            argv=args['argv']
            if not isinstance(argv,list) or not argv or any(not isinstance(s,str) or '\0' in s for s in argv):raise MvpError('invalid_tool_arguments')
            cwd=self.workspace if args.get('cwd','.') in {'.','./'} else self.path(args['cwd'])
            if not cwd.is_dir():raise MvpError('invalid_tool_directory')
            timeout=self.integer(args,'timeout')
            command_id=str(uuid.uuid4());folder=self.evidence/'commands'/command_id
            folder.mkdir(parents=True,mode=0o700)
            env=dict(os.environ)
            for key in ('GH_TOKEN','GITHUB_TOKEN','GH_ENTERPRISE_TOKEN','GITHUB_ENTERPRISE_TOKEN'):env.pop(key,None)
            proc=None
            audit={'argv':argv,'cwd':str(cwd),'state':'starting'}
            try:
                with (folder/'stdout').open('wb') as stdout,(folder/'stderr').open('wb') as stderr:
                    proc=subprocess.Popen(argv,cwd=cwd,env=env,stdout=stdout,stderr=stderr,stdin=subprocess.DEVNULL,start_new_session=True)
                    audit.update(state='running',pid=proc.pid,lease=identity(proc.pid))
                    (folder/'execution.json').write_text(json.dumps(audit),encoding='utf-8')
                    import time
                    start=time.monotonic()
                    while proc.poll() is None:
                        self.pulse()
                        if timeout is not None and time.monotonic()-start>=timeout:raise MvpError('command_timeout')
                        time.sleep(.2)
            finally:
                if proc is not None:CodexRunner._stop_group(proc)
                audit.update(state='finished',exit_code=proc.returncode if proc else None,cleanup='process_group_terminated')
                (folder/'execution.json').write_text(json.dumps(audit),encoding='utf-8')
            sizes={s:(folder/s).stat().st_size for s in ('stdout','stderr')}
            return {'command_id':command_id,'exit_code':proc.returncode,'bytes':sizes,
                    'stdout_preview':self.read(folder/'stdout',{'length':8192})['content'],
                    'stderr_preview':self.read(folder/'stderr',{'length':8192})['content']}
        if name=='read_command_output':
            try:ident=str(uuid.UUID(args['command_id']))
            except (ValueError,TypeError):raise MvpError('invalid_command_id')
            stream=args.get('stream','stdout')
            if stream not in {'stdout','stderr'} or self.evidence is None:raise MvpError('invalid_tool_arguments')
            return self.read(self.evidence/'commands'/ident/stream,args)
        path=self.path(args['path'],write=name!='read_file')
        if name=='read_file':return self.read(path,args)
        if name=='write_file':
            if not isinstance(args['content'],str) or type(args.get('append',False)) is not bool:raise MvpError('invalid_file_content')
            if args.get('encoding','utf-8') not in {'utf-8','base64'}:raise MvpError('invalid_encoding')
            data=base64.b64decode(args['content'],validate=True) if args.get('encoding')=='base64' else args['content'].encode('utf-8')
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('ab' if args.get('append') else 'wb') as stream:stream.write(data)
        else:
            if not path.is_file():raise MvpError('regular_file_required')
            path.unlink()
        return {'path':args['path'],'status':'ok'}
