"""Adapt a request only after the provider rejects its context window; retain the full archive."""
import copy
import json


def request_view(history,budget):
    groups=[]
    for index,message in enumerate(history):
        if message.get('role')=='tool' and groups:groups[-1].append((index,message))
        else:groups.append([(index,message)])
    selected=[];used=0
    for group in reversed(groups):
        packed=[]
        for index,original in group:
            item=copy.deepcopy(original)
            content=item.get('content')
            if isinstance(content,str) and len(content)>max(1,budget//4):
                excerpt=max(1,budget//8)
                item['content']=content[:excerpt]+f'\n[Full content retained in session history entry {index}; use read_session_history with byte offset/length. This request was shortened only after the provider rejected its context window.]\n'+content[-excerpt:]
            packed.append(item)
        size=len(json.dumps(packed,ensure_ascii=False))
        if selected and used+size>budget:break
        selected=packed+selected;used+=size
    first_system=next((m for m in history if m.get('role')=='system'),None)
    first_user=next(((i,m) for i,m in enumerate(history) if m.get('role')=='user'),None)
    prefix=[]
    if first_system and first_system not in selected:prefix.append(first_system)
    if first_user and first_user[1] not in selected:
        index,message=first_user
        excerpt=max(1,budget//8)
        prefix.append({'role':'user','content':message.get('content','')[:excerpt]+f'\n[Original task retained in full at session history entry {index}; retrieve it in chunks when needed.]'})
    return prefix+[{'role':'system','content':'The provider context window rejected the full request. Complete history is preserved on disk. Use read_session_history to retrieve omitted entries. Continue completed work rather than restarting it.'}]+selected
