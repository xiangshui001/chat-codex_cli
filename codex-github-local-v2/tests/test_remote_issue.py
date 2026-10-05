from dataclasses import replace
from datetime import datetime, timezone, timedelta
import base64
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

import test_mvp2 as fixtures
import test_model_api as api_fixtures
from codex_github_local_v2.api_checkpoint import restore_pending,save_result
from codex_github_local_v2.api_recovery import ResponseRecovery
from codex_github_local_v2.app_server_runner import AppServerRunner
from codex_github_local_v2.issue_control import IssueControl, action
from codex_github_local_v2.large_file_tools import RepositoryTools
from codex_github_local_v2.model_api import ModelClient,ModelRegistry
from codex_github_local_v2.mvp0_runner import MvpError
from codex_github_local_v2.mvp2 import DesktopStore,Publisher,branch_name
from codex_github_local_v2.mvp2_contract import DesktopConfig,parse_desktop_task
from codex_github_local_v2.mvp2_runner import ApiFileRunner
from codex_github_local_v2.remote_git import run_remote_git


class RemoteIssueTests(fixtures.Fixture):
    def setUp(self):
        super().setUp()
        self.s=self.store()
        self.ident=self.s.claim_desktop(self.source,self.target,self.issue,self.parse(),{})
        self.client=Mock()
        self.comments=[]
        self.client.comments.side_effect=lambda *_:list(self.comments)
        self.posts=[]
        def post(endpoint,body=None,**kwargs):
            self.posts.append(body)
            comment={'id':1000+len(self.posts),'body':body['body'],'user':{'login':'owner'}}
            self.comments.append(comment)
            return comment
        self.client.api.side_effect=post
        self.gh=Mock()
        self.gh.client.return_value=self.client
        self.remote=IssueControl(self.config,self.s,self.gh)

    def incoming_comment(self,ident,body,owner='owner',old=False):
        at=datetime.now(timezone.utc)+timedelta(seconds=-30 if old else 2)
        return {'id':ident,'body':body,'user':{'login':owner},'created_at':at.isoformat()}

    def test_owner_inbox_deduplicates_and_ignores_historical_or_other_authors(self):
        messages=[self.incoming_comment(222,'新要求'),self.incoming_comment(223,'/codex stop','visitor'),self.incoming_comment(224,'旧要求',old=True),
                  self.incoming_comment(225,'<!-- codex-remote:aaa -->\n自己的回执')]
        self.remote.ingest(self.s.get(1),messages)
        self.remote.ingest(self.s.get(1),messages)
        self.assertEqual([(m['comment_id'],m['text']) for m in self.s.inbox(1)],[(222,'新要求')])

    def test_status_does_not_restart_finished_model_and_stop_does_not_poison_next_run(self):
        self.s.finish(1,'succeeded',0,None,False,'done')
        self.remote.ingest(self.s.get(1),[self.incoming_comment(222,'/codex status'),self.incoming_comment(223,'/codex stop')])
        self.assertEqual(self.s.inbox(1),[])
        self.assertEqual(self.s.get(1)['state'],'succeeded')
        self.remote.flush([self.source])
        self.assertTrue(any('当前阶段' in p['body'] for p in self.posts))

    def test_followup_keeps_original_contract_and_archives_previous_result(self):
        original=dict(self.s.get(1))
        self.s.save_session(1,fixtures.SID,'codex')
        self.s.publication(1,commit_sha='b'*40,pr_url='https://github.com/owner/project/pull/5')
        self.s.finish(1,'succeeded',0,None,True,'done')
        self.remote.ingest(self.s.get(1),[self.incoming_comment(222,'/codex allow .'),self.incoming_comment(223,'继续补充测试')])
        self.assertTrue(self.s.reopen(1,'owner_followup'))
        self.assertFalse(self.s.reopen(1,'duplicate'))
        row=self.s.get(1)
        for key in ('prompt','write_paths','base_sha','contract_hash','comment_id'):self.assertEqual(row[key],original[key])
        self.assertEqual(self.s.effective_paths(1),('docs/check.txt','.'))
        self.assertEqual(self.s.delivery(1)['session_id'],fixtures.SID)
        self.assertEqual(self.s.delivery(1)['commit_sha'],'b'*40)
        snapshot=json.loads(self.s.db.execute('SELECT snapshot FROM remote_runs').fetchone()[0])
        self.assertEqual(snapshot['task']['state'],'succeeded')
        self.assertEqual(self.s.generation(1),1)

    def test_lost_reply_response_is_reconciled_without_duplicate_post(self):
        original=self.client.api.side_effect
        def lost(endpoint,body=None,**kwargs):
            original(endpoint,body,**kwargs)
            raise MvpError('github_transport_unavailable')
        self.client.api.side_effect=lost
        self.remote.flush([self.source])
        self.assertEqual(len(self.posts),1)
        self.client.api.side_effect=original
        self.remote.flush([self.source])
        self.assertEqual(len(self.posts),1)
        self.assertIsNotNone(self.s.db.execute('SELECT comment_id FROM remote_replies').fetchone()[0])

    def test_large_reply_is_split_without_losing_content(self):
        self.s.queue_reply(1,'huge','中'*150001)
        rows=self.s.db.execute("SELECT body FROM remote_replies WHERE reply_key LIKE 'huge/%' ORDER BY id").fetchall()
        self.assertEqual(''.join(r[0] for r in rows),'中'*150001)

    def test_same_session_followup_waits_for_other_active_task(self):
        self.s.save_session(1,fixtures.SID,'codex')
        self.s.finish(1,'succeeded',0,None,False,'done')
        import uuid
        task=replace(self.parse(),request_id=str(uuid.uuid4()),session={'mode':'resume','id':fixtures.SID})
        other=self.s.claim_desktop(self.source,self.target,{**self.issue,'id':102,'number':4},task,{},3)
        self.assertFalse(self.s.reopen(1,'owner_followup'))
        self.s.finish(other,'succeeded',0,None,False,'done')
        self.assertTrue(self.s.reopen(1,'owner_followup'))

    def test_stop_supersedes_older_unapplied_instructions_and_invalid_scope_never_takes_effect(self):
        self.remote.ingest(self.s.get(1),[self.incoming_comment(222,'先做这个'),self.incoming_comment(223,'/codex allow ../private'),self.incoming_comment(224,'/codex stop')])
        self.assertEqual([m['action'] for m in self.s.inbox(1)],['stop'])
        self.assertEqual(self.s.effective_paths(1),('docs/check.txt',))
        self.assertEqual(action('现在做到什么程度了？'),('status',''))

    def test_mobile_issue_accepts_whole_repository_and_large_prompt_without_uuid_or_sha(self):
        issue={**self.issue,'body':'/codex run desktop\nrepo: owner/project\nmodel: gpt-6.1-sol\neffort: high\n\n'+'完整任务'*10000}
        task=parse_desktop_task(issue,[],self.source,self.config)
        self.assertEqual(task.write_paths,('.',))
        self.assertEqual(task.base_sha,'')
        self.assertEqual(task.models['primary']['model'],'gpt-6.1-sol')
        self.assertEqual(len(task.prompt),40000)
        self.assertEqual(task.request_id,parse_desktop_task(issue,[],self.source,self.config).request_id)
        with self.assertRaisesRegex(MvpError,'wrong_host'):
            parse_desktop_task({**issue,'body':issue['body'].replace('desktop','laptop',1)},[],self.source,self.config)
        with self.assertRaises(MvpError):
            parse_desktop_task({**issue,'user':{'login':'foreign'}},[],self.source,self.config)

    def test_schema_four_migration_preserves_frozen_rows_and_activates_channels_at_upgrade(self):
        self.s.finish(1,'failed',1,'workspace_git_failed',False,'retained')
        before=dict(self.s.get(1));delivery=dict(self.s.delivery(1))
        for table in ('remote_runs','remote_replies','remote_messages','remote_channels'):self.s.db.execute('DROP TABLE '+table)
        self.s.db.execute('PRAGMA user_version=4')
        DesktopStore.migrate(self.s.path)
        self.assertEqual(dict(self.s.get(1)),before)
        self.assertEqual(dict(self.s.delivery(1)),delivery)
        self.assertEqual(self.s.db.execute('PRAGMA user_version').fetchone()[0],5)
        self.remote.ingest(self.s.get(1),[self.incoming_comment(222,'旧的完成回执',old=True)])
        self.assertEqual(self.s.inbox(1),[])


