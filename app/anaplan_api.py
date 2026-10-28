import base64, logging, os
import requests
from credentials import load_credentials
log=logging.getLogger(__name__)

class AnaplanAPI:
    def __init__(self):
        self.auth_url=os.getenv('ANAPLAN_AUTH_URL','https://auth.anaplan.com/token/authenticate')
        self.api_base=os.getenv('ANAPLAN_API_BASE_URL','https://api.anaplan.com/2/0').rstrip('/')
        self.email,self.password=load_credentials()
        self.mode=os.getenv('ANAPLAN_AUTH_MODE','browser').strip().lower()
        self.token=None

    @property
    def discovery_enabled(self): return self.mode=='basic'

    def authenticate(self):
        if self.mode!='basic':
            log.info('API discovery disabled (ANAPLAN_AUTH_MODE=%s); using configured IDs/names.', self.mode)
            return False
        if not self.email or not self.password:
            raise RuntimeError('Basic API discovery requires ANAPLAN_EMAIL and ANAPLAN_PASSWORD in .env.')
        raw=base64.b64encode(f'{self.email}:{self.password}'.encode()).decode()
        r=requests.post(self.auth_url,headers={'Authorization':f'Basic {raw}'},timeout=30)
        r.raise_for_status(); data=r.json()
        self.token=data.get('tokenInfo',{}).get('tokenValue')
        if not self.token: raise RuntimeError('Anaplan authentication succeeded without a tokenValue.')
        log.info('Anaplan API authentication successful for discovery/validation.')
        return True

    def _get(self,path):
        if not self.token: self.authenticate()
        r=requests.get(f'{self.api_base}{path}',headers={'Authorization':f'AnaplanAuthToken {self.token}'},timeout=30)
        r.raise_for_status(); return r.json()

    @staticmethod
    def _items(payload):
        if isinstance(payload,list): return payload
        if not isinstance(payload,dict): return []
        for key in ('models','workspaces','items'):
            if isinstance(payload.get(key),list): return payload[key]
        return []

    def models(self): return self._items(self._get('/models'))

    def workspace_usage(self, workspace_id):
        """Return percent/size data when the tenant API exposes it, otherwise None."""
        if not self.discovery_enabled:
            return None
        payload=self._get(f'/workspaces/{workspace_id}')
        data=payload.get('workspace',payload) if isinstance(payload,dict) else {}
        used=next((data.get(key) for key in ('currentSize','size','usedSize')
                   if isinstance(data.get(key),(int,float))),None)
        limit=next((data.get(key) for key in ('sizeAllowance','maxSize','capacity')
                    if isinstance(data.get(key),(int,float))),None)
        percent=data.get('usagePercent')
        if not isinstance(percent,(int,float)) and used is not None and limit:
            percent=used/limit*100
        if not isinstance(percent,(int,float)):
            return None
        return {'percent':round(float(percent),2),'used':used,'limit':limit}

    def resolve(self,target):
        if target.workspace_id and target.model_id:
            return target
        if not self.discovery_enabled:
            return target
        models=self.models()
        matches=[]
        for m in models:
            mn=m.get('name') or m.get('modelName')
            mid=m.get('id') or m.get('modelId')
            wid=m.get('currentWorkspaceId') or m.get('workspaceId')
            wn=m.get('currentWorkspaceName') or m.get('workspaceName')
            model_ok=(target.model_id and mid==target.model_id) or (not target.model_id and mn==target.model)
            ws_ok=(target.workspace_id and wid==target.workspace_id) or (not target.workspace_id and (not target.workspace or wn==target.workspace))
            if model_ok and ws_ok: matches.append((m,wn,wid,mn,mid))
        if len(matches)!=1:
            raise RuntimeError(f'Expected exactly one API model match for {target.workspace!r}/{target.model!r}; found {len(matches)}.')
        _,wn,wid,mn,mid=matches[0]
        return target.__class__(wn or target.workspace,mn or target.model,wid,mid,target.tags)
