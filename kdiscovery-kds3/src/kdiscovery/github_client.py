"""Public GitHub reads with encrypted optional credentials, cache and durable backoff."""
import hashlib
import json
import threading
import time
from contextvars import ContextVar
from urllib.parse import urlsplit
import httpx
from .providers import ProviderError

active_client=ContextVar('github_client',default=None)
request_gate=ContextVar('github_request_gate',default=None)


class GithubUnavailable(ProviderError):
    def __init__(self,reason,kind='rate_limited',retry_at=None):
        super().__init__(reason);self.kind=kind;self.retry_at=retry_at
    def info(self):return {'kind':self.kind,'retry_at':self.retry_at,'message':str(self)}


class GithubClient:
    def __init__(self,configuration,before_request=None):
        self.configuration=configuration;self.store=configuration.store
        self.before_request=before_request
        self.lock=threading.RLock();self.last=0
        with self.store.connect() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS github_cache(key TEXT PRIMARY KEY,expires REAL,body BLOB); CREATE TABLE IF NOT EXISTS github_backoff(key TEXT PRIMARY KEY,payload TEXT);')
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def identity(self):
        token=self.configuration.private().get('github_key','')
        return token,hashlib.sha256(token.encode()).hexdigest()
    def get(self,url,params=None,check=False):
        parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.hostname not in ('api.github.com','raw.githubusercontent.com') or parsed.username or parsed.port not in (None,443):raise ValueError('GitHub 请求地址不允许')
        address=str(httpx.URL(url,params=params));token,identity=self.identity()
        key=hashlib.sha256((identity+address).encode()).hexdigest()
        with self.lock:
            gate=request_gate.get()
            if gate:gate()
            with self.store.connect() as db:
                cached=db.execute('SELECT body FROM github_cache WHERE key=? AND expires>?',(key,time.time())).fetchone()
                backoff=db.execute('SELECT payload FROM github_backoff WHERE key=?',(identity,)).fetchone()
            if cached and not check:return httpx.Response(200,content=cached[0],request=httpx.Request('GET',address))
            block=json.loads(backoff[0]) if backoff else {}
            if block and (not check or block['kind']=='rate_limited'):
                if not block.get('retry_at') or block['retry_at']>time.time():raise GithubUnavailable(block['message'],block['kind'],block.get('retry_at'))
            time.sleep(max(0,1-(time.monotonic()-self.last)))
            if gate:gate()
            if self.before_request:self.before_request()
            headers={'User-Agent':'MRG-Project','Accept':'application/vnd.github+json'}
            if token and parsed.hostname=='api.github.com':headers['Authorization']='Bearer '+token
            try:
                with httpx.Client(timeout=20,trust_env=False,follow_redirects=False) as client:r=client.get(address,headers=headers)
            except httpx.HTTPError:raise GithubUnavailable('GitHub 网络连接失败，已保留进度，请检查网络后继续。','network',time.time()+60) from None
            finally:self.last=time.monotonic()
            if r.status_code in (401,403,429):
                limited=r.status_code==429 or r.headers.get('x-ratelimit-remaining')=='0' or 'retry-after' in r.headers or 'rate limit' in r.text[:2000].lower()
                retry=None
                if limited:
                    values=[time.time()+min(3600,60*2**min(block.get('attempts',0),6))]
                    try:
                        if r.headers.get('retry-after'):values.append(time.time()+float(r.headers['retry-after']))
                        if r.headers.get('x-ratelimit-remaining')=='0':values.append(float(r.headers.get('x-ratelimit-reset',0))+1)
                    except ValueError:pass
                    retry=max(values)
                error=GithubUnavailable('GitHub 请求额度受限，已暂停并保存进度。' if limited else 'GitHub 拒绝访问，请检查 Token 是否有效及访问权限。','rate_limited' if limited else 'access_denied',retry)
                with self.store.connect() as db:db.execute('INSERT OR REPLACE INTO github_backoff VALUES(?,?)',(identity,json.dumps({**error.info(),'attempts':block.get('attempts',0)+1})))
                raise error
            r.raise_for_status()
            if check:
                with self.store.connect() as db:db.execute('DELETE FROM github_backoff WHERE key=?',(identity,))
            elif len(r.content)<=8_000_000:
                ttl=604800 if parsed.hostname=='raw.githubusercontent.com' else 3600
                with self.store.connect() as db:db.execute('INSERT OR REPLACE INTO github_cache VALUES(?,?,?)',(key,time.time()+ttl,r.content))
            return r
    def test(self):
        try:
            data=self.get('https://api.github.com/rate_limit',check=True).json();token,_=self.identity()
            quotas={k:{f:data.get('resources',{}).get(k,{}).get(f) for f in ('limit','remaining','reset')} for k in ('core','search')}
            return {'ok':True,'authenticated':bool(token),'quotas':quotas,'message':'GitHub 连接成功；额度为当前查询结果，实际请求响应头优先。'}
        except GithubUnavailable as e:return {'ok':False,**e.info()}
        except (httpx.HTTPError,ValueError):return {'ok':False,'message':'GitHub 连接测试失败，请检查网络与配置。'}