class LargeToolsTests(fixtures.Fixture):
    def setUp(self):
        super().setUp()
        self.workspace=self.root/'project';self.workspace.mkdir()
        self.evidence=self.root/'evidence'
        self.tools=RepositoryTools(self.workspace,('.',),self.evidence)

    def test_large_utf8_binary_and_append_roundtrip(self):
        content='大文件\n'*300000
        self.tools.call('write_file',{'path':'docs/large.txt','content':content})
        self.tools.call('write_file',{'path':'docs/large.txt','content':'追加','append':True})
        self.assertEqual(self.tools.call('read_file',{'path':'docs/large.txt'})['content'],content+'追加')
        data=bytes(range(256))*10000
        self.tools.call('write_file',{'path':'binary.bin','content':base64.b64encode(data).decode(),'encoding':'base64'})
        answer=self.tools.call('read_file',{'path':'binary.bin','offset':300000,'length':800000,'encoding':'base64'})
        self.assertEqual(base64.b64decode(answer['content']),data[300000:1100000])
        self.assertEqual(answer['next_offset'],1100000)

    def test_listing_pages_every_file_including_hidden_and_dependencies(self):
        for directory in ('.hidden','node_modules','venv','src'):
            (self.workspace/directory).mkdir()
            for n in range(101):(self.workspace/directory/f'{n:03}.txt').write_text('x')
        (self.workspace/'.git').mkdir();(self.workspace/'.git'/'config').write_text('excluded')
        all_files=self.tools.call('list_files',{})['files']
        self.assertEqual(len(all_files),404)
        collected=[];offset=0
        while True:
            page=self.tools.call('list_files',{'offset':offset,'limit':70})
            collected.extend(page['files'])
            if page['next_offset'] is None:break
            offset=page['next_offset']
        self.assertEqual(collected,all_files)

    def test_secret_files_are_owner_authorized_but_paths_stay_in_repository(self):
        self.tools.call('write_file',{'path':'.env.local','content':'example'})
        self.assertEqual(self.tools.call('read_file',{'path':'.env.local'})['content'],'example')
        for name in ('../outside','/absolute','.git/config','.codex/config.toml'):
            with self.subTest(path=name),self.assertRaises(MvpError):self.tools.call('write_file',{'path':name,'content':'x'})

    @unittest.skipUnless(os.name=='posix','Process group test requires Linux/WSL')
    def test_command_large_output_saved_without_truncating_file(self):
        result=self.tools.call('run_command',{'argv':[sys.executable,'-c','import sys;sys.stdout.write("x"*3000000)']})
        self.assertEqual(result['exit_code'],0)
        self.assertEqual(result['bytes']['stdout'],3000000)
        full=self.tools.call('read_command_output',{'command_id':result['command_id']})
        self.assertEqual(len(full['content']),3000000)
        self.assertTrue(full['eof'])
        audit=json.loads((self.evidence/'commands'/result['command_id']/'execution.json').read_text())
        self.assertEqual(audit['cleanup'],'process_group_terminated')

    @unittest.skipUnless(os.name=='posix','Process group test requires Linux/WSL')
    def test_stop_cancels_command_and_records_cleanup(self):
        self.tools.pulse=lambda:(_ for _ in ()).throw(MvpError('cancelled_by_owner'))
        with self.assertRaisesRegex(MvpError,'cancelled_by_owner'):
            self.tools.call('run_command',{'argv':[sys.executable,'-c','import time;time.sleep(60)']})
        audit=json.loads(next((self.evidence/'commands').glob('*/execution.json')).read_text())
        with self.assertRaises(ProcessLookupError):os.kill(audit['pid'],0)
        self.assertEqual(audit['cleanup'],'process_group_terminated')


