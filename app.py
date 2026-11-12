"""MTB Module 01 – runnable reference implementation; see README for production gaps."""
import os, json, sqlite3, secrets, hashlib, hmac, re, time, base64, uuid, logging, contextvars
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
from typing import Optional
import jwt
import mailer
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import FastAPI, Request, HTTPException, Response, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

ROOT=Path(__file__).resolve().parent

def load_env(path):
    """Read KEY=value lines from a local .env file; real environment variables win."""
    if not path.is_file():return
    for line in path.read_text(encoding='utf-8').splitlines():
        line=line.strip()
        if line and not line.startswith('#') and '=' in line:
            k,v=line.split('=',1);os.environ.setdefault(k.strip(),v.strip().strip('"\''))
load_env(ROOT/'.env')
DB=Path(os.getenv('MTB_DB',str(ROOT/'mtb.sqlite3')))
SECRET=os.getenv('MTB_SECRET','')
DEV=os.getenv('MTB_DEV_MODE','0')=='1'
if not SECRET and not DEV: raise RuntimeError('MTB_SECRET is required outside dev mode')
if not SECRET: SECRET='demo-only-please-change-in-production'
COOKIE_SECURE=not DEV
# Browser key for Google Maps JavaScript API + Places API (New). Restrict it by HTTP referrer in Google Cloud.
MAPS_KEY=os.getenv('MTB_GOOGLE_MAPS_KEY','').strip()
UPLOADS=Path(os.getenv('MTB_UPLOADS',str(ROOT/'uploads')))
hasher=PasswordHasher(time_cost=2,memory_cost=32768,parallelism=2)
DUMMY_HASH=hasher.hash('timing-equalizer-Aa!')
app=FastAPI(title='MTB Registration & Identity API', version='0.2.0')

class RedactTokens(logging.Filter):
    """Masks invitation tokens in request-log lines, e.g. /?invite=<token> and /api/invitation/<token>/respond."""
    PATTERN=re.compile(r'(invite=|/api/invitation/)[A-Za-z0-9_\-]{16,}')
    def filter(self,record):
        if isinstance(record.args,tuple):
            record.args=tuple(self.PATTERN.sub(r'\1[redacted]',a) if isinstance(a,str) else a for a in record.args)
        return True
logging.getLogger('uvicorn.access').addFilter(RedactTokens())

# BRD 3.1 / 3.2 / 4.1 option lists. "Others" must carry a specified value ("Others: ...").
ORG_TYPES=('Sponsor','CRO','SMO','Site / Hospital / Institution')
CLOSED_LINKS=('rejected','removed')  # hospital-SMO links the SMO may request again
# Roles an Org Admin may give when inviting; 'Others: <text>' is also allowed. Sent to the page through /api/config.
MEMBER_ROLES={'Sponsor':['Org Admin','Research Team'],'CRO':['Org Admin','Research Team'],
              'SMO':['Org Admin','PI','Research Team'],'Site / Hospital / Institution':['Org Admin','PI','Research Team']}
PI_LINK_ROLES=['PI','Research Team']  # roles for SMO-PI invitations
INVITE_DAYS=7
CATEGORIES={
    'Sponsor':['Pharmaceutical','Biotechnology','Medical Device','Academic Institution','Government Agency','CRO as Sponsor','Hospital/Healthcare Institution','Investigator-Initiated','Foundation/Trust'],
    'CRO':['Clinical Trials','BA-BE','Clinical Trials and BA-BE','Biotechnology','HEOR','Preclinical','Bioanalytical'],
    'Site / Hospital / Institution':['Private','Government','Trust','Academic'],
}
HOSPITAL_TYPES=['Government','Private','Trust','Academic']
SALUTATIONS=['Dr.','Prof.','Mr.','Ms.','Mrs.']
GENDERS=['Male','Female','Other']

# IP and device of the request being handled, so every audit record can carry them (BRD 18.2).
REQUEST_INFO=contextvars.ContextVar('request_info',default=(None,None))

# Until an SMS provider is connected, a sign-up phone code can be shown to the person on their own verification screen.
PHONE_CODE_ON_SCREEN=os.getenv('MTB_PHONE_CODE_ON_SCREEN','0')=='1'
SESSION_HOURS=float(os.getenv('MTB_SESSION_HOURS','8'))          # BRD 10.4.1: configurable session expiry
FORCE_HTTPS=os.getenv('MTB_FORCE_HTTPS','0' if DEV else '1')=='1'  # BRD 10.4.1: HTTPS outside local test mode

@app.middleware('http')
async def no_store(request:Request,call_next):
    REQUEST_INFO.set((request.client.host if request.client else None,request.headers.get('user-agent','')[:200] or None))
    if FORCE_HTTPS and request.headers.get('x-forwarded-proto',request.url.scheme)=='http' and request.url.hostname not in ('127.0.0.1','localhost'):
        return RedirectResponse(str(request.url.replace(scheme='https')),308)
    # BRD 10.4.3: browser back/cache must not restore authenticated data after logout.
    resp=await call_next(request)
    if FORCE_HTTPS:resp.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
    if request.url.path.startswith('/api') or request.url.path=='/':resp.headers['Cache-Control']='no-store'
    return resp

@contextmanager
def db():
    conn=sqlite3.connect(str(DB),timeout=15)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
        conn.commit()
    except:
        conn.rollback(); raise
    finally: conn.close()

