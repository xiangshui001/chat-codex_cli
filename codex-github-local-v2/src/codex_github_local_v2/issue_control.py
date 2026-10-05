"""Owner-only live Issue commands, progress and durable mobile replies."""
import hashlib
import json
import subprocess
import time
from datetime import datetime

from .mvp0_runner import MvpError, utc_now


def public_text(text):
    # Redact credentials before any model reply leaves the host.
    from .workbench import clean
    return clean(text,limit=len(str(text))+1)


def action(body):
    body=body.strip()
    if body.startswith('/codex-v2-mvp2 run') or body.startswith('<!-- codex-'):return None
    if not body:return None
    parts=body.split(None,2)
    if parts[0]=='/codex':
        command=parts[1].lower() if len(parts)>1 else 'status'
        text=parts[2] if len(parts)>2 else ''
        if command in {'status','stop','retry','merge','allow','say'}:return command,text
        return 'say',body
    if body.rstrip('？?！!。') in {'进度','现在到哪了','做到哪了','进度怎么样','现在做到什么程度了','做到什么程度了','现在做到什么程度','到什么阶段了','进度如何','进展如何','现在进展如何','进展怎么样','status'}:return 'status',''
    return 'say',body


class IssueControl:
    def __init__(self,config,store,github):
        self.config,self.store,self.github=config,store,github
        self.since={}

    def reject(self,source,issue,error,task=None):
        if str((issue.get('user') or {}).get('login','')).lower()!=self.config.owner:return
        if error in {'wrong_host','parallel_capacity_reached','session_busy','unfinished_task_requires_manual_inspection'} or error.startswith('github_'):return
        key=f"rejected/{source.id}/{issue['id']}/{self.config.host_id}/{error}/"+(task.contract_hash if task else hashlib.sha256(str(issue.get('body','')).encode()).hexdigest())
        marker='<!-- codex-remote:'+hashlib.sha256(key.encode()).hexdigest()+' -->'
        client=self.github.client(source)
        message=f"本机 **{self.config.host_id}** 尚未领取：`{error}`。\n\n可直接编辑未领取的手机派单正文，或使用 `/codex run {self.config.host_id}` 简化格式重新派单。任务尚未调用模型。"
        if task and error in {'model_not_allowed','effort_not_allowed','provider_not_allowed','model_api_key_missing'}:
            message+='\n\n请按本机登记的 provider、型号（含大小写）与思考强度填写；API 密钥保留在本机环境。'
        try:
            if not any(marker in c.get('body','') and str((c.get('user') or {}).get('login','')).lower()==self.config.owner for c in client.comments(issue['number'])):
                client.api(f"repos/{source.full_name}/issues/{issue['number']}/comments",{'body':marker+'\n'+message})
        except MvpError:pass

    def status(self,row):
        d=self.store.delivery(row['id'])
        latest=self.store.db.execute("SELECT kind,at,detail FROM events WHERE task_id=? AND kind NOT IN ('remote_instruction_received','session_saved','receipt_sent') ORDER BY id DESC LIMIT 1",(row['id'],)).fetchone()
        activity=latest['kind'] if latest else '等待领取'
        from .workbench import activity as label
        if latest:activity=label(latest).get('label',activity)
        events=self.store.db.execute("SELECT COUNT(*) FROM events WHERE task_id=? AND kind IN ('api_file_tool','remote_file_change')",(row['id'],)).fetchone()[0]
        model=json.loads(d['options_json'])['models']['primary']['model']
        reply=self.store.db.execute("SELECT detail FROM events WHERE task_id=? AND kind='remote_agent_message' ORDER BY id DESC LIMIT 1",(row['id'],)).fetchone()
        progress=json.loads(reply['detail']).get('text','') if reply else ''
        recovery=self.store.db.execute("SELECT detail FROM events WHERE task_id=? AND kind IN ('remote_recovery','api_response_recovery') ORDER BY id DESC LIMIT 1",(row['id'],)).fetchone()
        failure=json.loads(recovery['detail']) if recovery else {}
        diagnostic=failure.get('diagnostic') or failure.get('rpc_error') or failure.get('turn_error')
        return (f"本机 **{row['host_id']}** · `{row['state']}` · 模型 `{model}`\n\n"
                f"当前阶段：{activity}\n\n最近活动：{latest['at'] if latest else row['created_at']}\n\n"
                f"已记录文件操作/变更事件：{events}。任务没有默认执行时长或数据大小上限。\n\n"
                + (f"正在处理：`{row['error']}`\n\n" if row['error'] else '')
                + (f"成果 PR：{d['pr_url']}\n\n" if d['pr_url'] else '')
                + ('模型最近说明：\n\n'+public_text(progress)[:2000]+'\n\n' if progress else '')
                + ('最近恢复原因：`'+public_text(failure.get('reason'))+'`'+ ('\n\n接口诊断：'+public_text(json.dumps(diagnostic,ensure_ascii=False) if isinstance(diagnostic,dict) else diagnostic)[:1500] if diagnostic else '')+'\n\n' if failure and row['state'] in {'queued','running','failed'} else '')
                + "直接留言可继续追加指示；`/codex stop` 停止，`/codex retry` 使用保留的进度续跑。")

    def ingest(self,row,comments):
        channel=self.store.db.execute('SELECT activated_at FROM remote_channels WHERE task_id=?',(row['id'],)).fetchone()
        if not channel:
            self.store.db.execute('INSERT INTO remote_channels VALUES(?,?)',(row['id'],utc_now()))
            return
        for comment in sorted(comments,key=lambda c:c.get('id',0)):
            if str((comment.get('user') or {}).get('login','')).lower()!=self.config.owner:continue
            if comment.get('id',0)<=row['comment_id']:continue
            try:
                if datetime.fromisoformat(comment['created_at'].replace('Z','+00:00')) < datetime.fromisoformat(channel['activated_at'].replace('Z','+00:00')):continue
            except (ValueError,KeyError):continue
            # Comments received before a new run was claimed are still explicit instructions.
            parsed=action(comment.get('body',''))
            if parsed is None:continue
            command,text=parsed
            if command=='allow':
                from .mvp0 import write_path
                try:
                    paths=[p.strip() for p in text.splitlines() if p.strip()]
                    if not paths:raise MvpError('invalid_write_path')
                    for path in paths:
                        if path not in {'.','./','*','/'}:write_path(path,remote=True)
                except MvpError:command='invalid'
            with self.store.transaction():
                cursor=self.store.db.execute('INSERT OR IGNORE INTO remote_messages(task_id,comment_id,action,text,received_at) VALUES(?,?,?,?,?)',
                    (row['id'],comment['id'],command,text,utc_now()))
                if not cursor.rowcount:continue
                ident=cursor.lastrowid
                self.store.event(row['id'],'remote_instruction_received',{'comment_id':comment['id'],'action':command})
                if command=='stop':
                    self.store.db.execute("UPDATE remote_messages SET state='cancelled' WHERE task_id=? AND comment_id<? AND state='queued' AND action IN ('say','retry','allow')",(row['id'],comment['id']))
            if command=='invalid':
                self.store.delivered_message(ident)
                self.store.queue_reply(row['id'],f"invalid/{row['request_id']}/{comment['id']}",'路径无效，请使用仓库相对路径；整仓修改填写 `/codex allow .`。')
                continue
            if command=='status':
                self.store.delivered_message(ident)
                self.store.queue_reply(row['id'],f"status/{row['request_id']}/{comment['id']}",self.status(self.store.get(row['id'])))
            elif command=='allow':
                self.store.queue_reply(row['id'],f"allow/{row['request_id']}/{comment['id']}",'已记录新的修改范围，后续执行与发布检查会使用它。')
            elif command!='merge':
                if command=='stop' and row['state'] not in {'queued','running'}:
                    self.store.delivered_message(ident)
                self.store.queue_reply(row['id'],f"ack/{row['request_id']}/{comment['id']}",
                    ('该任务当前没有运行，保留的对话和文件可随时续跑。' if row['state'] not in {'queued','running'} else '已收到停止指示，正在清理当前进程。') if command=='stop' else '已收到追加指示，会在原对话与当前工作目录继续处理。')

    def poll(self,repos):
        by_name={r.full_name:r for r in repos}
        changed={}
        for name in {r['source_repo'] for r in self.store.db.execute('SELECT DISTINCT source_repo FROM deliveries')}:
            source=by_name.get(name)
            if source is None:continue
            from urllib.parse import quote
            since=self.since.get(name)
            if not since:
                channel=self.store.db.execute('SELECT MIN(activated_at) FROM remote_channels JOIN deliveries ON remote_channels.task_id=deliveries.task_id WHERE source_repo=?',(name,)).fetchone()
                since=channel[0] or utc_now()
            before=utc_now()
            try:
                updates=self.github.client(source).pages(f"repos/{name}/issues?state=all&sort=updated&direction=desc&since={quote(since,safe='')}")
                if isinstance(updates,list):changed[name]={i['id'] for i in updates if isinstance(i,dict) and 'id' in i}
                self.since[name]=before
            except MvpError:continue
        # Scan known tasks as well as new Issues, so completed conversations can continue.
        for row in self.store.db.execute('SELECT * FROM tasks ORDER BY id').fetchall():
            d=self.store.delivery(row['id']);source=by_name.get(d['source_repo'])
            if not source:continue
            client=self.github.client(source)
            if d['source_repo'] not in changed or row['issue_id'] in changed[d['source_repo']]:
                try:self.ingest(row,client.comments(row['issue_number']))
                except MvpError:
                    # Revisit the same update if fetching its comments failed.
                    self.since.pop(d['source_repo'],None)
                    continue
            queued=self.store.inbox(row['id'])
            if row['state'] not in {'queued','running'} and any(m['action'] in {'say','retry','allow'} for m in queued):
                self.store.reopen(row['id'],'owner_followup')
                row=self.store.get(row['id'])
            if row['state'] in {'queued','running'}:
                bucket=int(time.time()/self.config.progress_seconds)
                self.store.queue_reply(row['id'],f"heartbeat/{row['request_id']}/{bucket}",self.status(row))
            for m in queued:
                if m['action']=='merge' and d['pr_url']:
                    self.merge(row,d,client,m)
            if row['state']=='succeeded' and d['pr_url'] and self.config.auto_merge:
                self.merge(row,d,client,None)
        self.flush(repos)

    def merge(self,row,d,client,message):
        number=int(d['pr_url'].rsplit('/',1)[-1])
        try:
            pr=client.api(f"repos/{row['repo']}/pulls/{number}")
            if not pr.get('merged'):
                subprocess.run(['gh','pr','ready',str(number),'--repo',row['repo']],capture_output=True,check=bool(pr.get('draft')),timeout=None)
                # Use exact reviewed/published commit; never force push or bypass branch protection.
                result=client.api(f"repos/{row['repo']}/pulls/{number}/merge",{'sha':d['commit_sha'],'merge_method':'merge'},method='PUT')
                if not result.get('merged'):raise MvpError('merge_not_ready')
            if message:self.store.delivered_message(message['id'])
            self.store.queue_reply(row['id'],f"merged/{row['request_id']}/{d['commit_sha']}",f"成果已合并到默认分支：{d['pr_url']}")
        except (MvpError,OSError,subprocess.SubprocessError):
            self.store.queue_reply(row['id'],f"merge-pending/{row['request_id']}/{d['commit_sha']}",f"成果 PR 已保存，合并尚未成功（可能有冲突、检查或分支保护）：{d['pr_url']}。将继续检查，任务成果不会删除。")

    def flush(self,repos):
        by_name={r.full_name:r for r in repos}
        for reply in self.store.db.execute('SELECT * FROM remote_replies WHERE comment_id IS NULL ORDER BY id').fetchall():
            row=self.store.get(reply['task_id']);d=self.store.delivery(row['id']);source=by_name.get(d['source_repo'])
            if source is None:continue
            client=self.github.client(source)
            marker='<!-- codex-remote:' + hashlib.sha256(reply['reply_key'].encode()).hexdigest() + ' -->'
            try:
                # Reconcile an unknown POST outcome before writing a second reply.
                previous=[c for c in client.comments(row['issue_number']) if marker in c.get('body','') and str((c.get('user') or {}).get('login','')).lower()==self.config.owner]
                result=previous[-1] if previous else client.api(f"repos/{source.full_name}/issues/{row['issue_number']}/comments",{'body':marker+'\n'+public_text(reply['body'])})
                if type(result.get('id')) is not int:raise MvpError('invalid_github_comment_response')
                self.store.db.execute('UPDATE remote_replies SET comment_id=? WHERE id=?',(result['id'],reply['id']))
            except MvpError:continue
