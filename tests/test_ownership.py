"""Duplicate organizations, join requests, expiry of unverified registrations and ownership claims."""
import os,sys,re,tempfile,sqlite3
from pathlib import Path
_tmp=Path(tempfile.mkdtemp())
os.environ.setdefault('MTB_DEV_MODE','1')
os.environ['BREVO_API_KEY']=''  # tests never send real email
os.environ['BREVO_SMTP_KEY']='';os.environ['BREVO_SMTP_LOGIN']=''
os.environ['MTB_PHONE_CODE_ON_SCREEN']='0'
os.environ.setdefault('MTB_SECRET','a-long-test-key-for-local-tests-012345')
os.environ.setdefault('MTB_DB',str(_tmp/'mtb_test.db'))
os.environ.setdefault('MTB_UPLOADS',str(_tmp/'uploads'))
os.environ['MTB_ADMIN_EMAILS']='ops@mtb-team.org'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app import app,DB

CAPTCHA={'captcha_expected':'7','captcha_answer':'7'}

def payload(name,em,city='Pune',typ='CRO',sub='Clinical Trials',**org):
    return {'organization':{'type':typ,'name':name,'subtypes':sub,'address1':'Street 1','city':city,'state':'Maharashtra','country':'India','pin':'411001',**org},
            'person':{'first':'Test','last':'Person','salutation':'Dr.','gender':'Other','email':em,'phone':'9876543210','password':'Complex!123','confirm':'Complex!123'},
            'authorized':True,'accurate':True,'terms':True,**CAPTCHA}

def code_for(c,target,kind):
    msgs=c.get('/api/dev/outbox').json()['messages']
    return re.search(r'\d{6}',next(m['body'] for m in msgs if m['kind']==kind and m['target']==target)).group()

def verify(c,uid,em):
    r=None
    for channel,target in [('email',em),('phone','9876543210')]:
        r=c.post('/api/verify-registration',json={'registration_id':uid,'channel':channel,'code':code_for(c,target,channel)});assert r.status_code==200,r.text
    return r.json()

def register(c,body):
    r=c.post('/api/register',json=body);assert r.status_code==200,r.text
    return r.json()['registration_id'],verify(c,r.json()['registration_id'],body['person']['email'])

def login(c,em):
    r=c.post('/api/login',json={'email':em,'password':'Complex!123'});assert r.status_code==200,r.text
    return r.json()['csrf']

def sql(q,args=()):
    with sqlite3.connect(DB) as con:con.execute(q,args)

def org_id(name):
    with sqlite3.connect(DB) as con:return con.execute('SELECT id FROM organizations WHERE name=?',(name,)).fetchone()[0]

def test_exact_and_likely_duplicates_are_caught():
    with TestClient(app) as c:
        register(c,payload('Sahyadri Research Pvt. Ltd.','admin@sahyadri-research.in',website='https://www.sahyadri-research.in',acronym='SRL'))
        # Early check: exact name + city (city alias), similar name, same domain.
        r=c.get('/api/org-check',params={'name':'Sahyadri Research Pvt. Ltd.','city':'Poona'}).json()
        assert r['matches'][0]['level']=='exact'
        r=c.get('/api/org-check',params={'name':'Sahyadri Research Limited','city':'Pune'}).json()
        assert r['matches'][0]['level']=='likely' and 'Very similar name in the same city' in r['matches'][0]['reasons']
        r=c.get('/api/org-check',params={'name':'Totally Different','city':'Mumbai','website':'http://sahyadri-research.in/about'}).json()
        assert r['matches'][0]['reasons']==['Same website domain']
        assert c.get('/api/org-check',params={'name':'Gmail Org','city':'Mumbai','website':'https://gmail.com'}).json()['matches']==[]
        # Server blocks an exact duplicate, and needs confirmation for a likely one.
        r=c.post('/api/register',json=payload('sahyadri  research pvt ltd','x@other.org'));assert r.status_code==409 and r.json()['detail']['code']=='org_exists'
        r=c.post('/api/register',json=payload('Sahyadri Research Limited','y@other.org'));assert r.status_code==409 and r.json()['detail']['code']=='possible_duplicate'
        ids=[m['id'] for m in r.json()['detail']['matches']]
        r=c.post('/api/register',json={**payload('Sahyadri Research Limited','y@other.org'),'confirm_distinct':ids});assert r.status_code==200,r.text

def test_join_request_reaches_admin_and_is_cleared_by_invite():
    with TestClient(app) as c:
        register(c,payload('Deccan Trials','admin@deccantrials.in'))
        oid=org_id('Deccan Trials')
        r=c.post('/api/join-requests',json={'org_id':oid,'full_name':'New Colleague','email':'new@deccantrials.in'});assert r.status_code==200,r.text
        assert 'admin@deccantrials.in' not in r.text  # admin identity is not revealed
        csrf=login(c,'admin@deccantrials.in')
        joins=c.get(f'/api/dashboard/{oid}').json()['join_requests'];assert joins[0]['email']=='new@deccantrials.in'
        r=c.post('/api/invitations',headers={'x-csrf-token':csrf},json={'org_id':oid,'kind':'member','role':'Research Team','full_name':'New Colleague','email':'new@deccantrials.in'});assert r.status_code==200
        assert c.get(f'/api/dashboard/{oid}').json()['join_requests']==[]