def init_db():
    DB.parent.mkdir(parents=True,exist_ok=True)
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,first TEXT NOT NULL,middle TEXT,last TEXT NOT NULL,salutation TEXT,gender TEXT,designation TEXT,email TEXT UNIQUE NOT NULL,alt_email TEXT,phone TEXT,alt_phone TEXT,password_hash TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',email_verified INTEGER DEFAULT 0,phone_verified INTEGER DEFAULT 0,failed INTEGER DEFAULT 0,locked_until INTEGER DEFAULT 0,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS organizations(id INTEGER PRIMARY KEY,name TEXT NOT NULL,normalized TEXT NOT NULL,type TEXT NOT NULL,subtype TEXT,acronym TEXT,phone TEXT,address1 TEXT,address2 TEXT,city TEXT,state TEXT,country TEXT,pin TEXT,website TEXT,legal_doc TEXT,status TEXT DEFAULT 'pending',created TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS org_lookup ON organizations(normalized,city);
        CREATE TABLE IF NOT EXISTS memberships(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),org_id INTEGER NOT NULL REFERENCES organizations(id),role TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',created TEXT NOT NULL, UNIQUE(user_id,org_id));
        CREATE TABLE IF NOT EXISTS hospitals(id INTEGER PRIMARY KEY,name TEXT NOT NULL,normalized TEXT NOT NULL,type TEXT NOT NULL,address1 TEXT NOT NULL,address2 TEXT,city TEXT NOT NULL,state TEXT NOT NULL,country TEXT NOT NULL,pin TEXT NOT NULL,phone TEXT,website TEXT,org_id INTEGER REFERENCES organizations(id),provisional INTEGER NOT NULL DEFAULT 1,created TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS hospital_lookup ON hospitals(normalized,city);
        CREATE TABLE IF NOT EXISTS hospital_links(id INTEGER PRIMARY KEY,smo_org_id INTEGER NOT NULL REFERENCES organizations(id),hospital_id INTEGER NOT NULL REFERENCES hospitals(id),status TEXT NOT NULL,requested_by INTEGER REFERENCES users(id),created TEXT NOT NULL, UNIQUE(smo_org_id,hospital_id));
        CREATE TABLE IF NOT EXISTS pi_links(id INTEGER PRIMARY KEY,smo_org_id INTEGER NOT NULL REFERENCES organizations(id),hospital_id INTEGER NOT NULL REFERENCES hospitals(id),user_id INTEGER NOT NULL REFERENCES users(id),status TEXT DEFAULT 'active',created TEXT NOT NULL,UNIQUE(smo_org_id,hospital_id,user_id));
        CREATE TABLE IF NOT EXISTS invitations(id INTEGER PRIMARY KEY,token_hash TEXT UNIQUE NOT NULL,org_id INTEGER NOT NULL REFERENCES organizations(id),hospital_id INTEGER REFERENCES hospitals(id),kind TEXT NOT NULL,role TEXT NOT NULL,full_name TEXT NOT NULL,email TEXT NOT NULL,phone TEXT,designation TEXT,department TEXT,status TEXT NOT NULL DEFAULT 'pending',invited_by INTEGER NOT NULL REFERENCES users(id),expires INTEGER NOT NULL,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS otps(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),channel TEXT NOT NULL,purpose TEXT NOT NULL,code_hash TEXT NOT NULL,expires INTEGER NOT NULL,attempts INTEGER DEFAULT 0,used INTEGER DEFAULT 0,created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),csrf TEXT NOT NULL,expires INTEGER NOT NULL,revoked INTEGER DEFAULT 0,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,actor_id INTEGER,action TEXT NOT NULL,subject_type TEXT,subject_id INTEGER,org_id INTEGER,details TEXT,ip TEXT,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY,target TEXT,kind TEXT,body TEXT,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS consents(id INTEGER PRIMARY KEY,user_id INTEGER,org_id INTEGER,kind TEXT,version TEXT,accepted_at TEXT);
        CREATE TABLE IF NOT EXISTS login_attempts(email_hash TEXT PRIMARY KEY,failed INTEGER NOT NULL DEFAULT 0,locked_until INTEGER NOT NULL DEFAULT 0,updated INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS join_requests(id INTEGER PRIMARY KEY,org_id INTEGER NOT NULL REFERENCES organizations(id),full_name TEXT NOT NULL,email TEXT NOT NULL,phone TEXT,message TEXT,status TEXT NOT NULL DEFAULT 'pending',ip TEXT,created INTEGER NOT NULL);
        -- Ownership claims. kind="organization": user_id claims org_id. kind="hospital": org_id (a Site) claims a provisional hospital_id.
        CREATE TABLE IF NOT EXISTS claims(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,org_id INTEGER NOT NULL REFERENCES organizations(id),hospital_id INTEGER REFERENCES hospitals(id),user_id INTEGER NOT NULL REFERENCES users(id),status TEXT NOT NULL,method TEXT,deadline INTEGER,objected_by INTEGER,objection TEXT,decided_by INTEGER,note TEXT,details TEXT,created TEXT NOT NULL,decided TEXT);
        ''')
        add_columns(c,'users',[('email_verified_at','TEXT'),('phone_verified_at','TEXT'),('alt_email_verified','INTEGER DEFAULT 0'),('alt_email_verified_at','TEXT')])
        add_columns(c,'hospitals',[('acronym','TEXT')])
        add_columns(c,'pi_links',[('role',"TEXT DEFAULT 'PI'")])
        add_columns(c,'memberships',[('designation','TEXT'),('department','TEXT')])
        add_columns(c,'audit',[('hospital_id','INTEGER'),('trial_id','INTEGER'),('row_hash','TEXT')])
        add_columns(c,'outbox',[('subject','TEXT'),('status','TEXT'),('provider_id','TEXT'),('error','TEXT')])
        protect_audit(c)
        # Duplicate-detection signals (filled by set_signals / backfill_signals).
        add_columns(c,'organizations',[('exact_key','TEXT'),('match_key','TEXT'),('city_key','TEXT'),('initials','TEXT'),('domain','TEXT'),('phone_digits','TEXT'),('place_id','TEXT')])
        add_columns(c,'hospitals',[('match_key','TEXT'),('city_key','TEXT'),('domain','TEXT'),('place_id','TEXT')])

AUDIT_FIELDS=('id','actor_id','action','subject_type','subject_id','org_id','hospital_id','trial_id','details','ip','created')

def audit_hash(prev,row):
    """Each record's seal covers its own content and the previous record's seal, keyed with MTB_SECRET."""
    msg=json.dumps([prev]+[row[k] for k in AUDIT_FIELDS],separators=(',',':'),default=str)
    return hmac.new(SECRET.encode(),msg.encode(),hashlib.sha256).hexdigest()

def protect_audit(c):
    """BRD 18.2.1: audit records cannot be edited or deleted; the only allowed change is sealing a new record once."""
    c.executescript('''
        CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'Audit records cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
        WHEN NOT (OLD.row_hash IS NULL AND NEW.row_hash IS NOT NULL AND NEW.id IS OLD.id AND NEW.actor_id IS OLD.actor_id AND NEW.action IS OLD.action
                  AND NEW.subject_type IS OLD.subject_type AND NEW.subject_id IS OLD.subject_id AND NEW.org_id IS OLD.org_id AND NEW.hospital_id IS OLD.hospital_id
                  AND NEW.trial_id IS OLD.trial_id AND NEW.details IS OLD.details AND NEW.ip IS OLD.ip AND NEW.created IS OLD.created)
        BEGIN SELECT RAISE(ABORT,'Audit records cannot be changed'); END;''')
    prev=None  # seal records written before sealing existed, in order
    for r in c.execute('SELECT * FROM audit ORDER BY id').fetchall():
        if r['row_hash'] is None:c.execute('UPDATE audit SET row_hash=? WHERE id=?',(audit_hash(prev,r),r['id']));prev=audit_hash(prev,r)
        else:prev=r['row_hash']

def verify_audit_chain(c):
    """Recomputes every seal; any edited, inserted or removed record breaks the chain from that point."""
    prev,n=None,0
    for r in c.execute('SELECT * FROM audit ORDER BY id'):
        n+=1
        if r['row_hash']!=audit_hash(prev,r):return {'ok':False,'records':n,'first_bad_id':r['id']}
        prev=r['row_hash']
    return {'ok':True,'records':n,'first_bad_id':None}

def add_columns(c,table,cols):
    have={r['name'] for r in c.execute(f'PRAGMA table_info({table})')}
    for name,decl in cols:
        if name not in have:c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {decl}')
init_db()

def now(): return datetime.now(timezone.utc).isoformat()
def ts(): return int(time.time())
def clean(v):return str(v or '').strip()
def norm(v):return re.sub(r'\s+',' ',clean(v).casefold())
def email(v):
    v=clean(v).lower()
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',v): raise HTTPException(422,'Enter a valid email address')
    return v

def require(cond,message,status=422):
    if not cond: raise HTTPException(status,message)
def password_valid(p):return len(p)>=8 and bool(re.search('[A-Z]',p)) and bool(re.search('[a-z]',p)) and bool(re.search('[^A-Za-z0-9]',p))
def phone(v,label='phone number'):
    v=clean(v)
    require(re.fullmatch(r'\+?[0-9 ()-]{7,20}',v) and 7<=len(re.sub(r'\D','',v))<=15,f'Enter a valid {label}')
    return v
def website(v):
    v=clean(v)
    if v:require(re.fullmatch(r'https?://[^\s/$.?#][^\s]*',v,re.I),'Website must start with http:// or https://')
    return v
def option(value,allowed,label):
    """Accept a listed value, or 'Others: <text>' (BRD 3.3 custom value stored on this record)."""
    value=clean(value)
    if value in allowed:return value
    m=re.fullmatch(r'Others:\s*(.{2,80})',value)
    if not m:raise HTTPException(422,f'Select a valid {label} or specify "Others"')
    return 'Others: '+m.group(1).strip()
def categories(typ,raw):
    if typ not in CATEGORIES:return ''
    values=raw if isinstance(raw,list) else [raw] if clean(raw) else []
    values=[option(v,CATEGORIES[typ],'organization category') for v in values]
    require(values,'Select the organization category')
    require(typ=='Sponsor' or len(values)==1,'Select one organization category')
    return '; '.join(dict.fromkeys(values))

DOC_TYPES={b'%PDF':'pdf',b'\x89PNG':'png',b'\xff\xd8\xff':'jpg'}
def save_document(doc):
    """BRD 3.1 legal/institutional document: PDF/PNG/JPG up to 5 MB, type checked by content."""
    if not doc:return None
    try:data=base64.b64decode(str(doc.get('data','')).split(',')[-1],validate=True)
    except Exception:raise HTTPException(422,'Document upload could not be read')
    require(0<len(data)<=5*1024*1024,'Document must be 5 MB or smaller')
    ext=next((e for magic,e in DOC_TYPES.items() if data.startswith(magic)),None)
    require(ext,'Document must be a PDF, PNG or JPG file')
    UPLOADS.mkdir(parents=True,exist_ok=True)
    name=f'{uuid.uuid4().hex}.{ext}'
    (UPLOADS/name).write_bytes(data)  # Production: malware scan + private object storage.
    return name

def attempts(c,e):
    h=hashlib.sha256(e.encode()).hexdigest()
    r=c.execute('SELECT failed,locked_until FROM login_attempts WHERE email_hash=?',(h,)).fetchone()
    return h,(r['failed'] if r else 0),(r['locked_until'] if r else 0)
def set_attempts(c,h,failed,locked):
    c.execute('INSERT INTO login_attempts(email_hash,failed,locked_until,updated) VALUES(?,?,?,?) ON CONFLICT(email_hash) DO UPDATE SET failed=excluded.failed,locked_until=excluded.locked_until,updated=excluded.updated',(h,failed,locked,ts()))
def client_info(request):
    return (request.client.host if request.client else None),{'device':request.headers.get('user-agent','')[:200]}
def audit(c,actor,action,subtype=None,subid=None,orgid=None,details=None,ip=None,hospital_id=None):
    """Append one audit record (BRD 18). Never pass passwords, codes or tokens in details."""
    req_ip,device=REQUEST_INFO.get()
    details=dict(details or {})
    if device and 'device' not in details:details['device']=device
    if hospital_id is None and subtype=='hospital':hospital_id=subid
    cur=c.execute('INSERT INTO audit(actor_id,action,subject_type,subject_id,org_id,hospital_id,details,ip,created) VALUES(?,?,?,?,?,?,?,?,?)',
                  (actor,action,subtype,subid,orgid,hospital_id,json.dumps(details),ip or req_ip,now()))
    row=c.execute('SELECT * FROM audit WHERE id=?',(cur.lastrowid,)).fetchone()
    prev=c.execute('SELECT row_hash FROM audit WHERE id<? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
    c.execute('UPDATE audit SET row_hash=? WHERE id=?',(audit_hash(prev['row_hash'] if prev else None,row),row['id']))
def otp_hash(uid,code,purpose):return hmac.new(SECRET.encode(),f'{uid}:{purpose}:{code}'.encode(),hashlib.sha256).hexdigest()
def send_otp(c,uid,target,channel,purpose):
    # BRD 8.2 email: 5 sends / hour. BRD 8.3 phone: 3 sends / 30 min and 10 / 24 h.
    current=ts(); is_phone=channel=='phone'; window=1800 if is_phone else 3600; cap=3 if is_phone else 5
    count=lambda since:c.execute('SELECT COUNT(*) n FROM otps WHERE user_id=? AND channel=? AND created>?',(uid,channel,since)).fetchone()['n']
    require(count(current-window)<cap,'OTP sending limit reached. Try again later.',429)
    if is_phone:require(count(current-86400)<10,'Daily SMS code limit reached. Try again tomorrow.',429)
    code=f'{secrets.randbelow(1000000):06d}'
    c.execute('UPDATE otps SET used=1 WHERE user_id=? AND channel=? AND purpose=?',(uid,channel,purpose))
    c.execute('INSERT INTO otps(user_id,channel,purpose,code_hash,expires,created) VALUES(?,?,?,?,?,?)',(uid,channel,purpose,otp_hash(uid,code,purpose),current+900,current))
    if channel=='phone':outbox(c,target,f'My Trial Board code: {code}. Valid for 15 minutes. Do not share it.','phone')  # SMS provider not chosen yet
    else:
        subject,text=OTP_TEXT.get(purpose,('Your My Trial Board code','Your My Trial Board code is {code}. It expires in 15 minutes.'))
        outbox(c,target,text.format(code=code),channel,subject=subject,critical=True)
    return code

def verify_otp(c,uid,channel,purpose,code):
    o=c.execute('SELECT * FROM otps WHERE user_id=? AND channel=? AND purpose=? AND used=0 ORDER BY id DESC LIMIT 1',(uid,channel,purpose)).fetchone()
    require(o is not None and o['expires']>=ts(),'Invalid or expired code',400)
    max_attempts=3 if channel=='phone' else 5
    if o['attempts']>=max_attempts: raise HTTPException(429,'Too many attempts')
    correct=hmac.compare_digest(o['code_hash'],otp_hash(uid,clean(code),purpose))
    c.execute('UPDATE otps SET attempts=attempts+1,used=? WHERE id=?',(1 if correct or o['attempts']+1>=max_attempts else 0,o['id']))
    if not correct:
        c.commit()  # keep the attempt count: the error below rolls back everything not yet saved (BRD 8.2: 5 tries per code)
        raise HTTPException(400,'Invalid or expired code')

def auth(request:Request,c,csrf=False):
    token=request.cookies.get('mtb_session')
    try:
        payload=jwt.decode(token or '',SECRET,algorithms=['HS256']); sid=payload['sid']
    except Exception: raise HTTPException(401,'Please log in')
    s=c.execute('SELECT * FROM sessions WHERE id=? AND revoked=0 AND expires>?',(sid,ts())).fetchone()
    if not s: raise HTTPException(401,'Session expired')
    if csrf: require(hmac.compare_digest(request.headers.get('x-csrf-token',''),s['csrf']),'Invalid CSRF token',403)
    u=c.execute('SELECT * FROM users WHERE id=?',(s['user_id'],)).fetchone()
    require(u and u['status']=='active','Account unavailable',403)
    return u,s

def membership(c,uid,oid,admin=False):
    m=c.execute('SELECT m.*,o.status org_status FROM memberships m JOIN organizations o ON o.id=m.org_id WHERE m.user_id=? AND m.org_id=? AND m.status="active"',(uid,oid)).fetchone()
    require(m is not None,'Organization access denied',403)
    require(m['org_status'] not in ('blocked','deleted'),'This organization has been suspended by MTB. Contact MTB support.',403)
    if admin: require(m['role']=='Org Admin','Organization Admin permission required',403)
    return m

def jrow(r):return dict(r) if r else None

# ---------- Duplicate organizations and ownership claims (BRD 2, 4.2.4, 17) ----------
PENDING_HOURS=int(os.getenv('MTB_PENDING_HOURS','48'))        # unverified registrations are released after this
CLAIM_WINDOW_DAYS=int(os.getenv('MTB_CLAIM_WINDOW_DAYS','7'))  # time current admins / linked SMOs have to object
# Optional server-side Google key (restricted by IP, not by website) used to read a place's official phone and website.
SERVER_MAPS_KEY=os.getenv('MTB_GOOGLE_SERVER_KEY','').strip()
def mtb_admins():return {e.strip().lower() for e in os.getenv('MTB_ADMIN_EMAILS','').split(',') if e.strip()}

LINK_WORDS={'of','the','and','for'}
LEGAL_WORDS={'pvt','private','ltd','limited','llp','llc','inc','co','company','corp','corporation','plc'}
NAME_NOISE=LINK_WORDS|LEGAL_WORDS|{'india','hospital','hospitals'}
CITY_ALIASES={'bangalore':'bengaluru','bombay':'mumbai','madras':'chennai','calcutta':'kolkata','newdelhi':'delhi','gurgaon':'gurugram',
    'trivandrum':'thiruvananthapuram','poona':'pune','mysore':'mysuru','vizag':'visakhapatnam','vishakhapatnam':'visakhapatnam',
    'baroda':'vadodara','cochin':'kochi','pondicherry':'puducherry','calicut':'kozhikode','allahabad':'prayagraj',
    'secunderabad':'hyderabad','mangalore':'mangaluru','belgaum':'belagavi','hubli':'hubballi','banaras':'varanasi','benares':'varanasi'}
# Email providers and shared hosts never prove that someone belongs to an organization.
GENERIC_DOMAINS={'gmail.com','googlemail.com','yahoo.com','yahoo.co.in','yahoo.in','outlook.com','hotmail.com','live.com','msn.com',
    'icloud.com','me.com','aol.com','rediffmail.com','proton.me','protonmail.com','zoho.com','zohomail.in','gmx.com','yandex.com','mail.com',
    'google.com','facebook.com','blogspot.com','wixsite.com','wordpress.com','linkedin.com','instagram.com','justdial.com','practo.com'}
SECOND_LEVEL={'co','com','org','net','ac','edu','gov','nic','res','gen','firm','ind','mil','nhs'}
OPEN_CLAIMS=('awaiting_verification','objection_window','disputed')

def name_words(v):return re.sub(r'[^0-9a-z]+',' ',clean(v).casefold().replace('&',' and ')).split()
def exact_key(v):return ' '.join(name_words(v))  # same name ignoring case, spaces and punctuation
def match_key(v):
    """Name with legal suffixes and filler words removed: 'Apollo Hospitals Pvt. Ltd.' -> 'apollo'."""
    w=name_words(v);core=[x for x in w if x not in NAME_NOISE]
    return ' '.join(core or w)
def initials(v):
    w=[x for x in name_words(v) if x not in LINK_WORDS|LEGAL_WORDS]
    return ''.join(x[0] for x in w) if len(w)>=3 else ''
def city_key(v):
    k=re.sub(r'[^a-z]','',clean(v).casefold())
    return CITY_ALIASES.get(k,k)
def base_domain(host):
    parts=[p for p in clean(host).lower().strip('.').split('.') if p]
    if parts and parts[0]=='www':parts=parts[1:]
    if len(parts)<2:return ''
    n=3 if len(parts)>=3 and len(parts[-1])==2 and parts[-2] in SECOND_LEVEL else 2
    return '.'.join(parts[-n:])
def site_domain(url):
    url=clean(url)
    if not url:return ''
    try:return base_domain(urlparse(url if '://' in url else 'http://'+url).hostname or '')
    except ValueError:return ''
def email_domain(e):return base_domain(clean(e).rsplit('@',1)[-1])
def trusted_domain(d):return bool(d) and d not in GENERIC_DOMAINS
def phone_digits(v):
    d=re.sub(r'\D','',clean(v))
    return d[-10:] if len(d)>=8 else ''
def place_ref(v):
    v=clean(v)
    return v if re.fullmatch(r'[A-Za-z0-9_-]{10,300}',v) else ''

def set_signals(c,table,row_id):
    r=c.execute(f'SELECT * FROM {table} WHERE id=?',(row_id,)).fetchone()
    if table=='organizations':
        c.execute('UPDATE organizations SET exact_key=?,match_key=?,city_key=?,initials=?,domain=?,phone_digits=? WHERE id=?',
                  (exact_key(r['name']),match_key(r['name']),city_key(r['city']),initials(r['name']),site_domain(r['website']),phone_digits(r['phone']),row_id))
    else:
        c.execute('UPDATE hospitals SET match_key=?,city_key=?,domain=? WHERE id=?',(match_key(r['name']),city_key(r['city']),site_domain(r['website']),row_id))
def backfill_signals():
    with db() as c:
        for t,missing in (('organizations','match_key IS NULL OR exact_key IS NULL'),('hospitals','match_key IS NULL')):
            for r in c.execute(f'SELECT id FROM {t} WHERE {missing}').fetchall():set_signals(c,t,r['id'])
backfill_signals()

def find_org_matches(c,name,city,acronym='',site='',org_phone='',place_id=''):
    """'exact' matches block a new registration; 'likely' ones must be confirmed as a different organization."""
    found={}
    def hit(where,args,level,reason):
        for r in c.execute(f'SELECT id,name,type,city,state,status FROM organizations WHERE status!="deleted" AND ({where})',args).fetchall():
            m=found.setdefault(r['id'],{**dict(r),'level':level,'reasons':[]})
            if level=='exact':m['level']='exact'
            if reason not in m['reasons']:m['reasons'].append(reason)
    ck=city_key(city)
    if place_id:hit('place_id=?',(place_id,),'exact','Same place on Google Maps')
    if norm(name) and ck:
        hit('exact_key=? AND city_key=?',(exact_key(name),ck),'exact','Same name and city')
        hit('match_key=? AND city_key=?',(match_key(name),ck),'likely','Very similar name in the same city')
        single=norm(name) if ' ' not in norm(name) and len(norm(name))<=8 else ''
        for s in {x for x in (clean(acronym).casefold(),initials(name),single) if len(x)>=3}:
            hit('(lower(acronym)=? OR initials=?) AND city_key=?',(s,s,ck),'likely','Same short name or acronym in the same city')
    d=site_domain(site)
    if trusted_domain(d):hit('domain=?',(d,),'likely','Same website domain')
    p=phone_digits(org_phone)
    if p:hit('phone_digits=?',(p,),'likely','Same contact number')
    return sorted(found.values(),key=lambda m:(m['level']!='exact',m['name']))

def outbox(c,target,body,kind='notice',subject=None,critical=False):
    """Record an outgoing message; emails go out through Brevo when BREVO_API_KEY is set (see mailer.py).
    critical: codes and invitations. If they cannot be sent, the request fails so the person can try again."""
    status,provider_id,error='test',None,None
    if kind!='phone' and '@' in str(target) and mailer.enabled() and not mailer.undeliverable(target):
        try:
            provider_id=mailer.send(target,subject or 'Update from My Trial Board',body,tag=kind);status='sent'
        except mailer.MailError as e:
            status,error='failed',str(e)
            logging.getLogger('mtb.mail').warning('Email to %s (%s) failed: %s',target,kind,error)
            if not critical:audit(c,None,'email_send_failed','email',None,None,{'to':target,'kind':kind,'error':error[:200]})
    stored=body if DEV else RedactTokens.PATTERN.sub(r'\1[redacted]',re.sub(r'\b\d{6}\b','[code]',body))  # BRD 18.2.2
    c.execute('INSERT INTO outbox(target,kind,body,created,subject,status,provider_id,error) VALUES(?,?,?,?,?,?,?,?)',(target,kind,stored,now(),subject,status,provider_id,error))
    if status=='failed' and critical:
        raise HTTPException(502,'We could not send the email right now. Please try again in a few minutes.')

OTP_TEXT={
    'registration':('Verify your email for My Trial Board','Your My Trial Board verification code is {code}. It expires in 15 minutes. Enter it on the verification screen to confirm this email address.'),
    'recovery':('Reset your My Trial Board password','Use the code {code} to reset your My Trial Board password. It expires in 15 minutes. If you did not ask to reset your password, ignore this email and your password stays the same.'),
    'unlock':('Unlock your My Trial Board account','Use the code {code} to unlock your My Trial Board account. It expires in 15 minutes. If this was not you, reset your password after unlocking.'),
}
def admin_emails(c,org_id):
    return [r['email'] for r in c.execute('SELECT u.email FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.role="Org Admin" AND m.status="active"',(org_id,))]

def purge_stale(c):
    """Release registrations whose email/phone were not verified in time, so they stop blocking the name and email."""
    cutoff=datetime.fromtimestamp(ts()-PENDING_HOURS*3600,timezone.utc).isoformat()
    for u in c.execute('SELECT id FROM users WHERE status="pending" AND created<?',(cutoff,)).fetchall():
        uid=u['id']
        for o in c.execute('SELECT o.id,o.legal_doc FROM organizations o JOIN memberships m ON m.org_id=o.id WHERE m.user_id=? AND m.role="Org Admin" AND o.status="pending"',(uid,)).fetchall():
            for t in ('memberships','consents','join_requests','claims'):c.execute(f'DELETE FROM {t} WHERE org_id=?',(o['id'],))
            c.execute('DELETE FROM organizations WHERE id=?',(o['id'],))
            if o['legal_doc']:(UPLOADS/o['legal_doc']).unlink(missing_ok=True)
            audit(c,None,'registration_expired','organization',o['id'],o['id'])
        mtb_profile.erase_user(c,uid)
        for t in ('otps','sessions','consents','memberships','claims'):c.execute(f'DELETE FROM {t} WHERE user_id=?',(uid,))
        c.execute('DELETE FROM users WHERE id=?',(uid,))
        audit(c,None,'registration_expired','user',uid)

def google_place(place_id):
    """Official phone and website domain from Google (needs MTB_GOOGLE_SERVER_KEY). None when unavailable."""
    if not (SERVER_MAPS_KEY and place_id):return None
    try:
        import httpx
        r=httpx.get(f'https://places.googleapis.com/v1/places/{place_id}',timeout=5,
                    headers={'X-Goog-Api-Key':SERVER_MAPS_KEY,'X-Goog-FieldMask':'internationalPhoneNumber,nationalPhoneNumber,websiteUri'})
        if r.status_code!=200:return None
        j=r.json();return {'phone':j.get('internationalPhoneNumber') or j.get('nationalPhoneNumber') or '','domain':site_domain(j.get('websiteUri',''))}
    except Exception:return None

def claim_target(c,cl):
    """The record being claimed: the organization, or the provisional hospital."""
    if cl['kind']=='organization':return c.execute('SELECT * FROM organizations WHERE id=?',(cl['org_id'],)).fetchone()
    return c.execute('SELECT * FROM hospitals WHERE id=?',(cl['hospital_id'],)).fetchone()
def claim_objectors(c,cl):
    """Who may object: the organization's current admins, or the admins of SMOs linked to the hospital."""
    if cl['kind']=='organization':return admin_emails(c,cl['org_id'])
    return [r['email'] for r in c.execute('''SELECT DISTINCT u.email FROM hospital_links hl JOIN memberships m ON m.org_id=hl.smo_org_id AND m.role="Org Admin" AND m.status="active"
        JOIN users u ON u.id=m.user_id WHERE hl.hospital_id=? AND hl.status IN ("active","pending")''',(cl['hospital_id'],))]
def notify_mtb_admins(c,text):
    for e in sorted(mtb_admins()):outbox(c,e,text,subject='MTB review needed')

def evaluate_claim(c,cl):
    """Run once the claimant is verified. Approve on proof, flag rival claims, otherwise open the objection window."""
    target=claim_target(c,cl);claimant=c.execute('SELECT * FROM users WHERE id=?',(cl['user_id'],)).fetchone()
    rival=c.execute('SELECT 1 FROM claims WHERE id<>? AND kind=? AND status IN ("objection_window","disputed") AND '+('org_id=?' if cl['kind']=='organization' else 'hospital_id=?'),
                    (cl['id'],cl['kind'],cl['org_id'] if cl['kind']=='organization' else cl['hospital_id'])).fetchone()
    if rival:
        c.execute('UPDATE claims SET status="disputed",objection=? WHERE id=?',('Another claim for the same record is open.',cl['id']))
        notify_mtb_admins(c,f'MTB review needed: competing ownership claims for {target["name"]}.')
        return audit(c,cl['user_id'],'ownership_claim_disputed','claim',cl['id'],cl['org_id'],{'reason':'rival_claim'})
    mine=email_domain(claimant['email'])
    domains={target['domain']}
    g=google_place(target['place_id'])
    if g and g['domain']:domains.add(g['domain'])
    # If a current admin already uses the same domain, the domain proves nothing about who should be in charge.
    holders={email_domain(e) for e in admin_emails(c,cl['org_id'])} if cl['kind']=='organization' else set()
    if trusted_domain(mine) and mine in domains and mine not in holders:
        return approve_claim(c,cl,'email_domain',None)
    deadline=ts()+CLAIM_WINDOW_DAYS*86400
    c.execute('UPDATE claims SET status="objection_window",deadline=? WHERE id=?',(deadline,cl['id']))
    when=datetime.fromtimestamp(deadline,timezone.utc).strftime('%d %b %Y')
    who=f'{claimant["first"]} {claimant["last"]} ({claimant["email"]})'
    for e in claim_objectors(c,cl):
        outbox(c,e,f'{who} has claimed ownership of {target["name"]} on My Trial Board. If this is wrong, object from your dashboard before {when}. If nobody objects, the claim is approved.',subject=f'Ownership claim for {target["name"]}')
    outbox(c,claimant['email'],f'Your ownership claim for {target["name"]} is open for objections until {when}. If nobody objects, it is approved automatically.',subject='Your ownership claim is in review')
    audit(c,cl['user_id'],'ownership_claim_window_opened','claim',cl['id'],cl['org_id'],{'deadline':deadline})

def approve_claim(c,cl,method,actor):
    target=claim_target(c,cl);details={'method':method}
    if cl['kind']=='organization':
        oid=cl['org_id']
        old=c.execute('SELECT m.id,u.email FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.role="Org Admin" AND m.status="active" AND m.user_id<>?',(oid,cl['user_id'])).fetchall()
        for m in old:
            c.execute('UPDATE memberships SET status="inactive" WHERE id=?',(m['id'],))
            audit(c,actor,'role_revoked','membership',m['id'],oid,{'role':'Org Admin','admin':m['email'],'reason':'ownership claim approved'})
            outbox(c,m['email'],f'Ownership of {target["name"]} on My Trial Board has been transferred to a verified representative, and your admin access has ended. If this is wrong, contact MTB support.',subject=f'Admin access to {target["name"]} has ended')
        c.execute('INSERT INTO memberships(user_id,org_id,role,status,designation,created) VALUES(?,?,?,?,(SELECT designation FROM users WHERE id=?),?) ON CONFLICT(user_id,org_id) DO UPDATE SET role="Org Admin",status="active",designation=coalesce(designation,excluded.designation)',(cl['user_id'],oid,'Org Admin','active',cl['user_id'],now()))
        c.execute('UPDATE organizations SET status="active" WHERE id=?',(oid,))
        audit(c,actor,'role_granted','user',cl['user_id'],oid,{'role':'Org Admin','via':'ownership claim'})
        details['previous_admin_memberships']=[m['id'] for m in old]
    else:
        taken=c.execute('UPDATE hospitals SET org_id=?,provisional=0 WHERE id=? AND org_id IS NULL',(cl['org_id'],cl['hospital_id'])).rowcount
        if not taken:return reject_claim(c,cl,None,'The hospital record was already claimed by another organization.')
    c.execute('UPDATE claims SET status="approved",method=?,decided_by=?,decided=? WHERE id=?',(method,actor,now(),cl['id']))
    claimant=c.execute('SELECT email FROM users WHERE id=?',(cl['user_id'],)).fetchone()
    outbox(c,claimant['email'],f'Your ownership claim for {target["name"]} was approved.',subject='Your ownership claim was approved')
    audit(c,actor or cl['user_id'],'ownership_claim_approved','claim',cl['id'],cl['org_id'],details)

def reject_claim(c,cl,actor,note):
    target=claim_target(c,cl)
    c.execute('UPDATE claims SET status="rejected",decided_by=?,note=?,decided=? WHERE id=?',(actor,note,now(),cl['id']))
    claimant=c.execute('SELECT email FROM users WHERE id=?',(cl['user_id'],)).fetchone()
    outbox(c,claimant['email'],f'Your ownership claim for {target["name"]} was not approved.'+(f' Note: {note}' if note else ''),subject='Your ownership claim was not approved')
    audit(c,actor,'ownership_claim_rejected','claim',cl['id'],cl['org_id'],{'note':note})

def process_claims(c):
    for cl in c.execute('SELECT * FROM claims WHERE status="objection_window" AND deadline<=?',(ts(),)).fetchall():
        approve_claim(c,cl,'no_objection',None)
def housekeeping(c):
    purge_stale(c);process_claims(c);expire_invitations(c)

def expire_invitations(c):
    for i in c.execute('SELECT id,org_id,email FROM invitations WHERE status="pending" AND expires<=?',(ts(),)).fetchall():
        c.execute('UPDATE invitations SET status="expired" WHERE id=?',(i['id'],))
        audit(c,None,'invitation_expired','invitation',i['id'],i['org_id'])

_hits={}
def rate_limit(request,bucket,limit,window):
    """Small in-memory per-IP limiter for public lookups (production: shared store / gateway)."""
    key=(bucket,request.client.host if request.client else '?');t=time.time()
    recent=[x for x in _hits.get(key,[]) if x>t-window]
    require(len(recent)<limit,'Too many requests. Please wait a moment and try again.',429)
    _hits[key]=recent+[t]

def claim_view(c,cl,with_phone=False):
    """Claim summary for the claimant's dashboard."""
    target=claim_target(c,cl);v={k:cl[k] for k in ('id','kind','status','method','deadline','note','created')}
    v['target']=target['name'] if target else '';v['city']=target['city'] if target else ''
    if with_phone and cl['status']=='objection_window' and target:
        g=google_place(target['place_id'])
        if g and phone_digits(g['phone']):d=re.sub(r'\D','',g['phone']);v['official_phone']='•••• ••'+d[-3:]
    return v

@app.get('/')
def index():return FileResponse(ROOT/'static'/'index.html')
@app.get('/static/{path:path}')
def static(path:str):
    target=(ROOT/'static'/path).resolve()
    require(str(target).startswith(str((ROOT/'static').resolve())) and target.is_file(),'Not found',404)
    # Windows registry can map .js to text/plain, which breaks ES module loading.
    return FileResponse(target,media_type='text/javascript' if target.suffix=='.js' else None)

@app.get('/api/config')
def config():return {'app':'My Trial Board','dev_mode':DEV,'otp_delivery_configured':False,'maps_key':MAPS_KEY,'claim_window_days':CLAIM_WINDOW_DAYS,'pending_hours':PENDING_HOURS,'member_roles':MEMBER_ROLES,'pi_roles':PI_LINK_ROLES,'email_delivery':mailer.enabled(),'phone_code_on_screen':PHONE_CODE_ON_SCREEN}

@app.post('/api/register')
async def register(request:Request):
    d=await request.json(); org=d.get('organization') or {}; person=d.get('person') or {}
    typ=clean(org.get('type')); require(typ in ORG_TYPES,'Select organization type')
    subtype=categories(typ,org.get('subtypes',org.get('subtype')))
    name=clean(org.get('name')); require(len(name)>=2,'Organization name required')
    for f in ('address1','city','state','country','pin'):require(clean(org.get(f)),f'Organization {f} is required')
    org_phone=phone(org['phone'],'organization contact number') if clean(org.get('phone')) else ''
    site=website(org.get('website'))
    for f in ('first','last','email','phone','salutation','gender'):require(clean(person.get(f)),f'{f} is required')
    require(person['salutation'] in SALUTATIONS,'Invalid salutation')
    require(person['gender'] in GENDERS,'Invalid gender')
    mobile=phone(person['phone'],'official contact number')
    alt_phone=phone(person['alt_phone'],'alternate contact number') if clean(person.get('alt_phone')) else ''
    pw=person.get('password','');require(password_valid(pw),'Password requires 8 characters, uppercase, lowercase and special character')
    require(pw==person.get('confirm'),'Passwords do not match')
    # BRD 7: authority, accuracy/update undertaking and Terms + Privacy Notice are separate declarations.
    require(bool(d.get('authorized')) and bool(d.get('accurate')) and bool(d.get('terms')),'All declarations and Terms acceptance are required')
    require(d.get('captcha_answer')==str(d.get('captcha_expected')) and d.get('captcha_answer') is not None,'Complete CAPTCHA',422)  # DEV-ONLY untrusted challenge; replace before production
    e=email(person['email']); alt=email(person['alt_email']) if clean(person.get('alt_email')) else None
    require(alt!=e,'Alternate email must differ from the official email')
    ip,dev=client_info(request)
    pid=place_ref(org.get('place_id'));claim_oid=int(d.get('claim_org_id') or 0);matches=[]
    with db() as c:
        housekeeping(c)
        # BRD 8.1.2: also catch an existing account held under an alternate email.
        addrs=[x for x in (e,alt) if x]; marks=','.join('?'*len(addrs))
        dup=c.execute(f'SELECT status FROM users WHERE email IN ({marks}) OR alt_email IN ({marks})',addrs+addrs).fetchone()
        if dup and dup['status']=='pending':
            raise HTTPException(409,f'A registration with this email is waiting for verification. Finish it with the codes we sent, or register again after {PENDING_HOURS} hours.')
        require(not dup,'An account with this email already exists. Sign in or use an invitation.',409)
        if claim_oid:
            target=c.execute('SELECT * FROM organizations WHERE id=?',(claim_oid,)).fetchone()
            require(target and target['status']=='active','This organization cannot be claimed right now.',409)
        else:
            matches=find_org_matches(c,name,org['city'],clean(org.get('acronym')),site,org_phone,pid)
            if any(m['level']=='exact' for m in matches):
                raise HTTPException(409,{'code':'org_exists','message':'This organization is already on My Trial Board. Ask to join it, or claim it if you are its authorized representative.','matches':matches})
            acked={int(x) for x in (d.get('confirm_distinct') or []) if str(x).isdigit()}
            if {m['id'] for m in matches}-acked:
                raise HTTPException(409,{'code':'possible_duplicate','message':'This looks like an organization already on My Trial Board. Please confirm it is a different organization.','matches':matches})
        doc=save_document(org.get('legal_doc'))
        c.execute('INSERT INTO users(first,middle,last,salutation,gender,designation,email,alt_email,phone,alt_phone,password_hash,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(clean(person['first']),clean(person.get('middle')),clean(person['last']),person['salutation'],person['gender'],clean(person.get('designation')),e,alt,mobile,alt_phone,hasher.hash(pw),now()))
        uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        if claim_oid:
            # No second record: the claimant's details are kept on the claim for reviewers.
            oid=claim_oid
            submitted={k:clean(org.get(k)) for k in ('type','name','acronym','phone','address1','address2','city','state','country','pin','website')}
            c.execute('INSERT INTO claims(kind,org_id,user_id,status,details,created) VALUES(?,?,?,?,?,?)',('organization',oid,uid,'awaiting_verification',json.dumps({**submitted,'subtype':subtype,'legal_doc':doc}),now()))
            audit(c,uid,'ownership_claim_submitted','organization',oid,oid,dev,ip=ip)
        else:
            c.execute('INSERT INTO organizations(name,normalized,type,subtype,acronym,phone,address1,address2,city,state,country,pin,website,legal_doc,status,place_id,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(name,norm(name),typ,subtype,clean(org.get('acronym')),org_phone,clean(org['address1']),clean(org.get('address2')),clean(org['city']),clean(org['state']),clean(org['country']),clean(org['pin']),site,doc,'pending',pid or None,now()))
            oid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            set_signals(c,'organizations',oid)
            c.execute('INSERT INTO memberships(user_id,org_id,role,status,designation,created) VALUES(?,?,?,?,?,?)',(uid,oid,'Org Admin','pending',clean(person.get('designation')) or None,now()))
            if matches:audit(c,uid,'duplicate_warning_overridden','organization',oid,oid,{'matches':[{'id':m['id'],'reasons':m['reasons']} for m in matches]},ip=ip)
        for kind in ['authorized','accurate','terms','privacy_notice']:
            c.execute('INSERT INTO consents(user_id,org_id,kind,version,accepted_at) VALUES(?,?,?,?,?)',(uid,oid,kind,'1.0',now()))
        send_otp(c,uid,e,'email','registration');phone_code=send_otp(c,uid,mobile,'phone','registration')
        if alt:send_otp(c,uid,alt,'alt_email','registration')
        audit(c,uid,'registration_submitted','organization',oid,oid,{**dev,'legal_doc':bool(doc),'claim':bool(claim_oid)},ip=ip)
    return {'ok':True,'registration_id':uid,'alt_email':bool(alt),'claim':bool(claim_oid),'message':'Verify your contact channels to activate the account',**screen_code(phone_code)}

def screen_code(code):
    """Sign-up phone code for the person's own screen while SMS is not connected (MTB_PHONE_CODE_ON_SCREEN=1)."""
    return {'phone_code_on_screen':code} if PHONE_CODE_ON_SCREEN and code else {}

@app.get('/api/org-check')
def org_check(request:Request,name:str='',city:str='',type:str='',acronym:str='',website:str='',phone:str='',place_id:str=''):
    """Early duplicate check while the registration form is being filled in."""
    rate_limit(request,'org-check',60,60)
    with db() as c:
        housekeeping(c)
        matches=find_org_matches(c,name[:200],city[:100],acronym[:40],website[:300],phone[:30],place_ref(place_id))
        # A Site that an SMO already added becomes claimable after the Site's account is verified.
        hospital=None
        if type=='Site / Hospital / Institution' and norm(name) and city_key(city):
            h=c.execute('SELECT name,city FROM hospitals WHERE org_id IS NULL AND (normalized=? OR match_key=?) AND city_key=?',(norm(name),match_key(name),city_key(city))).fetchone()
            hospital=jrow(h)
    return {'matches':[{**m,'pending_release_hours':PENDING_HOURS if m['status']=='pending' else None} for m in matches],'hospital_record':hospital}

@app.post('/api/join-requests')
async def join_request(request:Request):
    """Ask an existing organization's admins for an invitation, without revealing who they are."""
    d=await request.json();oid=int(d.get('org_id') or 0);e=email(d.get('email'));name=clean(d.get('full_name'))[:120]
    require(len(name)>=2,'Enter your full name')
    p=phone(d['phone'],'phone number') if clean(d.get('phone')) else ''
    ip,_=client_info(request)
    with db() as c:
        o=c.execute('SELECT * FROM organizations WHERE id=?',(oid,)).fetchone()
        require(o and o['status']=='active','This organization is not accepting requests yet.',409)
        require(c.execute('SELECT COUNT(*) n FROM join_requests WHERE ip=? AND created>?',(ip,ts()-3600)).fetchone()['n']<5,'Too many requests. Try again later.',429)
        if not c.execute('SELECT 1 FROM join_requests WHERE org_id=? AND email=? AND status="pending"',(oid,e)).fetchone():
            c.execute('INSERT INTO join_requests(org_id,full_name,email,phone,message,ip,created) VALUES(?,?,?,?,?,?,?)',(oid,name,e,p,clean(d.get('message'))[:500],ip,ts()))
            for a in admin_emails(c,oid):outbox(c,a,f'{name} ({e}) asked to join {o["name"]} on My Trial Board. Review the request on your dashboard.',subject=f'New request to join {o["name"]}')
            audit(c,None,'join_requested','organization',oid,oid,{'email':e},ip=ip)
    return {'ok':True,'message':f'Request sent to the admin of {o["name"]}. If they approve it, you will receive an invitation by email.'}

@app.post('/api/join-requests/{req_id}/dismiss')
def dismiss_join_request(req_id:int,request:Request):
    with db() as c:
        u,s=auth(request,c,True)
        r=c.execute('SELECT * FROM join_requests WHERE id=?',(req_id,)).fetchone();require(r,'Request not found',404)
        membership(c,u['id'],r['org_id'],True)
        c.execute('UPDATE join_requests SET status="dismissed" WHERE id=?',(req_id,))
        audit(c,u['id'],'join_request_dismissed','join_request',req_id,r['org_id'])
    return {'ok':True}

@app.post('/api/claims/{claim_id}/object')
async def object_claim(claim_id:int,request:Request):
    d=await request.json();reason=clean(d.get('reason'))[:1000];require(len(reason)>=5,'Tell us briefly why this claim is wrong')
    with db() as c:
        u,s=auth(request,c,True)
        cl=c.execute('SELECT * FROM claims WHERE id=?',(claim_id,)).fetchone()
        require(cl and cl['status']=='objection_window','This claim is not open for objections',409)
        require(u['email'] in claim_objectors(c,cl),'Only the current admins can object to this claim',403)
        c.execute('UPDATE claims SET status="disputed",objected_by=?,objection=? WHERE id=?',(u['id'],reason,claim_id))
        target=claim_target(c,cl)
        notify_mtb_admins(c,f'MTB review needed: an ownership claim for {target["name"]} was disputed.')
        claimant=c.execute('SELECT email FROM users WHERE id=?',(cl['user_id'],)).fetchone()
        outbox(c,claimant['email'],f'Your ownership claim for {target["name"]} was disputed and will be reviewed by the MTB team.',subject='Your ownership claim is under review')
        audit(c,u['id'],'ownership_claim_disputed','claim',claim_id,cl['org_id'],{'reason':reason})
    return {'ok':True}

@app.post('/api/claims/{claim_id}/phone-code')
def claim_phone_code(claim_id:int,request:Request):
    """Send a code to the official phone listed on Google for the claimed place."""
    with db() as c:
        u,s=auth(request,c,True)
        cl=c.execute('SELECT * FROM claims WHERE id=? AND user_id=?',(claim_id,u['id'])).fetchone()
        require(cl and cl['status']=='objection_window','This claim cannot be verified by phone now',409)
        g=google_place(claim_target(c,cl)['place_id'])
        require(g and phone_digits(g['phone']),'No official phone number is available for this record',409)
        send_otp(c,u['id'],g['phone'],'phone',f'claim:{claim_id}')
    return {'ok':True}

@app.post('/api/claims/{claim_id}/phone-verify')
async def claim_phone_verify(claim_id:int,request:Request):
    d=await request.json()
    with db() as c:
        u,s=auth(request,c,True)
        cl=c.execute('SELECT * FROM claims WHERE id=? AND user_id=?',(claim_id,u['id'])).fetchone()
        require(cl and cl['status']=='objection_window','This claim cannot be verified by phone now',409)
        verify_otp(c,u['id'],'phone',f'claim:{claim_id}',d.get('code',''))
        approve_claim(c,cl,'official_phone',None)
    return {'ok':True}

@app.get('/api/admin/claims')
def admin_claims(request:Request):
    with db() as c:
        u,s=auth(request,c);require(u['email'] in mtb_admins(),'MTB Admin only',403)
        return {'claims':disputed_claims(c)}

def disputed_claims(c):
    out=[]
    for cl in c.execute('SELECT * FROM claims WHERE status="disputed" ORDER BY id').fetchall():
        target=claim_target(c,cl);claimant=c.execute('SELECT first,last,email FROM users WHERE id=?',(cl['user_id'],)).fetchone()
        objector=c.execute('SELECT email FROM users WHERE id=?',(cl['objected_by'],)).fetchone() if cl['objected_by'] else None
        site=c.execute('SELECT name FROM organizations WHERE id=?',(cl['org_id'],)).fetchone() if cl['kind']=='hospital' else None
        out.append({'id':cl['id'],'kind':cl['kind'],'target':target['name'],'city':target['city'],'target_website':target['website'],
            'claimant':f'{claimant["first"]} {claimant["last"]}','claimant_email':claimant['email'],'claimant_org':site['name'] if site else None,
            'current_admins':admin_emails(c,cl['org_id']) if cl['kind']=='organization' else [],
            'objection':cl['objection'],'objector':objector['email'] if objector else None,'created':cl['created']})
    return out

@app.post('/api/admin/claims/{claim_id}/decision')
async def admin_claim_decision(claim_id:int,request:Request):
    d=await request.json();decision=d.get('decision');require(decision in ('approve','reject'),'Choose approve or reject')
    with db() as c:
        u,s=auth(request,c,True);require(u['email'] in mtb_admins(),'MTB Admin only',403)
        cl=c.execute('SELECT * FROM claims WHERE id=? AND status="disputed"',(claim_id,)).fetchone();require(cl,'Claim not found',404)
        if decision=='approve':approve_claim(c,cl,'mtb_admin',u['id'])
        else:reject_claim(c,cl,u['id'],clean(d.get('note'))[:500])
    return {'ok':True}

@app.post('/api/verify-registration')
async def registration_verify(request:Request):
    d=await request.json(); uid=int(d.get('registration_id',0))
    with db() as c:
        u=c.execute('SELECT * FROM users WHERE id=? AND status="pending"',(uid,)).fetchone()
        require(u is not None,'Registration not found',404)
        channel=d.get('channel');require(channel in ('email','phone','alt_email'),'Invalid channel')
        require(channel!='alt_email' or u['alt_email'],'No alternate email on this registration')
        verify_otp(c,uid,channel,'registration',d.get('code',''))
        # BRD 8.2: verified flag + timestamp per channel.
        col={'email':'email_verified','phone':'phone_verified','alt_email':'alt_email_verified'}[channel]
        c.execute(f'UPDATE users SET {col}=1,{col}_at=? WHERE id=?',(now(),uid))
        flags=c.execute('SELECT email_verified,phone_verified,alt_email,alt_email_verified FROM users WHERE id=?',(uid,)).fetchone()
        # An alternate email, when given, must be verified so it can be trusted for recovery (BRD 6, 11.1).
        done=bool(flags['email_verified'] and flags['phone_verified'] and (flags['alt_email_verified'] or not flags['alt_email']))
        if done:
            c.execute('UPDATE users SET status="active" WHERE id=?',(uid,))
            c.execute('UPDATE memberships SET status="active" WHERE user_id=? AND status="pending"',(uid,))
            for o in c.execute('SELECT org_id FROM memberships WHERE user_id=? AND role="Org Admin"',(uid,)).fetchall():
                if c.execute('UPDATE organizations SET status="active" WHERE id=? AND status="pending"',(o['org_id'],)).rowcount:
                    audit(c,uid,'organization_activated','organization',o['org_id'],o['org_id'])
            audit(c,uid,'account_activated','user',uid)
            # A directly registered hospital becomes discoverable, but never inherits SMO rights.
            for o in c.execute('SELECT o.* FROM organizations o JOIN memberships m ON m.org_id=o.id WHERE m.user_id=? AND m.role="Org Admin" AND o.type="Site / Hospital / Institution"',(uid,)).fetchall():
                existing=c.execute('SELECT * FROM hospitals WHERE (normalized=? OR match_key=?) AND city_key=? ORDER BY org_id IS NOT NULL',(o['normalized'],o['match_key'],o['city_key'])).fetchone()
                if not existing:
                    htype=o['subtype'] if o['subtype'] in ('Private','Government','Trust','Academic') else 'Others'
                    c.execute('INSERT INTO hospitals(name,normalized,type,address1,address2,city,state,country,pin,phone,website,org_id,provisional,place_id,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(o['name'],o['normalized'],htype,o['address1'],o['address2'],o['city'],o['state'],o['country'],o['pin'],o['phone'],o['website'],o['id'],0,o['place_id'],now()))
                    set_signals(c,'hospitals',c.execute('SELECT last_insert_rowid()').fetchone()[0])
                elif existing['org_id'] is None:
                    # An SMO added this site earlier: claim the provisional record instead of taking it over silently.
                    c.execute('INSERT INTO claims(kind,org_id,hospital_id,user_id,status,created) VALUES(?,?,?,?,?,?)',('hospital',o['id'],existing['id'],uid,'awaiting_verification',now()))
                    audit(c,uid,'hospital_claim_submitted','hospital',existing['id'],o['id'])
                else:
                    audit(c,uid,'hospital_record_owned_elsewhere','organization',o['id'],o['id'],{'hospital_id':existing['id']})
            for cl in c.execute('SELECT * FROM claims WHERE user_id=? AND status="awaiting_verification"',(uid,)).fetchall():evaluate_claim(c,cl)
        audit(c,uid,'registration_'+channel+'_verified','user',uid)
        claims=[claim_view(c,cl) for cl in c.execute('SELECT * FROM claims WHERE user_id=?',(uid,)).fetchall()] if done else []
    return {'ok':True,'complete':done,'claims':claims,'email_verified':bool(flags['email_verified']),'phone_verified':bool(flags['phone_verified']),'alt_email_verified':bool(flags['alt_email_verified'])}

@app.post('/api/resend-otp')
async def resend(request:Request):
    d=await request.json();uid=int(d.get('registration_id',0));channel=d.get('channel')
    require(channel in ['email','phone','alt_email'],'Invalid channel')
    with db() as c:
        u=c.execute('SELECT * FROM users WHERE id=? AND status="pending"',(uid,)).fetchone();require(u,'No pending registration',404)
        target={'email':u['email'],'phone':u['phone'],'alt_email':u['alt_email']}[channel]
        require(target,'No alternate email on this registration')
        if u[{'email':'email_verified','phone':'phone_verified','alt_email':'alt_email_verified'}[channel]]:return {'ok':True}
        code=send_otp(c,uid,target,channel,'registration')
    return {'ok':True,**(screen_code(code) if channel=='phone' else {})}

@app.post('/api/login')
async def login(request:Request,response:Response):
    d=await request.json();e=email(d.get('email',''));password=d.get('password','')
    ip,dev=client_info(request)
    with db() as c:
        # Attempts are tracked per email, known or not, so responses never reveal whether an account exists (BRD 10.2).
        h,failed,locked=attempts(c,e)
        if locked>ts():raise HTTPException(423,'Account temporarily locked for security. Use "Unlock account" to continue.')
        if locked:failed=0  # lock expired
        if failed>=1:  # BRD 10.3.1: CAPTCHA after the first failed attempt (demo challenge; replace with Turnstile/reCAPTCHA)
            require(d.get('captcha_answer') is not None and str(d.get('captcha_answer'))==str(d.get('captcha_expected')),'Complete the security check to continue.',428)
        u=c.execute('SELECT * FROM users WHERE email=?',(e,)).fetchone()
        try: valid=hasher.verify(u['password_hash'] if u else DUMMY_HASH,password) and u is not None
        except (VerifyMismatchError,VerificationError):valid=False
        if not valid:
            failed+=1;lock=ts()+900 if failed>=3 else 0
            set_attempts(c,h,failed,lock)
            audit(c,u['id'] if u else None,'account_locked' if lock else 'login_failed','user',u['id'] if u else None,details={**dev,'attempt':failed},ip=ip)
            c.commit()
            msg={1:'Incorrect email or password. Warning: two more failed attempts will temporarily lock this account.',
                 2:'Incorrect email or password. Final warning: one more failed attempt will temporarily lock this account.'}.get(failed,'Account temporarily locked for security. Use "Unlock account" to continue.')
            raise HTTPException(423 if lock else 401,msg)
        require(u['status']!='blocked','This account has been suspended. Contact MTB support.',403)
        require(u['status']=='active','Verify account before signing in',403)
        set_attempts(c,h,0,0)
        life=int(SESSION_HOURS*3600)  # MTB_SESSION_HOURS (default 8); the cookie also ends when the browser closes
        sid=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24);expiration=ts()+life
        c.execute('INSERT INTO sessions(id,user_id,csrf,expires,created) VALUES(?,?,?,?,?)',(sid,u['id'],csrf,expiration,now()))
        audit(c,u['id'],'login_success','user',u['id'],details=dev,ip=ip)
    token=jwt.encode({'sid':sid,'exp':expiration},SECRET,algorithm='HS256')
    response.set_cookie('mtb_session',token,httponly=True,secure=COOKIE_SECURE,samesite='lax',path='/')
    return {'ok':True,'csrf':csrf}

GENERIC_UNLOCK='If the account is locked, an unlock code has been sent to its verified email.'
@app.post('/api/unlock/request')
async def unlock_request(request:Request):
    """BRD 11.2: OTP-based unlock through a verified channel; rate-limited per account (code caps) and per IP."""
    rate_limit(request,'unlock',10,900)
    d=await request.json()
    try:e=email(d.get('email'))
    except HTTPException:return {'ok':True,'message':GENERIC_UNLOCK}
    ip,dev=client_info(request)
    with db() as c:
        h,failed,locked=attempts(c,e)
        u=c.execute('SELECT * FROM users WHERE email=? AND status="active"',(e,)).fetchone()
        if u and locked>ts():
            try:send_otp(c,u['id'],e,'email','unlock')
            except HTTPException:pass
            audit(c,u['id'],'unlock_requested','user',u['id'],details=dev,ip=ip)
    return {'ok':True,'message':GENERIC_UNLOCK}

@app.post('/api/unlock/complete')
async def unlock_complete(request:Request):
    rate_limit(request,'unlock-verify',30,900)
    d=await request.json();e=email(d.get('email'))
    ip,dev=client_info(request)
    with db() as c:
        u=c.execute('SELECT * FROM users WHERE email=? AND status="active"',(e,)).fetchone()
        require(u,'Invalid or expired code',400)
        try:verify_otp(c,u['id'],'email','unlock',d.get('code',''))
        except HTTPException:
            audit(c,u['id'],'unlock_code_failed','user',u['id'],details=dev,ip=ip);c.commit();raise
        set_attempts(c,attempts(c,e)[0],0,0)
        audit(c,u['id'],'account_unlocked','user',u['id'],details=dev,ip=ip)
        reset=issue_reset_pass(c,u['id'])  # BRD 11.2.2: offer a password reset right after unlocking
    return {'ok':True,'reset_token':reset,'expires_in':RESET_PASS_SECONDS}

@app.get('/api/me')
def me(request:Request):
    with db() as c:
        housekeeping(c)
        u,s=auth(request,c)
        memberships=[dict(x) for x in c.execute('SELECT m.org_id,m.role,m.status,coalesce(m.designation,?) designation,m.department,o.name,o.type,o.city FROM memberships m JOIN organizations o ON o.id=m.org_id WHERE m.user_id=? AND m.status="active" AND o.status NOT IN ("blocked","deleted")',(u['designation'],u['id']))]
        invites=[dict(x) for x in c.execute('SELECT i.id,i.kind,i.role,i.full_name,i.email,i.hospital_id,i.org_id,o.name org_name,o.type org_type,h.name hospital,i.created FROM invitations i JOIN organizations o ON i.org_id=o.id LEFT JOIN hospitals h ON h.id=i.hospital_id WHERE i.email=? AND i.status="pending" AND i.expires>?',(u['email'],ts()))]
        claims=[claim_view(c,cl,True) for cl in c.execute('SELECT * FROM claims WHERE user_id=? ORDER BY id DESC',(u['id'],)).fetchall()]
        is_admin=u['email'] in mtb_admins()
        # BRD 5.1.3: one PI account can work with several SMOs; the PI sees every link even without an org membership.
        pi_affiliations=[dict(x) for x in c.execute('''SELECT p.id,o.name smo,o.city smo_city,h.name hospital,h.city,h.state,p.role,p.status,p.created
            FROM pi_links p JOIN organizations o ON o.id=p.smo_org_id JOIN hospitals h ON h.id=p.hospital_id
            WHERE p.user_id=? ORDER BY p.status="active" DESC,o.name''',(u['id'],))]
        return {'user':{'id':u['id'],'name':u['first']+' '+u['last'],'email':u['email']},'csrf':s['csrf'],'memberships':memberships,'invitations':invites,'pi_affiliations':pi_affiliations,
                'claims':claims,'is_mtb_admin':is_admin,'disputes':disputed_claims(c) if is_admin else []}

@app.post('/api/logout')
def logout(request:Request,response:Response):
    with db() as c:
        u,s=auth(request,c,True)
        c.execute('UPDATE sessions SET revoked=1 WHERE id=?',(s['id'],));audit(c,u['id'],'logout')
    response.delete_cookie('mtb_session',path='/');return {'ok':True}

@app.get('/api/dashboard/{org_id}')
def dashboard(org_id:int,request:Request):
    with db() as c:
        u,s=auth(request,c);m=membership(c,u['id'],org_id)
        o=c.execute('SELECT * FROM organizations WHERE id=?',(org_id,)).fetchone()
        members=[dict(x) for x in c.execute('SELECT m.id membership_id,u.id,u.first,u.last,u.email,m.role,coalesce(m.designation,u.designation) designation,m.department,m.status FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.org_id=?',(org_id,))]
        invitations=[{**dict(x),'status':'expired' if x['status']=='pending' and x['expires']<=ts() else x['status']} for x in c.execute('SELECT i.id,i.kind,i.full_name,i.email,i.role,i.status,i.created,i.expires,h.name hospital FROM invitations i LEFT JOIN hospitals h ON h.id=i.hospital_id WHERE i.org_id=? ORDER BY i.id DESC',(org_id,))]
        hospitals=[dict(x) for x in c.execute('SELECT h.id,hl.id link_id,h.name,h.type,h.city,h.state,h.provisional,hl.status,h.org_id,(h.org_id IS NULL AND (SELECT x.smo_org_id FROM hospital_links x WHERE x.hospital_id=h.id ORDER BY x.id LIMIT 1)=hl.smo_org_id) can_edit FROM hospital_links hl JOIN hospitals h ON h.id=hl.hospital_id WHERE hl.smo_org_id=?',(org_id,))]
        pi=[dict(x) for x in c.execute('SELECT p.id,p.hospital_id,h.name hospital,u.first,u.last,u.email,p.role,p.status FROM pi_links p JOIN users u ON u.id=p.user_id JOIN hospitals h ON h.id=p.hospital_id WHERE p.smo_org_id=?',(org_id,))]
        approvals=[dict(x) for x in c.execute('SELECT hl.id,hl.smo_org_id,o.name smo,h.name hospital,h.id hospital_id FROM hospital_links hl JOIN hospitals h ON h.id=hl.hospital_id JOIN organizations o ON o.id=hl.smo_org_id WHERE h.org_id=? AND hl.status="pending"',(org_id,))]
        # A registered hospital can be affiliated with several SMOs (BRD 4.2.5); its admin sees all of them.
        smo_links=[dict(x) for x in c.execute('''SELECT hl.id,o.name smo,o.city,h.name hospital,hl.status,hl.created,
            (SELECT COUNT(*) FROM pi_links p WHERE p.smo_org_id=hl.smo_org_id AND p.hospital_id=h.id AND p.status="active") pis
            FROM hospital_links hl JOIN hospitals h ON h.id=hl.hospital_id JOIN organizations o ON o.id=hl.smo_org_id
            WHERE h.org_id=? ORDER BY CASE hl.status WHEN "pending" THEN 0 WHEN "active" THEN 1 ELSE 2 END,o.name''',(org_id,))]
        # BRD 5.1.2: the hospital admin sees which PIs work at the hospital and through which SMO.
        hospital_pis=[dict(x) for x in c.execute('''SELECT p.id,u.first,u.last,u.email,u.phone,u.designation,p.role,o.name smo,h.name hospital,p.status,p.created
            FROM pi_links p JOIN users u ON u.id=p.user_id JOIN hospitals h ON h.id=p.hospital_id JOIN organizations o ON o.id=p.smo_org_id
            WHERE h.org_id=? ORDER BY p.status="active" DESC,u.last,u.first''',(org_id,))]
        audits=[dict(x) for x in c.execute('SELECT action,created,subject_type FROM audit WHERE org_id=? ORDER BY id DESC LIMIT 12',(org_id,))] if m['role']=='Org Admin' else []
        joins=[dict(x) for x in c.execute('SELECT id,full_name,email,phone,message,created FROM join_requests WHERE org_id=? AND status="pending" ORDER BY id DESC',(org_id,))]
        # Open claims this admin may object to: on this organization, or on hospitals this SMO is linked to.
        open_claims=c.execute('''SELECT cl.* FROM claims cl WHERE cl.status="objection_window" AND ((cl.kind="organization" AND cl.org_id=?)
            OR (cl.kind="hospital" AND cl.hospital_id IN (SELECT hospital_id FROM hospital_links WHERE smo_org_id=? AND status IN ("active","pending"))))''',(org_id,org_id)).fetchall()
        claims_on_org=[]
        for cl in open_claims:
            who=c.execute('SELECT first,last,email FROM users WHERE id=?',(cl['user_id'],)).fetchone()
            site=c.execute('SELECT name FROM organizations WHERE id=?',(cl['org_id'],)).fetchone() if cl['kind']=='hospital' else None
            claims_on_org.append({'id':cl['id'],'kind':cl['kind'],'target':claim_target(c,cl)['name'],'claimant':f'{who["first"]} {who["last"]}','claimant_email':who['email'],
                                  'claimant_org':site['name'] if site else None,'deadline':cl['deadline']})
    org=dict(o)
    for k in ('legal_doc','match_key','city_key','initials','phone_digits','place_id','domain'):org.pop(k,None)  # internal fields
    admin=m['role']=='Org Admin'
    return {'organization':org,'user_id':u['id'],'role':m['role'],'members':members if admin else [],'invitations':invitations if admin else [],'hospitals':hospitals,'pis':pi,'approvals':approvals if admin else [],'smo_links':smo_links if admin else [],'hospital_pis':hospital_pis if admin else [],'audit':audits,
            'join_requests':joins if admin else [],'claims_on_org':claims_on_org if admin else []}

def invite_role(value,allowed):
    """Only roles the form offers are accepted; 'Others: <text>' needs a short plain description."""
    r=clean(value)
    if r.startswith('Others'):
        txt=clean(re.sub(r'^Others:?','',r))
        require(0<len(txt)<=60 and re.fullmatch(r"[\w .,&()/'+-]+",txt),'Describe the other role in plain words (up to 60 characters)')
        return 'Others: '+txt
    require(r in allowed,'Select a valid role for this invitation')
    return r

def send_invite_message(c,iid,org_name):
    """Give an invitation a fresh link and validity; any earlier link stops working. Returns the raw token."""
    raw=secrets.token_urlsafe(32)
    c.execute('UPDATE invitations SET token_hash=?,expires=?,status="pending" WHERE id=?',(hashlib.sha256(raw.encode()).hexdigest(),ts()+INVITE_DAYS*86400,iid))
    target=c.execute('SELECT email FROM invitations WHERE id=?',(iid,)).fetchone()['email']
    # BRD 14.2.2: existing account -> affiliation invitation (sign in); otherwise a registration invitation.
    if c.execute('SELECT 1 FROM users WHERE email=? AND status!="deleted"',(target,)).fetchone():
        text=f'{org_name} invited you on My Trial Board. Sign in with this email address to accept. The invitation is valid for {INVITE_DAYS} days: {mailer.app_url()}/#invite={raw}'
    else:
        text=f'{org_name} invited you to join My Trial Board. Create your account with this email address to accept. The invitation is valid for {INVITE_DAYS} days: {mailer.app_url()}/#invite={raw}'
    outbox(c,target,text,'invite',subject=f'{org_name} invited you to My Trial Board',critical=True)
    return raw

@app.post('/api/invitations')
async def invite(request:Request):
    d=await request.json();oid=int(d.get('org_id',0));e=email(d.get('email'));name=clean(d.get('full_name'))
    require(name,'Invitee name required')
    kind=d.get('kind','member');require(kind in ['member','pi'],'Invalid invitation type')
    with db() as c:
        u,s=auth(request,c,True);membership(c,u['id'],oid,True)
        org=c.execute('SELECT * FROM organizations WHERE id=?',(oid,)).fetchone()
        hid=int(d.get('hospital_id') or 0) or None
        if kind=='pi':
            require(org['type']=='SMO','Only SMOs can invite affiliated PIs',403)
            require(hid is not None,'Select a hospital')
            require(c.execute('SELECT 1 FROM hospital_links WHERE smo_org_id=? AND hospital_id=? AND status="active"',(oid,hid)).fetchone(),'Hospital affiliation must be active',403)
            role=invite_role(d.get('role'),PI_LINK_ROLES)
            require(not c.execute('SELECT 1 FROM pi_links p JOIN users u ON u.id=p.user_id WHERE p.smo_org_id=? AND p.hospital_id=? AND u.email=? AND p.status="active"',(oid,hid,e)).fetchone(),'This person is already linked to your SMO at this hospital',409)
            same_hospital,args=' AND hospital_id=?',(hid,)
        else:
            role=invite_role(d.get('role'),MEMBER_ROLES.get(org['type'],[]))
            require(not c.execute('SELECT 1 FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND u.email=? AND m.status="active"',(oid,e)).fetchone(),'Already a member',409)
            hid=None;same_hospital,args='',()
        require(not c.execute(f'SELECT 1 FROM invitations WHERE org_id=? AND email=? AND kind=? AND status="pending" AND expires>?{same_hospital}',(oid,e,kind,ts())+args).fetchone(),
                'An invitation to this email is already waiting. Resend or cancel it from the Invitations tab.',409)
        c.execute('INSERT INTO invitations(token_hash,org_id,hospital_id,kind,role,full_name,email,phone,designation,department,invited_by,expires,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(secrets.token_hex(32),oid,hid,kind,role,name,e,clean(d.get('phone')),clean(d.get('designation')),clean(d.get('department')),u['id'],0,now()))
        iid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        raw=send_invite_message(c,iid,org['name'])
        if kind=='member':c.execute('UPDATE join_requests SET status="invited" WHERE org_id=? AND email=? AND status="pending"',(oid,e))
        audit(c,u['id'],'invitation_sent','invitation',iid,oid,{'kind':kind,'role':role},hospital_id=hid)
    return {'ok':True,'invitation_id':iid,'dev_invite_token':raw if DEV else None}

def admin_invitation(c,request,iid):
    """The invitation, if the caller is an admin of its organization and it is still waiting."""
    u,s=auth(request,c,True)
    i=c.execute('SELECT i.*,o.name org_name FROM invitations i JOIN organizations o ON o.id=i.org_id WHERE i.id=?',(iid,)).fetchone()
    require(i,'Invitation not found',404);membership(c,u['id'],i['org_id'],True)
    require(i['status'] in ('pending','expired'),'Only invitations that are waiting or expired can be changed',409)
    return u,i

@app.post('/api/invitations/{iid}/resend')
def resend_invitation(iid:int,request:Request):
    with db() as c:
        u,i=admin_invitation(c,request,iid)
        raw=send_invite_message(c,iid,i['org_name'])  # also restarts the 7-day validity
        audit(c,u['id'],'invitation_resent','invitation',iid,i['org_id'],{'from':i['status'],'to':'pending'},hospital_id=i['hospital_id'])
    return {'ok':True,'dev_invite_token':raw if DEV else None}

@app.post('/api/invitations/{iid}/cancel')
def cancel_invitation(iid:int,request:Request):
    with db() as c:
        u,i=admin_invitation(c,request,iid)
        c.execute('UPDATE invitations SET status="cancelled" WHERE id=?',(iid,))
        audit(c,u['id'],'invitation_cancelled','invitation',iid,i['org_id'],{'from':i['status'],'to':'cancelled'},hospital_id=i['hospital_id'])
    return {'ok':True}

@app.get('/api/invitation/{token}')
def invitation_detail(token:str):
    digest=hashlib.sha256(token.encode()).hexdigest()
    with db() as c:
        i=c.execute('SELECT i.*,o.name org_name FROM invitations i JOIN organizations o ON o.id=i.org_id WHERE i.token_hash=?',(digest,)).fetchone()
        require(i and i['status']=='pending' and i['expires']>ts(),'Invitation invalid or expired',404)
        has=bool(c.execute('SELECT 1 FROM users WHERE email=? AND status!="deleted"',(i['email'],)).fetchone())
        return {'org_name':i['org_name'],'email':i['email'],'full_name':i['full_name'],'kind':i['kind'],'role':i['role'],'has_account':has}

def answer_invitation(c,u,i,decision):
    require(i,'Invitation invalid or expired',404)
    require(u['email']==i['email'],'Invitation belongs to another email address',403)
    if decision=='accept':
        if i['kind']=='member':
            # An active member keeps their current role, so an invitation can never downgrade an admin.
            c.execute('''INSERT INTO memberships(user_id,org_id,role,status,designation,department,created) VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,org_id) DO UPDATE SET
                role=CASE WHEN status="active" THEN role ELSE excluded.role END,
                designation=CASE WHEN status="active" THEN designation ELSE excluded.designation END,
                department=CASE WHEN status="active" THEN department ELSE excluded.department END,status="active"''',
                (u['id'],i['org_id'],i['role'],'active',i['designation'] or None,i['department'] or None,now()))
            audit(c,u['id'],'role_granted','user',u['id'],i['org_id'],{'role':i['role'],'designation':i['designation'] or None,'via':'invitation'})
        else:
            require(c.execute('SELECT 1 FROM hospital_links WHERE smo_org_id=? AND hospital_id=? AND status="active"',(i['org_id'],i['hospital_id'])).fetchone(),'Hospital affiliation no longer active',403)
            c.execute('INSERT INTO pi_links(smo_org_id,hospital_id,user_id,role,status,created) VALUES(?,?,?,?,?,?) ON CONFLICT(smo_org_id,hospital_id,user_id) DO UPDATE SET status="active",role=excluded.role',(i['org_id'],i['hospital_id'],u['id'],i['role'],'active',now()))
            audit(c,u['id'],'pi_link_created','hospital',i['hospital_id'],i['org_id'],{'pi':u['email'],'role':i['role'],'smo_org_id':i['org_id'],'to':'active'})
    c.execute('UPDATE invitations SET status=? WHERE id=?',('accepted' if decision=='accept' else 'rejected',i['id']))
    audit(c,u['id'],'invitation_'+('accepted' if decision=='accept' else 'rejected'),'invitation',i['id'],i['org_id'],{'from':'pending','to':'accepted' if decision=='accept' else 'rejected'},hospital_id=i['hospital_id'])

@app.post('/api/invitation/{token}/respond')
async def respond_invitation(token:str,request:Request):
    d=await request.json();decision=d.get('decision');require(decision in ('accept','reject'),'Select accept or reject')
    digest=hashlib.sha256(token.encode()).hexdigest()
    with db() as c:
        u,s=auth(request,c,True)
        answer_invitation(c,u,c.execute('SELECT * FROM invitations WHERE token_hash=? AND status="pending" AND expires>?',(digest,ts())).fetchone(),decision)
    return {'ok':True}

@app.post('/api/invitations/{iid}/respond')
async def respond_invitation_in_app(iid:int,request:Request):
    """Signed-in users answer invitations sent to their own email from the dashboard, without the email link."""
    d=await request.json();decision=d.get('decision');require(decision in ('accept','reject'),'Select accept or reject')
    with db() as c:
        u,s=auth(request,c,True)
        answer_invitation(c,u,c.execute('SELECT * FROM invitations WHERE id=? AND status="pending" AND expires>?',(iid,ts())).fetchone(),decision)
    return {'ok':True}

def hospital_matches(c,name,city,pin='',site=''):
    """Hospitals that may be the same site (BRD 4.2.1): similar name in the same city, same PIN with a similar name, or the same website."""
    ck,mk,found=city_key(city),match_key(name),{}
    def hit(where,args,reason):
        for r in c.execute(f'SELECT id,name,city,state,pin,org_id FROM hospitals WHERE {where}',args).fetchall():
            m=found.setdefault(r['id'],{'id':r['id'],'name':r['name'],'city':r['city'],'state':r['state'],'pin':r['pin'],'registered':bool(r['org_id']),'reasons':[]})
            if reason not in m['reasons']:m['reasons'].append(reason)
    if mk and ck:hit('match_key=? AND city_key=?',(mk,ck),'Very similar name in the same city')
    if mk and clean(pin):hit('pin=? AND substr(match_key,1,4)=?',(clean(pin),mk[:4]),'Same PIN code and a similar name')
    dom=site_domain(site)
    if dom:hit('domain=?',(dom,),'Same website')
    return list(found.values())

@app.post('/api/hospitals')
async def add_hospital(request:Request):
    d=await request.json();oid=int(d.get('org_id',0));name=clean(d.get('name'))
    for f in ['name','type','address1','city','state','country','pin']:require(clean(d.get(f)),f'{f} required')
    htype=option(d['type'],HOSPITAL_TYPES,'hospital type')
    hphone=phone(d['phone'],'hospital contact number') if clean(d.get('phone')) else ''
    hsite=website(d.get('website'))
    with db() as c:
        u,s=auth(request,c,True);membership(c,u['id'],oid,True)
        require(c.execute('SELECT 1 FROM organizations WHERE id=? AND type="SMO"',(oid,)).fetchone(),'SMO required',403)
        pick=int(d.get('hospital_id') or 0)  # an existing record chosen from the suggestions
        h=c.execute('SELECT * FROM hospitals WHERE id=?',(pick,)).fetchone() if pick else c.execute('SELECT * FROM hospitals WHERE normalized=? AND city_key=?',(norm(name),city_key(d['city']))).fetchone()
        if pick:require(h,'Hospital not found',404)
        likely=[] if h else hospital_matches(c,name,d['city'],d.get('pin',''),d.get('website',''))
        if likely and not d.get('different_confirmed'):
            # BRD 4.2.4: an ambiguous match is reviewed before a second record is created.
            raise HTTPException(409,{'code':'possible_duplicate','message':'This looks like a hospital already on My Trial Board. Is it the same one?','matches':likely})
        if not h:
            # BRD 4.3: an unregistered site is added only after the SMO signs the declaration.
            require(bool(d.get('declaration')),'Confirm the hospital declaration to add a new site')
            c.execute('INSERT INTO hospitals(name,normalized,type,acronym,address1,address2,city,state,country,pin,phone,website,provisional,place_id,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(name,norm(name),htype,clean(d.get('acronym')),clean(d['address1']),clean(d.get('address2')),clean(d['city']),clean(d['state']),clean(d['country']),clean(d['pin']),hphone,hsite,1,place_ref(d.get('place_id')) or None,now()))
            hid=c.execute('SELECT last_insert_rowid()').fetchone()[0];status='active'
            set_signals(c,'hospitals',hid)
            c.execute('INSERT INTO consents(user_id,org_id,kind,version,accepted_at) VALUES(?,?,?,?,?)',(u['id'],oid,'hospital_declaration:'+str(hid),'1.0',now()))
            if likely:audit(c,u['id'],'hospital_duplicate_override','hospital',hid,oid,{'name':name,'similar_to':[{'id':m['id'],'name':m['name']} for m in likely]})
        else:hid=h['id'];status='pending' if h['org_id'] else 'active'
        # A rejected or removed SMO may ask again; an open or approved link is not duplicated.
        old=c.execute('SELECT id,status FROM hospital_links WHERE hospital_id=? AND smo_org_id=?',(hid,oid)).fetchone()
        require(not old or old['status'] in CLOSED_LINKS,'Hospital already associated',409)
        if old:c.execute('UPDATE hospital_links SET status=?,requested_by=?,created=? WHERE id=?',(status,u['id'],now(),old['id']));changed={'from':old['status'],'to':status}
        else:changed={'to':status}
        if not old:c.execute('INSERT INTO hospital_links(smo_org_id,hospital_id,status,requested_by,created) VALUES(?,?,?,?,?)',(oid,hid,status,u['id'],now()))
        audit(c,u['id'],'hospital_affiliation_'+status,'hospital',hid,oid,changed)
        if status=='pending':notify_hospital_admins(c,hid,oid)
    return {'ok':True,'hospital_id':hid,'status':status}

def notify_hospital_admins(c,hid,smo_id):
    h=c.execute('SELECT name,org_id FROM hospitals WHERE id=?',(hid,)).fetchone()
    smo=c.execute('SELECT name FROM organizations WHERE id=?',(smo_id,)).fetchone()
    if h and h['org_id']:
        for e in admin_emails(c,h['org_id']):outbox(c,e,f'{smo["name"]} asked to affiliate with {h["name"]} on My Trial Board. Approve or reject it on your dashboard under Hospitals / Sites.',subject=f'Affiliation request from {smo["name"]}')

# ---------- 2. The SMO that added a provisional hospital completes its site profile (BRD 4.3) ----------
def hospital_editor(c,u,hid):
    h=c.execute('SELECT * FROM hospitals WHERE id=?',(hid,)).fetchone();require(h,'Hospital not found',404)
    require(h['org_id'] is None,'This hospital is registered on MTB and manages its own profile',403)
    first=c.execute('SELECT smo_org_id FROM hospital_links WHERE hospital_id=? ORDER BY id LIMIT 1',(hid,)).fetchone()
    require(first,'Hospital not found',404)
    membership(c,u['id'],first['smo_org_id'],True)  # only admins of the SMO that added it
    return h,first['smo_org_id']

@app.get('/api/hospitals/{hid}')
def hospital_detail(hid:int,request:Request):
    with db() as c:
        u,s=auth(request,c);h,_=hospital_editor(c,u,hid)
        return {k:h[k] for k in ('id','name','acronym','type','address1','address2','city','state','country','pin','phone','website')}

@app.put('/api/hospitals/{hid}')
async def edit_hospital(hid:int,request:Request):
    d=await request.json()
    for f in ['name','type','address1','city','state','country','pin']:require(clean(d.get(f)),f'{f} required')
    new={'name':clean(d['name']),'acronym':clean(d.get('acronym')),'type':option(d['type'],HOSPITAL_TYPES,'hospital type'),'address1':clean(d['address1']),
         'address2':clean(d.get('address2')),'city':clean(d['city']),'state':clean(d['state']),'country':clean(d['country']),'pin':clean(d['pin']),
         'phone':phone(d['phone'],'hospital contact number') if clean(d.get('phone')) else '','website':website(d.get('website'))}
    with db() as c:
        u,s=auth(request,c,True);h,smo=hospital_editor(c,u,hid)
        require(not c.execute('SELECT 1 FROM hospitals WHERE normalized=? AND city_key=? AND id!=?',(norm(new['name']),city_key(new['city']),hid)).fetchone(),
                'Another hospital with this name is already on MTB in this city',409)
        changed={k:{'from':h[k] or '','to':v or ''} for k,v in new.items() if (h[k] or '')!=(v or '')}
        if changed:
            c.execute('UPDATE hospitals SET name=?,normalized=?,acronym=?,type=?,address1=?,address2=?,city=?,state=?,country=?,pin=?,phone=?,website=? WHERE id=?',
                      (new['name'],norm(new['name']),new['acronym'],new['type'],new['address1'],new['address2'],new['city'],new['state'],new['country'],new['pin'],new['phone'],new['website'],hid))
            set_signals(c,'hospitals',hid)
            audit(c,u['id'],'hospital_profile_updated','hospital',hid,smo,{'changes':changed})
    return {'ok':True,'changed':sorted(changed)}

@app.get('/api/hospital-search')
def hospital_search(q:str,request:Request):
    with db() as c:
        u,s=auth(request,c)
        q=norm(q)
        if len(q)<2:return {'results':[]}
        rows=c.execute('SELECT id,name,acronym,type,address1,address2,city,state,country,pin,phone,website,provisional,org_id FROM hospitals WHERE normalized LIKE ? OR lower(coalesce(acronym,"")) LIKE ? LIMIT 8',('%'+q+'%','%'+q+'%'))
        return {'results':[{**dict(x),'registered':bool(x['org_id'])} for x in rows]}

@app.post('/api/hospital-links/{link_id}/decision')
async def hospital_decision(link_id:int,request:Request):
    d=await request.json();decision=d.get('decision')
    # Approve or reject a pending request; remove an SMO that was already approved.
    needs={'active':'pending','rejected':'pending','removed':'active'}
    require(decision in needs,'Invalid decision')
    with db() as c:
        u,s=auth(request,c,True)
        link=c.execute('SELECT hl.*,h.org_id FROM hospital_links hl JOIN hospitals h ON h.id=hl.hospital_id WHERE hl.id=?',(link_id,)).fetchone()
        require(link and link['org_id'],'Registered hospital affiliation only',404)
        membership(c,u['id'],link['org_id'],True)
        require(link['status']==needs[decision],'This affiliation has already changed. Refresh the page.',409)
        c.execute('UPDATE hospital_links SET status=? WHERE id=?',(decision,link_id))
        if decision=='removed':
            # The SMO's PIs at this hospital lose that link too; open PI invites already fail without an active link.
            c.execute('UPDATE pi_links SET status="inactive" WHERE smo_org_id=? AND hospital_id=?',(link['smo_org_id'],link['hospital_id']))
        audit(c,u['id'],'hospital_affiliation_'+decision,'hospital',link['hospital_id'],link['org_id'],{'smo_org_id':link['smo_org_id'],'from':link['status'],'to':decision})
    return {'ok':True}

@app.post('/api/hospital-links/{link_id}/request-again')
def hospital_request_again(link_id:int,request:Request):
    with db() as c:
        u,s=auth(request,c,True)
        link=c.execute('SELECT hl.*,h.org_id FROM hospital_links hl JOIN hospitals h ON h.id=hl.hospital_id WHERE hl.id=?',(link_id,)).fetchone()
        require(link,'Affiliation not found',404)
        membership(c,u['id'],link['smo_org_id'],True)
        require(link['status'] in CLOSED_LINKS,'This affiliation is already pending or active',409)
        status='pending' if link['org_id'] else 'active'
        c.execute('UPDATE hospital_links SET status=?,requested_by=?,created=? WHERE id=?',(status,u['id'],now(),link_id))
        audit(c,u['id'],'hospital_affiliation_'+status,'hospital',link['hospital_id'],link['smo_org_id'],{'request_again':True,'from':link['status'],'to':status})
        if status=='pending':notify_hospital_admins(c,link['hospital_id'],link['smo_org_id'])
    return {'ok':True,'status':status}

@app.post('/api/memberships/{member_id}/deactivate')
def deactivate(member_id:int,request:Request):
    with db() as c:
        u,s=auth(request,c,True);m=c.execute('SELECT * FROM memberships WHERE id=?',(member_id,)).fetchone()
        require(m,'Membership not found',404);membership(c,u['id'],m['org_id'],True)
        require(m['user_id']!=u['id'],'Cannot deactivate your own admin membership',422)
        c.execute('UPDATE memberships SET status="inactive" WHERE id=?',(member_id,))
        audit(c,u['id'],'membership_deactivated','membership',member_id,m['org_id'],{'role':m['role'],'from':m['status'],'to':'inactive'})
    return {'ok':True}

@app.post('/api/recovery/request')
async def recovery_request(request:Request):
    rate_limit(request,'recovery',10,900)  # per IP: 10 requests per 15 minutes
    d=await request.json()
    try:e=email(d.get('email'))
    except HTTPException:return {'ok':True,'message':'If the account exists, a recovery code will be sent.'}
    with db() as c:
        # BRD 11.1: recovery only through previously verified channels.
        u=recovery_user(c,e)
        if u:
            try:send_otp(c,u['id'],e,'email','recovery')
            except HTTPException:pass  # keep the response generic
            audit(c,u['id'],'recovery_requested','user',u['id'])
    return {'ok':True,'message':'If the account exists, a recovery code will be sent.'}

RESET_PASS_SECONDS=600  # time to choose a new password after the code is verified

def recovery_user(c,e):
    return c.execute('SELECT * FROM users WHERE (email=? OR (alt_email=? AND alt_email_verified=1)) AND status NOT IN ("blocked","deleted")',(e,e)).fetchone()

def issue_reset_pass(c,uid):
    """Single-use pass (10 minutes) that lets this person set a new password without another code."""
    reset=secrets.token_urlsafe(32)
    c.execute('UPDATE otps SET used=1 WHERE user_id=? AND channel="reset"',(uid,))
    c.execute('INSERT INTO otps(user_id,channel,purpose,code_hash,expires,created) VALUES(?,?,?,?,?,?)',(uid,'reset','recovery',otp_hash(uid,reset,'recovery'),ts()+RESET_PASS_SECONDS,ts()))
    return reset

@app.post('/api/recovery/verify')
async def recovery_verify(request:Request):
    """Step 2 of recovery: check the emailed code and hand back a single-use reset pass."""
    rate_limit(request,'recovery-verify',30,900)
    d=await request.json();e=email(d.get('email'))
    with db() as c:
        u=recovery_user(c,e)
        require(u,'Invalid or expired code',400)  # same reply as a wrong code, so accounts are not revealed
        try:verify_otp(c,u['id'],'email','recovery',d.get('code',''))
        except HTTPException:
            audit(c,u['id'],'recovery_code_failed','user',u['id'],ip=request.client.host if request.client else None);c.commit();raise
        reset=issue_reset_pass(c,u['id'])
        audit(c,u['id'],'recovery_code_verified','user',u['id'])
    return {'ok':True,'reset_token':reset,'expires_in':RESET_PASS_SECONDS}

@app.post('/api/recovery/complete')
async def recovery_complete(request:Request):
    """Step 3 of recovery: set the new password with the reset pass from step 2."""
    d=await request.json();e=email(d.get('email'));pw=d.get('new_password','')
    require(password_valid(pw),'Password does not meet policy')
    require(pw==d.get('confirm',pw),'Passwords do not match')
    with db() as c:
        u=recovery_user(c,e)
        require(u,'Your reset session has expired. Please start again.',400)
        try:verify_otp(c,u['id'],'reset','recovery',d.get('reset_token',''))
        except HTTPException:raise HTTPException(400,'Your reset session has expired. Please start again.')
        c.execute('UPDATE users SET password_hash=?,failed=0,locked_until=0 WHERE id=?',(hasher.hash(pw),u['id']))
        set_attempts(c,attempts(c,u['email'])[0],0,0)
        c.execute('UPDATE sessions SET revoked=1 WHERE user_id=?',(u['id'],))
        audit(c,u['id'],'password_reset','user',u['id'])
    return {'ok':True}

# Personal account events (no organization attached) that an Org Admin sees for their own members.
ACCOUNT_EVENTS=('login_success','login_failed','account_locked','unlock_requested','unlock_code_failed','account_unlocked','recovery_requested',
                'recovery_code_verified','recovery_code_failed','password_reset','logout','account_activated',
                'registration_email_verified','registration_phone_verified','registration_alt_email_verified')

@app.get('/api/organizations/{oid}/audit')
def org_audit(oid:int,request:Request,limit:int=1000):
    """Audit trail for one organization, visible to its Org Admins only. Never includes another organization's events."""
    with db() as c:
        housekeeping(c)
        u,s=auth(request,c);membership(c,u['id'],oid,True)
        marks=','.join('?'*len(ACCOUNT_EVENTS))
        rows=c.execute(f'''SELECT a.id,a.action,a.subject_type,a.subject_id,a.details,a.ip,a.created,au.first||' '||au.last actor_name,au.email actor_email,
              CASE a.subject_type
                WHEN 'user' THEN (SELECT x.first||' '||x.last||' ('||x.email||')' FROM users x WHERE x.id=a.subject_id)
                WHEN 'hospital' THEN (SELECT name FROM hospitals WHERE id=a.subject_id)
                WHEN 'invitation' THEN (SELECT full_name||' ('||email||')' FROM invitations WHERE id=a.subject_id)
                WHEN 'membership' THEN (SELECT x.first||' '||x.last||' ('||x.email||')' FROM memberships m JOIN users x ON x.id=m.user_id WHERE m.id=a.subject_id)
                WHEN 'organization' THEN (SELECT name FROM organizations WHERE id=a.subject_id)
              END subject_name,
              o.name org_name
            FROM audit a LEFT JOIN users au ON au.id=a.actor_id LEFT JOIN organizations o ON o.id=a.org_id
            WHERE a.org_id=?
               OR (a.subject_type='hospital' AND a.subject_id IN (SELECT id FROM hospitals WHERE org_id=?))
               OR json_extract(a.details,'$.smo_org_id')=?
               OR (a.org_id IS NULL AND (a.action IN ({marks}) OR a.action LIKE 'mtb_admin_user_%')
                   AND coalesce(CASE WHEN a.subject_type='user' THEN a.subject_id END,a.actor_id) IN (SELECT user_id FROM memberships WHERE org_id=?))
            ORDER BY a.id DESC LIMIT ?''',(oid,oid,oid,*ACCOUNT_EVENTS,oid,max(1,min(limit,5000)))).fetchall()
        return {'events':[dict(r) for r in rows]}

# ---------- MTB Admin console: platform analytics, people, organizations, activity ----------
# MTB Admins are the emails in MTB_ADMIN_EMAILS. They see and manage registration data across the platform.
# BRD 15.4: once trials exist, trial and patient data must stay outside this console.

def mtb_admin(request,c,csrf=False):
    u,s=auth(request,c,csrf)
    require(u['email'] in mtb_admins(),'MTB Admin only',403)
    return u

def days_back(n):
    """ISO dates for the last n days, oldest first."""
    today=datetime.now(timezone.utc).date()
    return [(today-timedelta(days=i)).isoformat() for i in range(n-1,-1,-1)]

def per_day(c,sql,args,n):
    counts={r['d']:r['n'] for r in c.execute(sql,args)}
    return [{'date':d,'count':counts.get(d,0)} for d in days_back(n)]

@app.get('/api/admin/overview')
def admin_overview(request:Request):
    with db() as c:
        mtb_admin(request,c)
        one=lambda sql,*a:c.execute(sql,a).fetchone()[0]
        week=(datetime.now(timezone.utc)-timedelta(days=7)).isoformat()
        month_start=days_back(30)[0]
        users={r['status']:r['n'] for r in c.execute('SELECT status,COUNT(*) n FROM users GROUP BY status')}
        orgs={r['status']:r['n'] for r in c.execute('SELECT status,COUNT(*) n FROM organizations GROUP BY status')}
        inv={r['status']:r['n'] for r in c.execute('SELECT status,COUNT(*) n FROM invitations GROUP BY status')}
        by_type=[dict(r) for r in c.execute('SELECT type,COUNT(*) n FROM organizations WHERE status NOT IN ("deleted") GROUP BY type ORDER BY n DESC')]
        recent=[dict(r) for r in c.execute('''SELECT u.id,u.first,u.last,u.email,u.status,u.created,
            (SELECT group_concat(o.name||' ('||m.role||')','; ') FROM memberships m JOIN organizations o ON o.id=m.org_id WHERE m.user_id=u.id AND m.status="active") orgs
            FROM users u WHERE u.status!="deleted" ORDER BY u.id DESC LIMIT 10''')]
        return {
            'users':{'total':sum(v for k,v in users.items() if k!='deleted'),'active':users.get('active',0),'pending':users.get('pending',0),'blocked':users.get('blocked',0),
                     'new_7d':one('SELECT COUNT(*) FROM users WHERE created>=? AND status!="deleted"',week)},
            'orgs':{'total':sum(v for k,v in orgs.items() if k!='deleted'),'active':orgs.get('active',0),'pending':orgs.get('pending',0),'blocked':orgs.get('blocked',0),'by_type':by_type},
            'invitations':{'sent':sum(inv.values()),'accepted':inv.get('accepted',0),'pending':one('SELECT COUNT(*) FROM invitations WHERE status="pending" AND expires>?',ts()),
                           'rejected':inv.get('rejected',0),'cancelled':inv.get('cancelled',0)},
            'links':{'hospital_active':one('SELECT COUNT(*) FROM hospital_links WHERE status="active"'),'hospital_pending':one('SELECT COUNT(*) FROM hospital_links WHERE status="pending"'),
                     'pi_active':one('SELECT COUNT(*) FROM pi_links WHERE status="active"'),'hospitals':one('SELECT COUNT(*) FROM hospitals'),
                     'provisional':one('SELECT COUNT(*) FROM hospitals WHERE org_id IS NULL')},
            'security':{'logins_7d':one('SELECT COUNT(*) FROM audit WHERE action="login_success" AND created>=?',week),
                        'failed_7d':one('SELECT COUNT(*) FROM audit WHERE action IN ("login_failed","account_locked") AND created>=?',week),
                        'locked_now':one('SELECT COUNT(*) FROM login_attempts WHERE locked_until>?',ts()),
                        'open_claims':one('SELECT COUNT(*) FROM claims WHERE status IN ("objection_window","disputed","awaiting_verification")')},
            'signups':per_day(c,'SELECT substr(created,1,10) d,COUNT(*) n FROM users WHERE created>=? AND status!="deleted" GROUP BY d',(month_start,),30),
            'logins':per_day(c,'SELECT substr(created,1,10) d,COUNT(*) n FROM audit WHERE action="login_success" AND created>=? GROUP BY d',(month_start,),30),
            'recent_users':recent,'duplicate_people':duplicate_people(c),
            'hospital_reviews':[{**dict(r),'details':json.loads(r['details'] or '{}')} for r in c.execute('''SELECT a.created,a.subject_id hospital_id,h.name hospital,u.email by_email,o.name by_org,a.details
                FROM audit a LEFT JOIN hospitals h ON h.id=a.subject_id LEFT JOIN users u ON u.id=a.actor_id LEFT JOIN organizations o ON o.id=a.org_id
                WHERE a.action="hospital_duplicate_override" ORDER BY a.id DESC LIMIT 20''')]}

def duplicate_people(c):
    """BRD 19.2: accounts sharing a phone number may be the same person with two emails. Shown for MTB Admin review."""
    groups={}
    for r in c.execute('SELECT id,first,last,email,phone,status FROM users WHERE status!="deleted" AND phone!=""'):
        key=re.sub(r'\D','',r['phone'] or '')[-10:]
        if len(key)>=7:groups.setdefault(key,[]).append({'id':r['id'],'name':f"{r['first']} {r['last']}",'email':r['email'],'status':r['status']})
    return [{'phone':'••••••'+k[-4:],'accounts':v} for k,v in groups.items() if len(v)>1]

@app.get('/api/admin/audit-integrity')
def admin_audit_integrity(request:Request):
    with db() as c:
        mtb_admin(request,c)
        return verify_audit_chain(c)

@app.get('/api/admin/email-status')
def admin_email_status(request:Request):
    with db() as c:
        mtb_admin(request,c)
        today=datetime.now(timezone.utc).date().isoformat()
        counts={r['status']:r['n'] for r in c.execute('SELECT status,COUNT(*) n FROM outbox WHERE created>=? GROUP BY status',(today,))}
        last_error=c.execute('SELECT error,created FROM outbox WHERE status="failed" ORDER BY id DESC LIMIT 1').fetchone()
    return {**mailer.account_status(),'sent_today':counts.get('sent',0),'failed_today':counts.get('failed',0),'daily_limit':300,
            'last_error':dict(last_error) if last_error else None}

@app.post('/api/admin/test-email')
def admin_test_email(request:Request):
    with db() as c:
        u=mtb_admin(request,c,True)
        require(mailer.enabled(),'Email delivery is not set up yet. Add BREVO_API_KEY to .env and restart the site.',409)
        outbox(c,u['email'],'This is a test email from My Trial Board. If you can read it, email delivery through Brevo is working.',subject='My Trial Board test email',critical=True)
        audit(c,u['id'],'mtb_admin_test_email','user',u['id'])
    return {'ok':True,'to':u['email']}

@app.get('/api/admin/users')
def admin_users(request:Request,q:str='',status:str=''):
    with db() as c:
        mtb_admin(request,c)
        where,args=['u.status!="deleted"'],[]
        if q.strip():where.append('(lower(u.first||" "||u.last) LIKE ? OR lower(u.email) LIKE ? OR u.phone LIKE ?)');args+=[f'%{q.strip().lower()}%']*3
        if status:where.append('u.status=?');args.append(status)
        rows=[dict(r) for r in c.execute(f'''SELECT u.id,u.first,u.last,u.email,u.phone,u.designation,u.status,u.created,
            (SELECT MAX(created) FROM audit a WHERE a.actor_id=u.id AND a.action="login_success") last_login,
            (SELECT group_concat(o.name||' · '||m.role||coalesce(' · '||coalesce(m.designation,u.designation),''),'; ') FROM memberships m JOIN organizations o ON o.id=m.org_id WHERE m.user_id=u.id AND m.status="active") orgs,
            (SELECT COUNT(*) FROM pi_links p WHERE p.user_id=u.id AND p.status="active") pi_links
            FROM users u WHERE {' AND '.join(where)} ORDER BY u.id DESC LIMIT 500''',args)]
        admins=mtb_admins()
        for r in rows:
            r['locked']=attempts(c,r['email'])[2]>ts();r['mtb_admin']=r['email'] in admins
        return {'users':rows}

@app.get('/api/admin/organizations')
def admin_orgs(request:Request,q:str='',type:str='',status:str=''):
    with db() as c:
        mtb_admin(request,c)
        where,args=['o.status!="deleted"'],[]
        if q.strip():where.append('(lower(o.name) LIKE ? OR lower(o.city) LIKE ?)');args+=[f'%{q.strip().lower()}%']*2
        if type:where.append('o.type=?');args.append(type)
        if status:where.append('o.status=?');args.append(status)
        return {'organizations':[dict(r) for r in c.execute(f'''SELECT o.id,o.name,o.type,o.subtype,o.city,o.state,o.status,o.created,o.website,
            (SELECT COUNT(*) FROM memberships m WHERE m.org_id=o.id AND m.status="active") members,
            (SELECT group_concat(u.email,', ') FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.org_id=o.id AND m.role="Org Admin" AND m.status="active") admins
            FROM organizations o WHERE {' AND '.join(where)} ORDER BY o.id DESC LIMIT 500''',args)]}

@app.get('/api/admin/organizations/{oid}')
def admin_org_detail(oid:int,request:Request):
    with db() as c:
        mtb_admin(request,c)
        o=c.execute('SELECT * FROM organizations WHERE id=? AND status!="deleted"',(oid,)).fetchone();require(o,'Organization not found',404)
        org=dict(o)
        for k in ('legal_doc','match_key','city_key','initials','phone_digits','exact_key','normalized'):org.pop(k,None)
        q=lambda sql,*a:[dict(r) for r in c.execute(sql,a)]
        return {'organization':org,
            'members':q('SELECT u.id,u.first,u.last,u.email,m.role,coalesce(m.designation,u.designation) designation,m.department,m.status,m.created FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.org_id=? ORDER BY m.status="active" DESC,m.id',oid),
            'invitations':q('SELECT id,full_name,email,kind,role,status,created FROM invitations WHERE org_id=? ORDER BY id DESC LIMIT 50',oid),
            'hospital_links':q('SELECT hl.id,h.name hospital,o.name smo,hl.status,hl.created FROM hospital_links hl JOIN hospitals h ON h.id=hl.hospital_id JOIN organizations o ON o.id=hl.smo_org_id WHERE hl.smo_org_id=? OR h.org_id=? ORDER BY hl.id DESC',oid,oid),
            'pis':q('SELECT p.id,u.first,u.last,u.email,p.role,h.name hospital,o.name smo,p.status FROM pi_links p JOIN users u ON u.id=p.user_id JOIN hospitals h ON h.id=p.hospital_id JOIN organizations o ON o.id=p.smo_org_id WHERE p.smo_org_id=? OR h.org_id=? ORDER BY p.id DESC',oid,oid),
            'activity':q('SELECT a.action,a.created,a.ip,u.email actor FROM audit a LEFT JOIN users u ON u.id=a.actor_id WHERE a.org_id=? ORDER BY a.id DESC LIMIT 40',oid)}

@app.get('/api/admin/activity')
def admin_activity(request:Request,q:str='',limit:int=200):
    with db() as c:
        mtb_admin(request,c)
        where,args='',[]
        if q.strip():where='WHERE (a.action LIKE ? OR lower(coalesce(u.email,"")) LIKE ? OR lower(coalesce(o.name,"")) LIKE ?)';args=[f'%{q.strip().lower()}%']*3
        return {'activity':[dict(r) for r in c.execute(f'''SELECT a.id,a.action,a.subject_type,a.subject_id,a.created,a.ip,a.details,u.email actor,o.name org
            FROM audit a LEFT JOIN users u ON u.id=a.actor_id LEFT JOIN organizations o ON o.id=a.org_id {where} ORDER BY a.id DESC LIMIT ?''',args+[max(1,min(limit,1000))])]}

def sole_admin_of(c,uid):
    """Active organizations where this person is the only active Org Admin."""
    return [r['name'] for r in c.execute('''SELECT o.name FROM memberships m JOIN organizations o ON o.id=m.org_id
        WHERE m.user_id=? AND m.role="Org Admin" AND m.status="active" AND o.status IN ("active","pending")
        AND (SELECT COUNT(*) FROM memberships x WHERE x.org_id=m.org_id AND x.role="Org Admin" AND x.status="active")=1''',(uid,))]

@app.post('/api/admin/users/{uid}/action')
async def admin_user_action(uid:int,request:Request):
    d=await request.json();action=d.get('action')
    require(action in ('block','unblock','unlock','signout','delete'),'Unknown action')
    with db() as c:
        me=mtb_admin(request,c,True)
        u=c.execute('SELECT * FROM users WHERE id=? AND status!="deleted"',(uid,)).fetchone();require(u,'User not found',404)
        require(u['email'] not in mtb_admins(),'MTB Admin accounts cannot be changed here',409)
        if action=='block':
            require(u['status']!='blocked','Already blocked',409)
            c.execute('UPDATE users SET status="blocked" WHERE id=?',(uid,));c.execute('UPDATE sessions SET revoked=1 WHERE user_id=?',(uid,))
        elif action=='unblock':
            require(u['status']=='blocked','This account is not blocked',409)
            verified=u['email_verified'] and u['phone_verified']
            c.execute('UPDATE users SET status=? WHERE id=?',('active' if verified else 'pending',uid))
        elif action=='unlock':
            set_attempts(c,attempts(c,u['email'])[0],0,0)
        elif action=='signout':
            c.execute('UPDATE sessions SET revoked=1 WHERE user_id=?',(uid,))
        else:
            sole=sole_admin_of(c,uid)
            require(not sole,f'This person is the only admin of {", ".join(sole)}. Delete or block that organization first, or make someone else its admin.',409)
            # Personal details are removed; the audit trail keeps the record id only.
            c.execute('''UPDATE users SET first="Deleted",middle=NULL,last="user",designation=NULL,email=?,alt_email=NULL,phone="",alt_phone=NULL,
                password_hash=?,status="deleted" WHERE id=?''',(f'deleted-{uid}@deleted.invalid',hasher.hash(secrets.token_urlsafe(24)),uid))
            c.execute('UPDATE sessions SET revoked=1 WHERE user_id=?',(uid,))
            c.execute('UPDATE memberships SET status="inactive" WHERE user_id=?',(uid,))
            c.execute('UPDATE pi_links SET status="inactive" WHERE user_id=?',(uid,))
            c.execute('UPDATE invitations SET status="cancelled" WHERE email=? AND status="pending"',(u['email'],))
            c.execute('DELETE FROM otps WHERE user_id=?',(uid,))
            mtb_profile.erase_user(c,uid)  # profile content, uploaded CV and documents
        after=c.execute('SELECT status FROM users WHERE id=?',(uid,)).fetchone()['status']
        audit(c,me['id'],'mtb_admin_user_'+action,'user',uid,details={'email':u['email'] if action!='delete' else None,'from':u['status'],'to':after})
    return {'ok':True}

@app.post('/api/admin/organizations/{oid}/action')
async def admin_org_action(oid:int,request:Request):
    d=await request.json();action=d.get('action')
    require(action in ('block','unblock','delete'),'Unknown action')
    with db() as c:
        me=mtb_admin(request,c,True)
        o=c.execute('SELECT * FROM organizations WHERE id=? AND status!="deleted"',(oid,)).fetchone();require(o,'Organization not found',404)
        if action=='block':
            require(o['status']!='blocked','Already blocked',409)
            c.execute('UPDATE organizations SET status="blocked" WHERE id=?',(oid,))
        elif action=='unblock':
            require(o['status']=='blocked','This organization is not blocked',409)
            c.execute('UPDATE organizations SET status="active" WHERE id=?',(oid,))
        else:
            require(clean(d.get('confirm_name'))==o['name'],'Type the organization name exactly to confirm',422)
            c.execute('UPDATE organizations SET status="deleted" WHERE id=?',(oid,))
            c.execute('UPDATE memberships SET status="inactive" WHERE org_id=?',(oid,))
            c.execute('UPDATE invitations SET status="cancelled" WHERE org_id=? AND status="pending"',(oid,))
            c.execute('UPDATE join_requests SET status="dismissed" WHERE org_id=? AND status="pending"',(oid,))
            # As an SMO: its hospital links and PI links end. As a hospital: its record becomes provisional again.
            c.execute('UPDATE hospital_links SET status="removed" WHERE smo_org_id=? AND status IN ("active","pending")',(oid,))
            c.execute('UPDATE pi_links SET status="inactive" WHERE smo_org_id=?',(oid,))
            # Requests waiting for this hospital's approval have nobody to approve them now; provisional records link directly.
            c.execute('UPDATE hospital_links SET status="active" WHERE status="pending" AND hospital_id IN (SELECT id FROM hospitals WHERE org_id=?)',(oid,))
            c.execute('UPDATE hospitals SET org_id=NULL,provisional=1 WHERE org_id=?',(oid,))
        after=c.execute('SELECT status FROM organizations WHERE id=?',(oid,)).fetchone()['status']
        audit(c,me['id'],'mtb_admin_org_'+action,'organization',oid,oid,{'name':o['name'],'from':o['status'],'to':after})
    return {'ok':True}

@app.get('/api/dev/outbox')
def dev_outbox():
    require(DEV,'Not available',404)
    with db() as c:return {'messages':[dict(x) for x in c.execute('SELECT * FROM outbox ORDER BY id DESC LIMIT 20')]}

@app.get('/health')
def health():return {'status':'ok'}

@app.post('/api/invitation/{token}/register')
async def invited_registration(token:str,request:Request):
    """Invite-only account creation; activation on two verified channels."""
    d=await request.json();p=d.get('person') or {}
    digest=hashlib.sha256(token.encode()).hexdigest()
    with db() as c:
        i=c.execute('SELECT * FROM invitations WHERE token_hash=? AND status="pending" AND expires>?',(digest,ts())).fetchone()
        require(i,'Invitation invalid or expired',404)
        require(email(p.get('email'))==i['email'],'Registration email must match invitation',403)
        require(not c.execute('SELECT 1 FROM users WHERE email=?',(i['email'],)).fetchone(),'Account exists; sign in to accept invitation.',409)
        for f in ['first','last','phone','salutation','gender']: require(clean(p.get(f)),f'{f} required')
        require(p.get('salutation') in SALUTATIONS,'Invalid salutation')
        require(p.get('gender') in GENDERS,'Invalid gender')
        phone(p['phone'],'phone number')
        pw=p.get('password','');require(password_valid(pw) and pw==p.get('confirm'),'Password policy or confirmation failed')
        require(bool(d.get('terms')),'Terms acceptance required')
        c.execute('INSERT INTO users(first,middle,last,salutation,gender,designation,email,alt_email,phone,alt_phone,password_hash,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(clean(p['first']),clean(p.get('middle')),clean(p['last']),p['salutation'],p['gender'],clean(p.get('designation')),i['email'],email(p['alt_email']) if clean(p.get('alt_email')) else None,clean(p['phone']),clean(p.get('alt_phone')),hasher.hash(pw),now()))
        uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute('INSERT INTO consents(user_id,org_id,kind,version,accepted_at) VALUES(?,?,?,?,?)',(uid,i['org_id'],'terms','1.0',now()))
        # Invite response completes after successful account activation; no premature membership.
        send_otp(c,uid,i['email'],'email','registration');phone_code=send_otp(c,uid,clean(p['phone']),'phone','registration')
        audit(c,uid,'invited_user_registered','user',uid,i['org_id'])
    return {'ok':True,'registration_id':uid,**screen_code(phone_code)}

@app.get('/api/organization-claims')
def organization_claims(request:Request):
    with db() as c:
        u,s=auth(request,c)
        return {'memberships':[dict(x) for x in c.execute('SELECT m.org_id,o.name,m.role,m.status FROM memberships m JOIN organizations o ON o.id=m.org_id WHERE m.user_id=?',(u['id'],))]}

# ---------- Module 02: My Profile (CV auto-fill, sections, declaration, CV export). See mtb_profile.py ----------
import sys, mtb_profile
mtb_profile.attach(sys.modules[__name__])
