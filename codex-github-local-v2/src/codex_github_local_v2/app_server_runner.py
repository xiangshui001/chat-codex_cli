"""Persistent Codex app-server client with live steering and same-thread recovery."""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

from .mvp0_runner import CodexRunner, Execution, MvpError, utc_now
from .process_identity import identity
from . import __version__


class AppServerRunner:
    def __init__(self,control=lambda:[],ack=lambda *_:None):
        self.control,self.ack=control,ack

    def run(self,metadata,prompt,evidence,timeout,record):
        evidence.mkdir(parents=True,exist_ok=True,mode=0o700)
        deadline=time.monotonic()+timeout if timeout is not None else float('inf')
        thread=metadata.get('session_id');turn=None;counter=0;pending={};messages=[]
        failure=None;proc=None;reader=None;retry_at=None;retry_count=0;completed=False
        audit={**metadata,'started_at':utc_now(),'pid':None,'exit_code':None}
        incoming=queue.Queue();dispatched=set();foreign_threads=set()
        env=dict(os.environ)
        for name in ('GH_TOKEN','GITHUB_TOKEN','GH_ENTERPRISE_TOKEN','GITHUB_ENTERPRISE_TOKEN'):env.pop(name,None)
        with (evidence/'stdout.jsonl').open('a',encoding='utf-8') as log,(evidence/'stderr.log').open('ab') as stderr:
            def event(kind,**values):
                log.write(json.dumps({'type':kind,**values},ensure_ascii=False)+'\n');log.flush()
            def send(method,params,context=None):
                nonlocal counter
                counter+=1;pending[counter]=(method,context)
                proc.stdin.write((json.dumps({'id':counter,'method':method,'params':params},ensure_ascii=False)+'\n').encode());proc.stdin.flush()
                return counter
            def start_turn(text,context=None):
                send('turn/start',{'threadId':thread,'input':[{'type':'text','text':text}],
                    'model':metadata['model'],'effort':metadata['effort'],'cwd':metadata['cwd'],'approvalPolicy':'never'},context)
            try:
                proc=subprocess.Popen(metadata['argv'],cwd=metadata['cwd'],env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stderr,start_new_session=True)
                audit['pid']=proc.pid;audit['lease']=identity(proc.pid)
                (evidence/'execution.json').write_text(json.dumps(audit),encoding='utf-8')
                record('process_started',{'pid':proc.pid,'lease':audit['lease'],'at':utc_now(),'transport':'app_server'})
                def read():
                    try:
                        for line in proc.stdout:
                            incoming.put(json.loads(line))
                    except (ValueError,OSError) as exc:incoming.put({'local_error':type(exc).__name__})
                    finally:incoming.put({'eof':True})
                reader=threading.Thread(target=read,daemon=True);reader.start()
                send('initialize',{'clientInfo':{'name':'chat_codex_remote','title':'Issue remote execution','version':__version__},'capabilities':{'experimentalApi':True}})
                while True:
                    if time.monotonic()>=deadline:raise MvpError('execution_timeout')
                    for msg in self.control():
                        if msg['id'] in dispatched:continue
                        dispatched.add(msg['id'])
                        if msg['action']=='stop':
                            if turn:send('turn/interrupt',{'threadId':thread,'turnId':turn})
                            self.ack(msg['id']);raise MvpError('cancelled_by_owner')
                        if msg['action'] in {'say','allow','retry'}:
                            text=msg['text'] if msg['action']=='say' else ('Updated authorized write paths: '+msg['text'] if msg['action']=='allow' else 'Continue from retained progress; do not restart completed operations.')
                            if turn:
                                send('turn/steer',{'threadId':thread,'expectedTurnId':turn,'input':[{'type':'text','text':text}]},msg)
                            else:messages.append((text,msg))
                    if retry_at is not None and time.monotonic()>=retry_at:
                        retry_at=None
                        start_turn('The prior turn failed because of a transport/service error. Continue the same task from existing files and completed tool results. Do not repeat completed work. Resolve routine issues yourself. '+prompt)
                    try:message=incoming.get(timeout=.2)
                    except queue.Empty:
                        if completed and not pending:
                            # Give a last inbox check before closing the turn/starting publication.
                            if messages:
                                text,context=messages.pop(0);completed=False;start_turn(text,context)
                            else:break
                        continue
                    if message.get('eof'):
                        if completed:break
                        raise MvpError('codex_server_disconnected')
                    if message.get('local_error'):raise MvpError('invalid_jsonl')
                    if 'id' in message and 'method' not in message:
                        method,context=pending.pop(message['id'],('',None))
                        if 'error' in message:
                            if method=='turn/steer' and context:
                                messages.append((context['text'],context));continue
                            # A refused start/resume is visible remotely; keep server/context available for repair.
                            record('remote_recovery',{'reason':'codex_rpc_error','method':method,'rpc_error':message['error']})
                            if method in {'thread/start','thread/resume'}:raise MvpError('codex_thread_unavailable')
                            turn=None;retry_count+=1;retry_at=time.monotonic()+min(2**min(retry_count,6),60);continue
                        result=message.get('result',{})
                        if method=='initialize':
                            proc.stdin.write(b'{"method":"initialized","params":{}}\n');proc.stdin.flush()
                            params={'cwd':metadata['cwd'],'model':metadata['model'],'modelProvider':'openai','approvalPolicy':'never',
                                'sandbox':'danger-full-access' if metadata.get('full_access') else 'workspace-write'}
                            if thread:params['threadId']=thread;params['excludeTurns']=True
                            send('thread/resume' if thread else 'thread/start',params)
                        elif method in {'thread/start','thread/resume'}:
                            actual=result.get('thread',{}).get('id')
                            if not actual or (thread and actual!=thread):raise MvpError('cli_session_not_confirmed')
                            thread=actual;audit['session_id']=thread
                            event('thread.started',thread_id=thread);record('remote_session_opened',{'session_id':thread})
                            start_turn(prompt)
                        elif method in {'turn/start','turn/steer'}:
                            if method=='turn/start':turn=result.get('turn',{}).get('id',turn);completed=False
                            if context:self.ack(context['id']);record('remote_instruction_applied',{'comment_id':context['comment_id']})
                        continue
                    method=message.get('method','');params=message.get('params',{})
                    if 'id' in message:
                        # Headless, owner-authorized tasks cannot block on a local approval dialog.
                        if method=='item/tool/requestUserInput':
                            answers={q['id']:{'answers':['Use your judgment to resolve this within the authorized task and continue.']} for q in params.get('questions',[])}
                            response={'answers':answers}
                        elif 'requestApproval' in method:response={'decision':'accept'}
                        else:
                            proc.stdin.write((json.dumps({'id':message['id'],'error':{'code':-32601,'message':'Unsupported server request'}})+'\n').encode());proc.stdin.flush();continue
                        proc.stdin.write((json.dumps({'id':message['id'],'result':response})+'\n').encode());proc.stdin.flush();continue
                    if method in {'turn/started','turn/completed','item/completed','error','item/commandExecution/outputDelta'}:
                        # Descendant agents share this stream; only our current root turn controls completion.
                        notification_thread=params.get('threadId')
                        if notification_thread!=thread:
                            if notification_thread and notification_thread not in foreign_threads:
                                foreign_threads.add(notification_thread)
                                record('remote_foreign_thread_ignored',{'thread_id':notification_thread})
                            continue
                        notification_turn=params.get('turn',{}).get('id') if method.startswith('turn/') else params.get('turnId')
                        if not notification_turn:continue
                        if method=='turn/started':
                            if turn is not None and notification_turn!=turn:continue
                        elif turn is None or notification_turn!=turn:
                            continue
                    if method=='turn/started':
                        turn=params.get('turn',{}).get('id',turn);event('turn.started');record('remote_turn_started',{'turn_id':turn})
                    elif method=='item/completed':
                        item=dict(params.get('item',{}));kind=item.get('type')
                        mapping={'agentMessage':'agent_message','commandExecution':'command_execution','fileChange':'file_change','plan':'plan','mcpToolCall':'mcp_tool_call'}
                        item['type']=mapping.get(kind,kind)
                        if kind=='commandExecution':
                            item['aggregated_output']=item.get('aggregatedOutput','')
                            item['exit_code']=item.get('exitCode')
                        event('item.completed',item=item,thread_id=thread,turn_id=turn)
                        if kind=='fileChange':record('remote_file_change',{'changes':[c.get('path') for c in item.get('changes',[])]})
                        if kind=='agentMessage' and item.get('text'):
                            record('remote_agent_message',{'text':item['text'],'item_id':item.get('id'),'phase':item.get('phase')})
                    elif method=='turn/completed':
                        ended=params.get('turn',{});turn=None
                        if ended.get('status')=='completed':
                            retry_at=None;retry_count=0
                            event('turn.completed');completed=True
                            if messages:
                                text,context=messages.pop(0);completed=False;start_turn(text,context)
                        elif ended.get('status')=='interrupted':raise MvpError('cancelled_by_owner')
                        else:
                            retry_count+=1;retry_at=time.monotonic()+min(2**min(retry_count,6),60)
                            event('error',message='Turn temporarily failed; retaining thread and retrying.')
                            record('remote_recovery',{'reason':'codex_turn_failed','retry':retry_count,'turn_error':ended.get('error')})
                    elif method=='error':
                        # An error notification may explicitly say a retry is in flight.
                        record('remote_transport_error',{'will_retry':params.get('willRetry',False)})
                    elif method=='item/commandExecution/outputDelta':
                        event('item.updated',item={'id':params.get('itemId'),'type':'command_execution','aggregated_output':params.get('delta','')})
            except KeyboardInterrupt:
                failure='interrupted'
            except (BrokenPipeError,OSError):failure='codex_server_disconnected'
            except MvpError as exc:failure=str(exc)
            finally:
                if proc is not None:
                    CodexRunner._stop_group(proc);audit['cleanup']='process_group_terminated';audit['exit_code']=proc.returncode
                    if proc.stdin is not None:
                        try:proc.stdin.close()
                        except OSError:pass
                    if reader is not None:reader.join(timeout=1)
                    if proc.stdout is not None and (reader is None or not reader.is_alive()):proc.stdout.close()
                audit.update(finished_at=utc_now(),error=failure,session_id=thread)
                text=json.dumps(audit,ensure_ascii=False,indent=2)
                (evidence/('execution-'+str(time.time_ns())+'.json')).write_text(text,encoding='utf-8')
                (evidence/'execution.json').write_text(text,encoding='utf-8')
        return Execution(1 if failure else 0,failure)
