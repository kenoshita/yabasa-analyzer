
import os, json, hashlib
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(os.environ.get("YABASA_DATA_DIR","data")); DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR/'metrics.json'

def _load():
  if DB_PATH.exists():
    try: return json.loads(DB_PATH.read_text(encoding='utf-8'))
    except Exception: return {'by_day':{},'by_path':{}}
  return {'by_day':{},'by_path':{}}

def _save(db): DB_PATH.write_text(json.dumps(db, ensure_ascii=False), encoding='utf-8')
def _today(): return datetime.utcnow().strftime('%Y-%m-%d')
def _anon(ip): return hashlib.sha256(('salt|'+(ip or '')).encode()).hexdigest()[:12]

def record(page_path:str, ip:str='', user_agent:str='', ref:str=''):
  db=_load(); day=_today()
  by_day=db.setdefault('by_day',{}); by_path=db.setdefault('by_path',{})
  day_entry=by_day.setdefault(day, {'views':0,'ips':[]}); day_entry['views']+=1
  ips=set(day_entry.get('ips',[])); ips.add(_anon(ip)); day_entry['ips']=list(ips)
  p=by_path.setdefault(page_path or '/', {'views':0}); p['views']+=1
  _save(db)

def summary():
  db=_load(); out={'by_day':{},'by_path':db.get('by_path',{})}
  for d,info in db.get('by_day',{}).items():
    out['by_day'][d]={'views':info.get('views',0),'unique_ips':len(set(info.get('ips',[])))}
  return out
