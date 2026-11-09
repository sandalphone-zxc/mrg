"""Embedding protocol; keyword-only usage needs no model or network library."""
from typing import Protocol

class ProviderError(RuntimeError):
    pass

class EmbeddingProvider(Protocol):
    def status(self) -> dict: ...
    def vector_identity(self) -> str: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...

class KeywordOnlyProvider:
    def status(self):return {'embedding_configured':False}
    def vector_identity(self):return 'disabled'
    def embed(self, texts):raise ProviderError('Embedding is disabled')

class OpenAIEmbeddingProvider:
    """Explicit opt-in HTTP adapter. No credential persistence or automatic retries."""
    def __init__(self, endpoint, model, api_key, *, timeout=60, client=None):
        from urllib.parse import urlsplit
        parsed=urlsplit(endpoint)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise ValueError('Use an HTTPS embeddings endpoint without embedded credentials')
        if not model or not api_key:raise ValueError('Embedding model and API key are required')
        self.endpoint,self.model,self.api_key=endpoint,model,api_key
        self.timeout,self.client=timeout,client
        self.last_usage=None

    def status(self):return {'embedding_configured':True}
    def vector_identity(self):return self.endpoint+'|'+self.model

    def embed(self,texts):
        import httpx
        import numpy as np
        self.last_usage=None
        if not texts:return []
        payload={'model':self.model,'input':texts}
        try:
            if self.client is None:
                with httpx.Client(trust_env=False,follow_redirects=False) as client:
                    response=client.post(self.endpoint,headers={'Authorization':'Bearer '+self.api_key},json=payload,timeout=self.timeout)
            else:
                response=self.client.post(self.endpoint,headers={'Authorization':'Bearer '+self.api_key},json=payload,timeout=self.timeout)
        except httpx.HTTPError:
            raise ProviderError('Embedding transport failed; result and usage unknown; no automatic retry') from None
        if not response.is_success:raise ProviderError(f'Embedding HTTP {response.status_code}; no automatic retry')
        try:
            body=response.json();self.last_usage=body.get('usage')
            rows=sorted(body['data'],key=lambda r:r['index'])
            if [r['index'] for r in rows]!=list(range(len(texts))):raise ValueError()
            vectors=np.asarray([r['embedding'] for r in rows],dtype=float)
            if vectors.ndim!=2 or vectors.shape[1]==0 or not np.isfinite(vectors).all() or np.any(np.linalg.norm(vectors,axis=1)==0):raise ValueError()
            return vectors.tolist()
        except (ValueError,KeyError,TypeError,AttributeError):
            raise ProviderError('Embedding response has invalid count, dimensions or values') from None
