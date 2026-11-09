"""Bounded, immutable KD-S-3 request ledger; no replay of unknown outcomes."""
import json,time,threading
from pathlib import Path
from .kd_s2_format import digest
from .kd_s2_sources import atomic
from .kd_s2_units import compact_sources
from .kd_s2 import BudgetPause

class ServicePause(RuntimeError): pass
class PriorFailure(ValueError): pass

# Optional controller-owned gate. A service failure stops new requests across
# this parallel batch; in-flight results still finish and retain their ledger.
BATCH_HALT=None

class ReservedCalls:
    """Local review sees only its allowance; the real request ledger stays shared."""
    def __init__(self,calls,reserve):self.calls,self.reserve=calls,reserve
    def remaining(self):return max(0,self.calls.remaining()-self.reserve)
    def call(self,*args,**kwargs):
        if self.remaining()==0:raise BudgetPause('本工作包额度已用完，保留功能交接额度')
        return self.calls.call(*args,**kwargs)
    def __getattr__(self,name):return getattr(self.calls,name)

class Calls:
    def __init__(self,provider,folder,identity):
        self.provider,self.folder,self.identity=provider,Path(folder),identity
        self.path=self.folder/'round-1.json'
        self.state=json.loads(self.path.read_text(encoding='utf8')) if self.path.exists() else {'requests':0,'visible':{},'calls':[],'cache_hits':0}
        for c in self.state['calls']:
            if c['status']=='requested' and not (self.folder/'calls'/(c['key']+'.json')).exists():
                raise ServicePause('此前模型请求结果未知，不能自动重复发送')

    def remaining(self):return 24-self.state['requests']

    def call(self,task,prompt,data):
        policy={'timeout':240,'max_tokens':8192 if 'review' in task else 12288}
        if task.startswith('overview') and callable(getattr(self.provider,'json',None)):policy['capture_partial']=True
        if self.identity.get('model','').startswith('deepseek-v4'):policy['reasoning_effort']='low'
        context={k:self.identity.get(k) for k in ('repo','commit','strategy','format','schema_hash','model','model_url','rule_hash','tool_hash','model_config_hash')}
        data={**data,'contract':{'strategy':'KD-S-3','format':self.identity['format'],'format_sha256':self.identity['schema_hash']}}
        key=digest([context,task,prompt,data,policy]);cache=self.folder/'calls'/(key+'.json')
        if cache.exists():
            self.state['cache_hits']+=1;atomic(self.path,self.state)
            return json.loads(cache.read_text(encoding='utf8'))
        if BATCH_HALT is not None and BATCH_HALT.is_set():raise ServicePause('同批次服务中断，停止新请求并保留当前断点')
        previous=next((c for c in self.state['calls'] if c['key']==key),None)
        if previous:raise PriorFailure(previous.get('error','此前请求失败；使用已安排的定向修复，不重复成功或失败调用'))
        additions={}
        for path,source in data.get('sources',{}).items():
            for line in source['lines']:
                k=digest([path,source['sha256'],line['line'],line['text']])
                if k not in self.state['visible']:additions[k]=len(line['text'])+1
        # Source-bearing code snippets live only in sources. Graph descriptors are
        # still charged conservatively once; do not hide copied source in metadata.
        for entry in data.get('graph',{}).get('nodes',[]):
            k=digest(['graph',entry])
            if k not in self.state['visible']:additions[k]=len(json.dumps(entry,ensure_ascii=False))
        if self.remaining()<1 or sum(self.state['visible'].values())+sum(additions.values())>200000:
            raise BudgetPause('本轮24次请求或20万新增可见字符预算已用完')
        wire={**data,'sources':compact_sources(data.get('sources',{}))}
        request_path=self.folder/'requests'/(key+'.json')
        atomic(request_path,{'task':task,'prompt':prompt,'data':data,'context':context,'policy':policy})
        record={'task':task,'key':key,'status':'requested','input_path':str(request_path.relative_to(self.folder)), 'input_sha256':digest(request_path.read_bytes())}
        self.state['requests']+=1;self.state['visible'].update(additions);self.state['calls'].append(record);atomic(self.path,self.state)
        started=time.monotonic()
        try:
            value=self.provider.json(prompt,wire,**policy) if callable(getattr(self.provider,'json',None)) else self.provider.json_background(prompt,data)
            atomic(cache,value);record['status']='received';return value
        except Exception as exc:
            record.update(status='failed',error=str(exc)[:1200],error_type=type(exc).__name__,diagnostic=getattr(exc,'diagnostic',{}))
            if getattr(exc,'response_content',None):
                atomic(self.folder/'partial-responses'/(key+'.json'),{'task':task,'content':exc.response_content,'diagnostic':record['diagnostic']})
            if isinstance(exc,ValueError) or getattr(exc,'diagnostic',{}).get('code') in ('truncated','invalid_json','empty_content','output_budget'):raise
            if BATCH_HALT is not None:BATCH_HALT.set()
            raise ServicePause(str(exc)) from exc
        finally:
            record['seconds']=round(time.monotonic()-started,3);atomic(self.path,self.state)