class UnlimitedApiTests(api_fixtures.ApiFixture):
    def test_defaults_omit_provider_token_ceiling_and_accept_multi_megabyte_reply(self):
        self.file.write_text(json.dumps({'providers':self.providers}))
        registry=ModelRegistry(self.file)
        self.assertTrue(all(value is None for value in registry.limits.values()))
        self.queue=[api_fixtures.chat('x'*3000000)]
        reply=ModelClient(registry).call(self.other,[{'role':'user','content':'x'*1500000}])
        self.assertEqual(len(reply['text']),3000000)
        self.assertNotIn('max_tokens',self.requests[0][1])

    def test_api_checkpoint_retains_large_history_and_registers_session_before_first_response(self):
        workspace=self.root/'project';workspace.mkdir()
        from codex_github_local_v2.mvp2_contract import DesktopTask
        task=DesktopTask(fixtures.RID,'desktop','owner/project','a'*40,'answer',('.',),1,'hash',{'mode':'new'},{'mode':'api','primary':self.other})
        events=[];evidence=self.root/'run'
        self.queue=[api_fixtures.chat('done')]
        result,sid,history=ApiFileRunner(self.registry).run_task(task,workspace,evidence,None,lambda kind,detail:events.append((kind,detail)),[{'role':'user','content':'z'*3000000}])
        self.assertIsNone(result.error)
        self.assertGreater((evidence/'context.json').stat().st_size,3000000)
        opened=next(i for i,e in enumerate(events) if e[0]=='remote_session_opened')
        requested=next(i for i,e in enumerate(events) if e[0]=='api_model_request')
        self.assertLess(opened,requested)

    def test_stop_remains_responsive_during_unbounded_http_wait(self):
        started=threading.Event();release=threading.Event()
        def waiting(*args,**kwargs):started.set();release.wait();return {'text':'done','calls':[],'history':[]}
        recovery=ResponseRecovery(self.registry)
        recovery.pulse=lambda:(_ for _ in ()).throw(MvpError('cancelled_by_owner')) if started.is_set() else None
        try:
            with self.assertRaisesRegex(MvpError,'cancelled_by_owner'):
                recovery.call(Mock(call=waiting),self.other,[],(),float('inf'))
        finally:release.set()

    def test_restart_repairs_tool_sequence_from_ledger_without_reexecuting(self):
        evidence=self.root/'run';evidence.mkdir()
        history=[{'role':'assistant','content':None,'tool_calls':[api_fixtures.function('write_file',{'path':'a','content':'once'},'one'),api_fixtures.function('run_command',{'argv':['cmd']},'unknown')]}]
        save_result(evidence,'one',{'status':'ok','path':'a'})
        self.assertTrue(restore_pending(history,'chat_completions',evidence))
        self.assertEqual(json.loads(history[1]['content'])['status'],'ok')
        self.assertEqual(json.loads(history[2]['content'])['error'],'previous_tool_outcome_unconfirmed')
        self.assertFalse(restore_pending(history,'chat_completions',evidence))

    def test_context_window_view_preserves_tool_pairs_and_full_original_archive(self):
        from codex_github_local_v2.context_window import request_view
        history=[{'role':'system','content':'tools and permissions'},{'role':'user','content':'original task'},
                 {'role':'assistant','content':None,'tool_calls':[api_fixtures.function('read_file',{'path':'large'},'one')]},
                 {'role':'tool','tool_call_id':'one','content':'z'*3000000},{'role':'user','content':'continue'}]
        original=json.dumps(history)
        view=request_view(history,5000)
        self.assertEqual(json.dumps(history),original)
        self.assertLess(len(json.dumps(view)),6000)
        self.assertIn('read_session_history',json.dumps(view))
        pending=set()
        for message in view:
            pending.update(c['id'] for c in message.get('tool_calls',[]))
            if message.get('role')=='tool':self.assertIn(message['tool_call_id'],pending);pending.remove(message['tool_call_id'])
        self.assertFalse(pending)

    def test_mcp_background_consultation_returns_immediately_then_keeps_full_result(self):
        from codex_github_local_v2.collaboration_api import mcp_dispatch
        entered=threading.Event();release=threading.Event()
        def consult(index,prompt):entered.set();release.wait();return {'model':'test','text':'x'*200000}
        bridge=Mock(async_consultations=True,jobs={},consult=consult)
        try:
            first=mcp_dispatch({'method':'tools/call','params':{'name':'consult_model','arguments':{'index':0,'prompt':'question'}}},bridge)
            result=json.loads(first['content'][0]['text'])
            self.assertEqual(result['status'],'running');self.assertTrue(entered.wait(2))
            current=mcp_dispatch({'method':'tools/call','params':{'name':'get_consultation','arguments':{'job_id':result['job_id']}}},bridge)
            self.assertEqual(json.loads(current['content'][0]['text'])['status'],'running')
        finally:release.set()
        end=time.monotonic()+2
        while bridge.jobs[result['job_id']]['status']=='running':
            self.assertLess(time.monotonic(),end);time.sleep(.01)
        self.assertEqual(len(bridge.jobs[result['job_id']]['text']),200000)