def test_unverified_registration_is_released_after_48_hours():
    with TestClient(app) as c:
        r=c.post('/api/register',json=payload('Squatter Clinic Research','squat@example.net'));assert r.status_code==200
        assert c.post('/api/register',json=payload('Squatter Clinic Research','real@example.net')).status_code==409
        assert 'waiting for verification' in c.post('/api/register',json=payload('Another Name','squat@example.net')).json()['detail']
        sql('UPDATE users SET created=? WHERE email=?',('2000-01-01T00:00:00+00:00','squat@example.net'))
        r=c.post('/api/register',json=payload('Squatter Clinic Research','real@example.net'));assert r.status_code==200,r.text

def test_claim_approved_by_matching_email_domain():
    with TestClient(app) as c:
        register(c,payload('Konkan Medical Research','imposter@gmail.com',website='https://konkanmed.org'))
        oid=org_id('Konkan Medical Research')
        _,v=register(c,{**payload('Konkan Medical Research','director@konkanmed.org'),'claim_org_id':oid})
        assert v['claims'][0]['status']=='approved' and v['claims'][0]['method']=='email_domain'
        login(c,'director@konkanmed.org')
        assert c.get('/api/me').json()['memberships'][0]['role']=='Org Admin'
        r=c.post('/api/login',json={'email':'imposter@gmail.com','password':'Complex!123'});assert r.status_code==200
        assert c.get('/api/me').json()['memberships']==[]  # previous admin lost access

def test_claim_objection_goes_to_mtb_admin():
    with TestClient(app) as c:
        register(c,payload('MTB Operations','ops@mtb-team.org',city='Delhi'))
        register(c,payload('Malabar Trials','admin@malabartrials.in',city='Calicut',website='https://malabartrials.in'))
        oid=org_id('Malabar Trials')
        _,v=register(c,{**payload('Malabar Trials','someone@gmail.com',city='Kozhikode'),'claim_org_id':oid})
        claim=v['claims'][0];assert claim['status']=='objection_window'
        csrf=login(c,'admin@malabartrials.in')
        assert c.get(f'/api/dashboard/{oid}').json()['claims_on_org'][0]['claimant_email']=='someone@gmail.com'
        r=c.post(f'/api/claims/{claim["id"]}/object',headers={'x-csrf-token':csrf},json={'reason':'We do not know this person.'});assert r.status_code==200,r.text
        csrf=login(c,'ops@mtb-team.org')
        disputes=c.get('/api/me').json()['disputes'];assert disputes[0]['id']==claim['id']
        r=c.post(f'/api/admin/claims/{claim["id"]}/decision',headers={'x-csrf-token':csrf},json={'decision':'reject','note':'Not verified'});assert r.status_code==200
        login(c,'admin@malabartrials.in');assert c.get('/api/me').json()['memberships'][0]['org_id']==oid  # admin kept

def test_claim_approved_when_nobody_objects():
    with TestClient(app) as c:
        register(c,payload('Vidarbha Clinical','admin@vidarbha.in',city='Nagpur'))
        oid=org_id('Vidarbha Clinical')
        _,v=register(c,{**payload('Vidarbha Clinical','owner@gmail.com',city='Nagpur'),'claim_org_id':oid})
        sql('UPDATE claims SET deadline=1 WHERE id=?',(v['claims'][0]['id'],))
        login(c,'owner@gmail.com')
        assert c.get('/api/me').json()['memberships'][0]['org_id']==oid

def test_site_claims_provisional_hospital_added_by_smo():
    with TestClient(app) as c:
        register(c,payload('Coastal SMO','admin@coastalsmo.in',city='Chennai',typ='SMO',sub=None))
        csrf=login(c,'admin@coastalsmo.in');smo=org_id('Coastal SMO')
        site={'org_id':smo,'name':'Marina Heart Hospital','type':'Private','address1':'1 Beach Rd','city':'Chennai','state':'Tamil Nadu','country':'India','pin':'600001','website':'https://marinaheart.in','declaration':True}
        hid=c.post('/api/hospitals',headers={'x-csrf-token':csrf},json=site).json()['hospital_id']
        c.post('/api/logout',headers={'x-csrf-token':csrf})
        assert c.get('/api/org-check',params={'name':'Marina Heart Hospital','city':'Madras','type':'Site / Hospital / Institution'}).json()['hospital_record']
        _,v=register(c,payload('Marina Heart Hospital','research@marinaheart.in',city='Madras',typ='Site / Hospital / Institution',sub='Private'))
        assert v['claims'][0]['kind']=='hospital' and v['claims'][0]['status']=='approved'
        with sqlite3.connect(DB) as con:assert con.execute('SELECT org_id,provisional FROM hospitals WHERE id=?',(hid,)).fetchone()==(org_id('Marina Heart Hospital'),0)