FAKE_SERVER='''
import json,sys,pathlib,time
root=pathlib.Path(sys.argv[1]);mode=sys.argv[2];thread="56384b35-4a58-42eb-a9d3-3b203d29a3b9";number=0
def out(value):print(json.dumps(value),flush=True)
def notify(method,params,owner=None,turn_id=None):
 params['threadId']=owner or thread
 if turn_id:params['turnId']=turn_id
 out({'method':method,'params':params})
for line in sys.stdin:
 m=json.loads(line);method=m.get("method");p=m.get("params",{});ident=m.get("id")
 if method=="initialize":out({"id":ident,"result":{}})
 elif method in ("thread/start","thread/resume"):
  (root/"thread-params.json").write_text(json.dumps(p));out({"id":ident,"result":{"thread":{"id":thread}}})
 elif method=="turn/start":
  number+=1;turn="turn-"+str(number)
  (root/("start-"+str(number)+".json")).write_text(json.dumps(p))
  if mode=='rpc-retry' and number==1:
   out({'id':ident,'error':{'code':-32000,'message':'temporary start failure'}});continue
  if mode=='late-steer':
   (root/'start-waiting').write_text(turn);time.sleep(.5)
  out({"id":ident,"result":{"turn":{"id":turn}}});notify('turn/started',{'turn':{'id':turn}})
  if mode in ('recover','stale') and number==1:notify('turn/completed',{'turn':{'id':turn,'status':'failed','error':{'message':'temporary network failure'}}})
  elif mode in ("steer","late-steer"):(root/"ready").write_text(turn)
  else:
   if mode in ('foreign','foreign-failure'):
    notify('turn/started',{'turn':{'id':'child-turn'}},'child-thread')
    notify('item/completed',{'item':{'type':'agentMessage','id':'child-answer','phase':'final_answer','text':'child audit only'}},'child-thread','child-turn')
    notify('error',{'willRetry':False,'error':{'message':'child failure'}},'child-thread','child-turn')
    notify('turn/completed',{'turn':{'id':'child-turn','status':'completed' if mode=='foreign' else 'interrupted'}},'child-thread')
    time.sleep(.6)
   elif mode=='stale' and number==2:
    notify('turn/started',{'turn':{'id':'turn-1'}})
    notify('item/completed',{'item':{'type':'agentMessage','id':'stale-answer','text':'stale answer'}},turn_id='turn-1')
    notify('turn/completed',{'turn':{'id':'turn-1','status':'completed'}})
    time.sleep(.6)
   (root/'parent-finished').write_text(turn)
   notify('item/completed',{'item':{'type':'agentMessage','id':'parent-answer','phase':'final_answer','text':'parent work complete'}},turn_id=turn)
   notify('turn/completed',{'turn':{'id':turn,'status':'completed'}})
 elif method=="turn/steer":
  (root/"steer.json").write_text(json.dumps(p));out({"id":ident,"result":{}});notify('item/completed',{'item':{'type':'agentMessage','id':'answer','phase':'final_answer','text':'new instruction applied'}},turn_id=p['expectedTurnId']);notify('turn/completed',{'turn':{'id':p['expectedTurnId'],'status':'completed'}})
 elif method=="turn/interrupt":out({"id":ident,"result":{}})
'''


@unittest.skipUnless(os.name=='posix','JSON-RPC process test requires Linux/WSL')
class AppServerTests(fixtures.Fixture):
    def metadata(self,mode):
        server=self.root/'server.py';server.write_text(FAKE_SERVER)
        return {'argv':[sys.executable,str(server),str(self.root),mode],'cwd':str(self.root),'model':'gpt-6.1-sol','effort':'high','full_access':True}

    def test_running_turn_receives_followup_in_same_thread_and_acknowledges_once(self):
        acknowledged=[];events=[]
        msg={'id':1,'comment_id':222,'action':'say','text':'new instruction'}
        def control():return [msg] if (self.root/'ready').exists() and not acknowledged else []
        result=AppServerRunner(control,acknowledged.append).run(self.metadata('steer'),'original',self.root/'run',None,lambda k,d:events.append((k,d)))
        self.assertIsNone(result.error)
        self.assertEqual(acknowledged,[1])
        steer=json.loads((self.root/'steer.json').read_text())
        self.assertEqual(steer['threadId'],fixtures.SID)
        self.assertEqual(steer['expectedTurnId'],'turn-1')
        self.assertEqual(steer['input'][0]['text'],'new instruction')
        self.assertEqual(json.loads((self.root/'thread-params.json').read_text())['sandbox'],'danger-full-access')

    def test_failed_turn_retries_using_original_thread(self):
        events=[]
        result=AppServerRunner().run(self.metadata('recover'),'task',self.root/'run',10,lambda k,d:events.append((k,d)))
        self.assertIsNone(result.error)
        self.assertEqual(len([e for e in events if e[0]=='remote_session_opened']),1)
        self.assertEqual(len([e for e in events if e[0]=='remote_turn_started']),2)
        self.assertTrue(any(e[0]=='remote_recovery' for e in events))

    def test_initial_owner_constraints_are_in_first_request_without_extra_turn(self):
        acknowledged=[];events=[]
        messages=[{'id':i,'comment_id':200+i,'action':'say','text':text}
                  for i,text in ((1,'Do not submit any new model jobs'),(2,'Use saved answers only'))]
        def control():return [m for m in messages if m['id'] not in acknowledged]
        result=AppServerRunner(control,acknowledged.append).run(self.metadata('foreign'),'original',self.root/'run',10,lambda k,d:events.append((k,d)))
        self.assertIsNone(result.error)
        first=json.loads((self.root/'start-1.json').read_text())['input'][0]['text']
        for message in messages:self.assertIn(message['text'],first)
        self.assertEqual(acknowledged,[1,2])
        self.assertFalse((self.root/'start-2.json').exists())
        self.assertEqual([d['turn_id'] for k,d in events if k=='remote_turn_started'],['turn-1'])

    def test_instruction_arriving_during_start_is_steered_into_current_turn(self):
        acknowledged=[]
        message={'id':1,'comment_id':222,'action':'say','text':'No new calls; inspect retained results'}
        def control():return [message] if (self.root/'start-waiting').exists() and not acknowledged else []
        result=AppServerRunner(control,acknowledged.append).run(self.metadata('late-steer'),'original',self.root/'run',5,lambda *_:None)
        self.assertIsNone(result.error)
        steer=json.loads((self.root/'steer.json').read_text())
        self.assertEqual(steer['expectedTurnId'],'turn-1')
        self.assertEqual(steer['input'][0]['text'],message['text'])
        self.assertEqual(acknowledged,[1])
        self.assertFalse((self.root/'start-2.json').exists())

    def test_rpc_start_retry_keeps_unacknowledged_owner_constraints(self):
        acknowledged=[]
        message={'id':1,'comment_id':222,'action':'say','text':'Do not repeat the paid jobs'}
        def control():return [message] if not acknowledged else []
        result=AppServerRunner(control,acknowledged.append).run(self.metadata('rpc-retry'),'original',self.root/'run',10,lambda *_:None)
        self.assertIsNone(result.error)
        for number in (1,2):
            start=json.loads((self.root/('start-'+str(number)+'.json')).read_text())
            self.assertIn(message['text'],start['input'][0]['text'])
        self.assertEqual(acknowledged,[1])
        self.assertFalse((self.root/'start-3.json').exists())

    def test_child_completion_cannot_finish_the_parent_or_replace_its_answer(self):
        events=[]
        result=AppServerRunner().run(self.metadata('foreign'),'task',self.root/'run',10,lambda k,d:events.append((k,d)))
        self.assertIsNone(result.error)
        self.assertEqual((self.root/'parent-finished').read_text(),'turn-1')
        self.assertEqual([d['turn_id'] for k,d in events if k=='remote_turn_started'],['turn-1'])
        self.assertEqual([d['text'] for k,d in events if k=='remote_agent_message'],['parent work complete'])
        self.assertFalse(any(k=='remote_transport_error' for k,d in events))

    def test_child_interruption_does_not_cancel_parent_execution(self):
        events=[]
        result=AppServerRunner().run(self.metadata('foreign-failure'),'task',self.root/'run',10,lambda k,d:events.append((k,d)))
        self.assertIsNone(result.error)
        self.assertTrue((self.root/'parent-finished').is_file())
        self.assertEqual([d['text'] for k,d in events if k=='remote_agent_message'],['parent work complete'])

    def test_late_previous_turn_events_cannot_finish_a_recovery_turn(self):
        events=[]
        result=AppServerRunner().run(self.metadata('stale'),'task',self.root/'run',10,lambda k,d:events.append((k,d)))
        self.assertIsNone(result.error)
        self.assertEqual((self.root/'parent-finished').read_text(),'turn-2')
        self.assertEqual([d['turn_id'] for k,d in events if k=='remote_turn_started'],['turn-1','turn-2'])
        self.assertEqual([d['text'] for k,d in events if k=='remote_agent_message'],['parent work complete'])

    def test_owner_stop_preserves_session_and_cleans_process(self):
        msg={'id':1,'comment_id':222,'action':'stop','text':''}
        def control():return [msg] if (self.root/'ready').exists() else []
        result=AppServerRunner(control).run(self.metadata('steer'),'task',self.root/'run',None,lambda *_:None)
        self.assertEqual(result.error,'cancelled_by_owner')
        audit=json.loads((self.root/'run'/'execution.json').read_text())
        self.assertEqual(audit['session_id'],fixtures.SID)
        with self.assertRaises(ProcessLookupError):os.kill(audit['pid'],0)


if __name__=='__main__':unittest.main()
