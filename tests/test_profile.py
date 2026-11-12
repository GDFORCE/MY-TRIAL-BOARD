"""Server tests for Module 02 – My Profile. The AI service is never called: its reader is replaced with a canned answer."""
import os,sys,re,io,json,tempfile,zipfile
from pathlib import Path
os.environ['MTB_DEV_MODE']='1'
os.environ['BREVO_API_KEY']='';os.environ['BREVO_SMTP_KEY']='';os.environ['BREVO_SMTP_LOGIN']=''
os.environ['MTB_PHONE_CODE_ON_SCREEN']='0'
os.environ['OPENAI_API_KEY']=''  # tests never call the real AI service, whatever .env holds
os.environ['MTB_SECRET']='a-long-test-key-for-local-tests-012345'
os.environ['MTB_ADMIN_EMAILS']=os.environ.get('MTB_ADMIN_EMAILS','boss@example.org')
_tmp=Path(tempfile.mkdtemp())
os.environ.setdefault('MTB_DB',str(_tmp/'mtb_test.db'))
os.environ.setdefault('MTB_UPLOADS',str(_tmp/'uploads'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from fastapi.testclient import TestClient
import app as core
import mtb_profile,mtb_cv_ai
from app import app

PW='Complex!123'
PNG=b'\x89PNG\r\n\x1a\n'+b'\x00'*40
PDF=b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF'
_phone=iter(range(9100000000,9100009999))

def code_for(client,target,kind):
    msgs=client.get('/api/dev/outbox').json()['messages']
    return re.search(r'\d{6}',next(m['body'] for m in msgs if m['kind']==kind and m['target']==target)).group()

def new_org(client,name,em,typ='CRO',first='Priya',last='Rao'):
    ph=str(next(_phone))
    r=client.post('/api/register',json={'organization':{'type':typ,'name':name,'subtypes':'Clinical Trials' if typ=='CRO' else 'Private','address1':'Street 1','city':'Hyderabad','state':'Telangana','country':'India','pin':'500034'},
        'person':{'first':first,'last':last,'salutation':'Dr.','gender':'Female','designation':'Director','email':em,'phone':ph,'password':PW,'confirm':PW},
        'authorized':True,'accurate':True,'terms':True,'captcha_expected':'7','captcha_answer':'7'})
    assert r.status_code==200,r.text
    for ch,t in (('email',em),('phone',ph)):
        assert client.post('/api/verify-registration',json={'registration_id':r.json()['registration_id'],'channel':ch,'code':code_for(client,t,ch)}).status_code==200
    return login(client,em)

def login(client,em):
    r=client.post('/api/login',json={'email':em,'password':PW});assert r.status_code==200,r.text
    return {'x-csrf-token':r.json()['csrf']}

def add_member(admin,h,em,first='Ravi',last='Kumar'):
    """Invite a new person to the admin's organization and finish their sign-up. Returns a signed-in client."""
    oid=admin.get('/api/me').json()['memberships'][0]['org_id']
    tok=admin.post('/api/invitations',headers=h,json={'org_id':oid,'kind':'member','role':'Research Team','full_name':f'{first} {last}','email':em}).json()['dev_invite_token']
    c=TestClient(app);ph=str(next(_phone))
    r=c.post(f'/api/invitation/{tok}/register',json={'person':{'first':first,'last':last,'salutation':'Mr.','gender':'Male','email':em,'phone':ph,'password':PW,'confirm':PW},'terms':True});assert r.status_code==200,r.text
    for ch,t in (('email',em),('phone',ph)):
        assert c.post('/api/verify-registration',json={'registration_id':r.json()['registration_id'],'channel':ch,'code':code_for(c,t,ch)}).status_code==200
    hh=login(c,em)
    assert c.post(f'/api/invitation/{tok}/respond',headers=hh,json={'decision':'accept'}).status_code==200
    return c,hh

def entry(client,h,section,data,**extra):
    return client.post(f'/api/profile/entries/{section}',headers=h,json={'data':data,**extra})

def test_profile_is_created_from_registration_and_saves_progressively():
    with TestClient(app) as c:
        h=new_org(c,'Alder Research','p1@example.org')
        assert c.get('/api/profile/schema').json()['steps'][0]['key']=='basic'
        p=c.get('/api/profile').json()
        # BRD 3.1: registration details are reused; the organization joined at registration shows under Place of Work.
        assert p['user']['name']=='Priya Rao' and p['user']['email']=='p1@example.org' and p['user']['designation']=='Director'
        assert p['roles']==[{'org':'Alder Research','type':'CRO','role':'Admin','member_role':'Org Admin'}]
        pow_=p['entries']['place_of_work']
        assert len(pow_)==1 and pow_[0]['locked'] and pow_[0]['data']['org_name']=='Alder Research' and pow_[0]['data']['status']=='Current'
        assert p['completion']['percent']<50 and 'Education Details' in p['completion']['missing']
        assert c.put('/api/profile/basic',json={'department':'Cardiology'}).status_code==403  # CSRF
        r=c.put('/api/profile/basic',headers=h,json={'department':'Cardiology','languages':['English','Konkani'],'research_roles':['PI','Others: Sub-investigator'],'city':'Hyderabad','country':'India','designation':'Professor','alt_phone':'040 2345 6789'})
        assert r.status_code==200,r.text
        p=r.json();assert p['basic']['languages']==['English','Konkani'] and p['user']['designation']=='Professor' and p['completion']['steps']['basic']
        assert c.put('/api/profile/basic',headers=h,json={'research_roles':['Chief Wizard']}).status_code==422
        assert c.put('/api/profile/basic',headers=h,json={'alt_phone':'12'}).status_code==422
        assert c.put('/api/profile/basic',headers=h,json={'salutation':'','gender':'Robot'}).status_code==422
        assert c.put('/api/profile/about',headers=h,json={'about':'Cardiologist with twelve years of clinical research experience across phase II and III trials.'}).json()['completion']['steps']['about']
        r=c.put('/api/profile/tags/trial_expertise',headers=h,json={'values':['Paediatric','Others: Oncology vaccines']});assert r.json()['trial_expertise']==['Paediatric','Others: Oncology vaccines']
        assert c.put('/api/profile/tags/tech_expertise',headers=h,json={'values':['Time travel']}).status_code==422
        # "Nothing to add here" counts a section as done; adding an entry later clears it.
        p=c.put('/api/profile/settings',headers=h,json={'na':{'award':True,'basic':True}}).json();assert p['na']==['award'] and p['completion']['steps']['award']
        assert entry(c,h,'award',{'name':'Best Investigator','year':'2022'}).json()['na']==[]
        # BRD 23.3: every change is traceable with previous and new values.
        ev=c.get('/api/profile/history').json()['events']
        ch=next(e for e in ev if e['action']=='profile_updated' and e['details']['section']=='basic')['details']['changes']
        assert {'field':'Designation','old':'Director','new':'Professor'} in ch

def test_entries_validation_duplicates_expiry_and_delete():
    with TestClient(app) as c:
        h=new_org(c,'Birch Research','p2@example.org')
        assert entry(c,h,'education',{'degree_name':'MD'}).status_code==422                      # required fields
        assert entry(c,h,'education',{'degree_type':'Wizardry','degree_name':'MD','institution':'AIIMS'}).status_code==422
        r=entry(c,h,'education',{'degree_type':'Others: Diploma','degree_name':'MD General Medicine','institution':'AIIMS, New Delhi','completed_year':'2014'});assert r.status_code==200,r.text
        eid=r.json()['entries']['education'][0]['id']
        r=entry(c,h,'education',{'degree_type':'Master','degree_name':'md general medicine','institution':'AIIMS New Delhi'})   # BRD 5.3.4 / 23.2
        assert r.status_code==409 and r.json()['detail']['code']=='duplicate'
        assert entry(c,h,'education',{'degree_type':'Master','degree_name':'md general medicine','institution':'AIIMS New Delhi'},allow_duplicate=True).status_code==200
        r=c.put(f'/api/profile/entries/education/{eid}',headers=h,json={'data':{'degree_type':'Master','degree_name':'MD Medicine','institution':'AIIMS, New Delhi','completed_year':'2015'}})
        assert r.status_code==200 and any(e['data']['degree_name']=='MD Medicine' for e in r.json()['entries']['education'])
        assert entry(c,h,'education',{'degree_type':'PhD','degree_name':'PhD','institution':'IISc','completed_year':'20x5'}).status_code==422
        # Licences: dates in any common form, expired ones are kept and flagged (BRD 8.3).
        assert entry(c,h,'license',{'license_type':'Medical Council Registration','issue_date':'2020-01-01','expiry_date':'2019-01-01'}).status_code==422
        r=entry(c,h,'license',{'license_type':'Medical Council Registration','number':'TS/1','issue_date':'01/06/2015','expiry_date':'May 2020'});assert r.status_code==200,r.text
        lic=r.json()['entries']['license'][0];assert lic['data']['issue_date']=='2015-06-01' and lic['data']['expiry_date']=='2020-05' and lic['expired']
        ls=entry(c,h,'license',{'license_type':'State licence','number':'X9','expiry_date':'2031'}).json()['entries']['license']
        assert [l['expired'] for l in ls if l['data']['number']=='X9']==[False] and len(ls)==2
        # Work: a current job has no end date; a web link must be http(s).
        w=entry(c,h,'work',{'org_name':'City Hospital','job_title':'Consultant','start':'2018-04','end':'2020-01','current':True}).json()['entries']['work'][0]['data']
        assert w['current'] is True and 'end' not in w
        assert entry(c,h,'publication',{'name':'A study','weblink':'javascript:alert(1)'}).status_code==422
        assert entry(c,h,'publication',{'name':'A study','weblink':'doi.org/10.1/x'}).json()['entries']['publication'][0]['data']['weblink']=='https://doi.org/10.1/x'
        # The organization from the MTB membership cannot be renamed or removed; other details can be added to it.
        pid=c.get('/api/profile').json()['entries']['place_of_work'][0]['id']
        r=c.put(f'/api/profile/entries/place_of_work/{pid}',headers=h,json={'data':{'org_type':'Sponsor','org_name':'Hacked','status':'Previous','working_hours':'9 to 5','research_roles':['CRA']}})
        d=r.json()['entries']['place_of_work'][0]['data'];assert d['org_name']=='Birch Research' and d['org_type']=='CRO' and d['status']=='Current' and d['working_hours']=='9 to 5'
        assert c.delete(f'/api/profile/entries/place_of_work/{pid}',headers=h).status_code==409
        # A place of work typed by hand never creates a membership (BRD 9.1.4).
        assert entry(c,h,'place_of_work',{'org_type':'Site','org_name':'Some Other Hospital','status':'Previous'}).status_code==200
        assert len(c.get('/api/me').json()['memberships'])==1
        assert c.delete(f'/api/profile/entries/education/{eid}',headers=h).status_code==200
        assert c.delete(f'/api/profile/entries/education/{eid}',headers=h).status_code==404
        assert c.post('/api/profile/entries/nonsense',headers=h,json={'data':{}}).status_code==404

def test_csv_import_reports_invalid_and_duplicate_rows():
    with TestClient(app) as c:
        h=new_org(c,'Cedar Research','p3@example.org')
        t=c.get('/api/profile/entries/education/csv-template');assert t.status_code==200 and 'Degree name' in t.text and 'MD General Medicine' in t.text
        assert c.get('/api/profile/entries/training/csv-template').status_code==404
        csv_text='Type of degree,Degree name,Institution name,Completed year\nBachelor,MBBS,Osmania Medical College,2010\nMaster,,AIIMS,2014\nBachelor,mbbs,"Osmania Medical College",2010\nSomething,BDS,Dental College,2012\n,,,\n'
        r=c.post('/api/profile/entries/education/csv',headers=h,json={'csv':csv_text});assert r.status_code==200,r.text
        d=r.json();assert d['added']==1 and [x['row'] for x in d['invalid']]==[3,5] and [x['row'] for x in d['duplicates']]==[4]
        assert 'Degree name is required' in d['invalid'][0]['errors'] and len(d['profile']['entries']['education'])==1
        assert c.post('/api/profile/entries/education/csv',headers=h,json={'csv':'foo,bar\n1,2\n'}).status_code==422
        r=c.post('/api/profile/entries/work/csv',headers=h,json={'csv':'Organization name,Job title,Started month / year,Currently working here\nCity Hospital,Consultant,04/2018,Yes\n'})
        assert r.json()['added']==1 and r.json()['profile']['entries']['work'][0]['data']=={'org_name':'City Hospital','job_title':'Consultant','start':'2018-04','current':True}

def test_files_are_type_checked_and_private():
    with TestClient(app) as c, TestClient(app) as other:
        h=new_org(c,'Dahlia Research','p4@example.org');new_org(other,'Elm Research','p4b@example.org')
        up=lambda kind,name,data:c.post('/api/profile/files',headers=h,data={'kind':kind},files={'file':(name,data,'application/octet-stream')})
        assert up('photo','me.png',PDF).status_code==422 and up('document','cert.pdf',b'MZ not a pdf').status_code==422
        assert up('cv','cv.pdf',PDF).status_code==422    # CVs go through /api/profile/cv
        r=up('photo','me.png',PNG);assert r.status_code==200,r.text
        photo=r.json()['file']['id'];assert c.get('/api/profile').json()['photo']['id']==photo
        assert c.get(f'/api/profile/files/{photo}').content==PNG and other.get(f'/api/profile/files/{photo}').status_code==404
        cert=up('document','degree.pdf',PDF).json()['file']['id']
        r=entry(c,h,'education',{'degree_type':'Bachelor','degree_name':'MBBS','institution':'OMC'},file_id=cert);assert r.json()['entries']['education'][0]['file']['name']=='degree.pdf'
        eid=r.json()['entries']['education'][0]['id']
        assert entry(c,h,'award',{'name':'Prize'},file_id=cert).status_code==422        # one file, one entry
        assert entry(c,h,'attachment',{'name':'Passport copy'}).status_code==422          # attachment needs its file
        att=up('attachment','note.pdf',PDF).json()['file']['id'];assert entry(c,h,'attachment',{'name':'Reference letter'},file_id=att).status_code==200
        assert c.delete(f'/api/profile/files/{cert}',headers=h).status_code==409
        assert c.delete(f'/api/profile/entries/education/{eid}',headers=h).status_code==200 and c.get(f'/api/profile/files/{cert}').status_code==404
        assert c.delete(f'/api/profile/files/{photo}',headers=h).json()['photo'] is None

def test_name_and_verified_contacts_change_only_with_proof():
    with TestClient(app) as c, TestClient(app) as other:
        h=new_org(c,'Fir Research','p5@example.org');new_org(other,'Ginkgo Research','p5b@example.org')
        assert c.post('/api/profile/name',headers=h,json={'first':'Priya','last':'Sharma','password':'wrong'}).status_code==403
        assert c.post('/api/profile/name',headers=h,json={'first':'Priya','middle':'K','last':'Sharma','password':PW}).json()['user']['name']=='Priya K Sharma'
        req=lambda **b:c.post('/api/profile/contact/request',headers=h,json={'password':PW,**b})
        assert req(channel='email',value='p5b@example.org').status_code==409             # someone else's address
        assert req(channel='email',value='p5@example.org').status_code==409
        assert c.post('/api/profile/contact/request',headers=h,json={'channel':'email','value':'new5@example.org','password':'nope'}).status_code==403
        assert req(channel='email',value='new5@example.org').status_code==200
        assert c.get('/api/profile').json()['user']['email']=='p5@example.org' and c.get('/api/profile').json()['pending_contact']=={'email':'new5@example.org'}
        assert c.post('/api/profile/contact/verify',headers=h,json={'channel':'email','code':'000000'}).status_code==400
        r=c.post('/api/profile/contact/verify',headers=h,json={'channel':'email','code':code_for(c,'new5@example.org','email')});assert r.status_code==200,r.text
        assert r.json()['user']['email']=='new5@example.org' and r.json()['pending_contact']=={}
        assert any('was changed to new5@example.org' in m['body'] for m in c.get('/api/dev/outbox').json()['messages'] if m['target']=='p5@example.org')
        with TestClient(app) as again: login(again,'new5@example.org')                    # the new address signs in
        assert req(channel='alt_email',value='alt5@example.org').status_code==200
        u=c.post('/api/profile/contact/verify',headers=h,json={'channel':'alt_email','code':code_for(c,'alt5@example.org','alt_email')}).json()['user']
        assert u['alt_email']=='alt5@example.org' and u['alt_email_verified']
        assert req(channel='alt_email',value='').json()['removed'] and c.get('/api/profile').json()['user']['alt_email']==''
        assert req(channel='phone',value='9988776655').status_code==200
        assert c.post('/api/profile/contact/verify',headers=h,json={'channel':'phone','code':code_for(c,'9988776655','phone')}).json()['user']['phone']=='9988776655'
        # Five wrong passwords pause re-authentication.
        for _ in range(3):assert c.post('/api/profile/name',headers=h,json={'first':'A','last':'B','password':'bad'}).status_code==403
        assert c.post('/api/profile/name',headers=h,json={'first':'A','last':'B','password':PW}).status_code==429

CV_ANSWER={'is_cv':True,
    'basic':{'first_name':'Priyanka','middle_name':None,'last_name':'Rao','email':'cv6@gmail.com','phone':'+91 90000 11111','designation':'Senior Consultant','department':'Cardiology',
             'address_line1':'12 Lake Road','address_line2':None,'city':'Hyderabad','state':'Telangana','country':'India','postal_code':'500034','salutation':'Dr.','gender':None,
             'languages':['English','Telugu'],'research_roles':['PI','Space Pilot']},
    'about':{'text':'Cardiologist and principal investigator with 12 years of experience.','drafted':False},
    'trial_expertise':['Paediatric','Made Up'],'tech_expertise':['EDC'],
    'education':[{'degree_type':'Bachelor','degree_name':'MBBS','institution':'Osmania Medical College','specialization':None,'completed_year':'2010'},
                 {'degree_type':None,'degree_name':'MD Medicine','institution':'AIIMS','specialization':'Medicine','completed_year':'Passed in 2014'},
                 {'degree_type':'Master','degree_name':'MD Medicine','institution':'AIIMS','specialization':None,'completed_year':'2014'},
                 {'degree_type':'Master','degree_name':None,'institution':'Nowhere','specialization':None,'completed_year':None}],
    'license':[{'license_type':'Medical Council Registration','issuer':'TSMC','number':'TS/77','region':'Telangana','issue_date':'2015-06','expiry_date':'not a date'}],
    'place_of_work':[{'org_type':'Site','org_name':'City Hospital','department':'Cardiology','designation':'Senior Consultant','research_roles':['PI'],'status':None,'date_of_joining':'2018'}],
    'training':[{'title':'GCP','date':'2023-02-10','issued_by':'CITI','status':'Completed'},{'title':'Advanced Cardiac Imaging Workshop','date':None,'issued_by':None,'status':None}],
    'certification':[],'publication':[{'name':'<img src=x onerror=alert(1)> Statins in ACS','therapeutic_area':'Cardiology','source':'IHJ','date_published':'2021-08','weblink':'javascript:alert(1)'}],
    'audit':[{'regulatory_body':'CDSCO','scope':None,'organization':'City Hospital','date':'2022-11-14','outcome':'No critical findings'}],
    'work':[{'org_name':'City Hospital','org_address':'Hyderabad','job_title':'Senior Consultant','start':'2018-04','end':None,'current':True,'description':'Leads trials.'}],
    'membership':[{'association':'Cardiological Society of India','type':'Life member','number':None,'start_date':None,'valid_until':None}],
    'award':[]}

@pytest.fixture
def fake_ai(monkeypatch):
    calls=[]
    def read(data,filename,ext,instructions,schema,request_text):
        calls.append((filename,ext,len(data)));return json.loads(json.dumps(read.answer))
    read.answer=CV_ANSWER
    monkeypatch.setenv('OPENAI_API_KEY','sk-test');monkeypatch.setattr(mtb_cv_ai,'read_document',read)
    read.calls=calls;return read

def upload_cv(c,h,name='cv.pdf',data=PDF):
    return c.post('/api/profile/cv',headers=h,files={'file':(name,data,'application/pdf')})

def test_cv_autofill_needs_review_and_never_overwrites_verified_details(fake_ai,monkeypatch):
    with TestClient(app) as c:
        h=new_org(c,'Hazel Research','p6@example.org')
        entry(c,h,'education',{'degree_type':'Bachelor','degree_name':'MBBS','institution':'Osmania Medical College'})
        assert upload_cv(c,h,'cv.png',PNG).status_code==422 and upload_cv(c,h,'cv.pdf',b'PK\x03\x04 zip but not word').status_code==422
        r=upload_cv(c,h);assert r.status_code==200,r.text
        iid=r.json()['import_id'];assert fake_ai.calls==[('cv.pdf','pdf',len(PDF))]
        d=c.get(f'/api/profile/cv/{iid}').json();assert d['status']=='ready'
        pv=d['preview'];rows={x['key']:x for x in pv['basic']}
        # BRD 4.3.2: the registered name and verified email/phone are never replaced by a CV.
        assert rows['name']['kind']=='locked' and rows['alt_email']['proposed']=='cv6@gmail.com' and rows['alt_phone']['proposed']=='+91 90000 11111'
        assert rows['designation']=={'key':'designation','label':'Designation','current':'Director','proposed':'Senior Consultant','kind':'conflict','note':''}
        assert rows['research_roles']['proposed']==['PI','Others: Space Pilot'] and 'salutation' not in rows and 'gender' not in rows
        assert pv['trial_expertise']==['Paediatric'] and pv['tech_expertise']==['EDC'] and pv['about']['proposed'].startswith('Cardiologist')
        edu=pv['sections']['education'];assert [e['data']['degree_name'] for e in edu]==['MBBS','MD Medicine']   # same entry twice and the empty one are dropped
        assert edu[0]['duplicate'] and not edu[1]['duplicate'] and edu[1]['missing']==['Type of degree'] and edu[1]['data']['completed_year']=='2014'
        assert 'expiry_date' not in pv['sections']['license'][0]['data'] and pv['sections']['training'][1]['data']['title']=='Others: Advanced Cardiac Imaging Workshop'
        assert 'weblink' not in pv['sections']['publication'][0]['data'] and pv['sections']['audit'][0]['data']['scope']=='My organization was audited'
        assert pv['sections']['place_of_work'][0]['data']['status']=='Current' and pv['sections']['membership'][0]['data']['association']=='Others: Cardiological Society of India'
        assert any('CV preview is ready' in (m.get('subject') or '') for m in c.get('/api/dev/outbox').json()['messages'] if m['target']=='p6@example.org')
        # Nothing reached the profile yet.
        p=c.get('/api/profile').json();assert len(p['entries']['education'])==1 and p['about']=='' and p['cv']['status']=='ready'
        # An item that still misses a required detail is refused until it is completed.
        bad=c.post(f'/api/profile/cv/{iid}/apply',headers=h,json={'entries':{'education':[edu[1]]}});assert bad.status_code==422 and 'Type of degree' in bad.json()['detail']
        body={'basic':{'designation':'Senior Consultant','research_roles':['PI'],'alt_email':'cv6@gmail.com','city':'Hyderabad','first':'Hacker','email':'x@y.z'},
              'about':pv['about']['proposed'],'trial_expertise':['Paediatric'],'tech_expertise':[],
              'entries':{'education':[edu[0],{'data':{**edu[1]['data'],'degree_type':'Master'}}],'training':pv['sections']['training'],'publication':pv['sections']['publication']}}
        r=c.post(f'/api/profile/cv/{iid}/apply',headers=h,json=body);assert r.status_code==200,r.text
        assert r.json()['saved']=={'basic':6,'entries':4,'skipped_duplicates':1}
        p=r.json()['profile'];u=p['user']
        assert u['name']=='Priya Rao' and u['email']=='p6@example.org' and u['alt_email']=='cv6@gmail.com' and not u['alt_email_verified'] and u['designation']=='Senior Consultant'
        assert len(p['entries']['education'])==2 and {e['source'] for e in p['entries']['training']}=={'cv'} and p['basic']['research_roles']==['PI'] and p['cv']['status']=='applied'
        assert c.post(f'/api/profile/cv/{iid}/apply',headers=h,json=body).status_code==409
        # BRD 5.3.3: a newer CV replaces the stored file but removes nothing that was confirmed.
        old_file=c.get('/api/profile').json()['cv']
        i2=upload_cv(c,h,'cv-2026.pdf').json()['import_id']
        assert c.post(f'/api/profile/cv/{i2}/discard',headers=h).status_code==200
        p=c.get('/api/profile').json();assert len(p['entries']['education'])==2 and len(p['entries']['training'])==2 and p['cv']['file_name']=='cv-2026.pdf'
        # Not a CV, and AI failures, end as a clear message.
        fake_ai.answer={**CV_ANSWER,'is_cv':False}
        assert 'does not look like a CV' in c.get(f"/api/profile/cv/{upload_cv(c,h).json()['import_id']}").json()['error']
        def boom(*a,**k):raise mtb_cv_ai.AIError('The AI service is busy right now. Please try again in a minute.')
        monkeypatch.setattr(mtb_cv_ai,'read_document',boom)
        d=c.get(f"/api/profile/cv/{upload_cv(c,h).json()['import_id']}").json();assert d['status']=='failed' and 'busy' in d['error']
        monkeypatch.delenv('OPENAI_API_KEY');assert upload_cv(c,h).status_code==503

def test_openai_request_shape_and_docx_fallback(monkeypatch):
    """The call to the AI service: the file itself is sent, the answer must match the schema, and nothing is stored there."""
    sent=[]
    class Resp:
        def __init__(s,code,body):s.status_code,s._b,s.text=code,body,json.dumps(body)
        def json(s):return s._b
    def post(url,headers=None,json=None,timeout=None):
        sent.append((url,headers,json))
        if json['input'][0]['content'][0]['type']=='input_file' and 'wordprocessingml' in json['input'][0]['content'][0]['file_data']:return Resp(400,{'error':{'message':'unsupported file','code':'invalid_file'}})
        return Resp(200,{'status':'completed','output':[{'type':'reasoning'},{'type':'message','content':[{'type':'output_text','text':'{"is_cv": true}'}]}]})
    monkeypatch.setattr(mtb_cv_ai.httpx,'post',post);monkeypatch.setenv('OPENAI_API_KEY','sk-test');monkeypatch.setenv('MTB_OPENAI_MODEL','test-model');monkeypatch.delenv('OPENAI_BASE_URL',raising=False)
    schema=mtb_profile.cv_schema()
    assert mtb_cv_ai.read_document(PDF,'cv.pdf','pdf','rules',schema,'go')=={'is_cv':True}
    url,headers,body=sent[0]
    assert url=='https://api.openai.com/v1/responses' and headers=={'Authorization':'Bearer sk-test'} and body['model']=='test-model' and body['store'] is False
    assert body['text']['format']['type']=='json_schema' and body['text']['format']['strict'] is True and body['input'][0]['content'][0]['file_data'].startswith('data:application/pdf;base64,')
    def strict(node):   # every object closed and every property required, as strict structured output demands
        if isinstance(node,dict):
            if node.get('type')=='object':assert node['additionalProperties'] is False and set(node['required'])==set(node['properties'])
            for v in node.values():strict(v)
        elif isinstance(node,list):
            for v in node:strict(v)
    strict(schema);assert set(mtb_profile.SECTIONS)-{'attachment'}<=set(schema['properties'])
    # A Word file the service refuses is read here and sent as text, including text boxes and headers.
    doc=io.BytesIO()
    with zipfile.ZipFile(doc,'w') as z:
        z.writestr('word/header1.xml','<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>priya@example.org</w:t></w:r></w:p></w:hdr>')
        z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Dr. Priya Rao</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>MBBS</w:t><w:tab/><w:t>2010</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:p><w:r><w:t>Consultant Cardiologist with long experience in trials</w:t></w:r></w:p></w:body></w:document>')
    assert mtb_profile.sniff(doc.getvalue())=='docx'
    assert mtb_cv_ai.read_document(doc.getvalue(),'cv.docx','docx','rules',schema,'go')=={'is_cv':True}
    text_part=sent[-1][2]['input'][0]['content'][0]
    assert text_part['type']=='input_text' and text_part['text'].index('priya@example.org')<text_part['text'].index('Dr. Priya Rao') and 'MBBS\t2010' in text_part['text']
    monkeypatch.setattr(mtb_cv_ai.httpx,'post',lambda *a,**k:Resp(401,{'error':{'message':'bad key sk-secret','code':'invalid_api_key'}}))
    with pytest.raises(mtb_cv_ai.AIError) as e:mtb_cv_ai.rewrite_about('x'*50)
    assert 'sk-' not in str(e.value) and 'administrator' in str(e.value)

def test_declaration_is_an_e_signature_and_changes_ask_for_it_again():
    with TestClient(app) as c:
        h=new_org(c,'Iris Research','p7@example.org')
        sign=lambda **b:c.post('/api/profile/declaration',headers=h,json={'agree':True,'full_name':'Priya Rao','password':PW,**b})
        assert sign(agree=False).status_code==422 and sign(full_name='Someone Else').status_code==422 and sign(password='wrong').status_code==403
        r=sign(full_name='  priya   RAO ');assert r.status_code==200,r.text
        d=r.json()['declaration'];assert d['name']=='Priya Rao' and d['signed_at'] and d['version']=='1.0' and not d['changed_since'] and r.json()['completion']['steps']['declaration']
        with core.db() as db:
            a=db.execute('SELECT details FROM audit WHERE action="profile_declared" ORDER BY id DESC LIMIT 1').fetchone()
            assert json.loads(a['details'])['method']=='typed name + password' and len(json.loads(a['details'])['profile_digest'])==64
            assert db.execute('SELECT declared_seal FROM profiles WHERE declared_name="Priya Rao" ORDER BY declared_at DESC').fetchone()['declared_seal']
            assert core.verify_audit_chain(db)['ok']
        p=entry(c,h,'award',{'name':'Prize','year':'2020'}).json()       # BRD 21.2: later edits are allowed and traceable
        assert p['declaration']['changed_since'] and not p['completion']['steps']['declaration'] and c.get('/api/profile/summary').json()['changed_since']
        assert not sign().json()['declaration']['changed_since']

def test_teammates_see_only_the_professional_part():
    with TestClient(app) as a, TestClient(app) as stranger:
        h=new_org(a,'Juniper Research','p8@example.org');new_org(stranger,'Kapok Research','p8b@example.org')
        oid=a.get('/api/me').json()['memberships'][0]['org_id'];me=a.get('/api/me').json()['user']['id']
        a.put('/api/profile/about',headers=h,json={'about':'Investigator with long experience in cardiology and oncology trials.'})
        a.put('/api/profile/basic',headers=h,json={'address1':'12 Secret Lane','city':'Hyderabad','research_roles':['PI']})
        entry(a,h,'license',{'license_type':'Medical Council Registration','number':'TS/SECRET/1','issuer':'TSMC'})
        cert=a.post('/api/profile/files',headers=h,data={'kind':'attachment'},files={'file':('passport.pdf',PDF,'application/pdf')}).json()['file']['id']
        entry(a,h,'attachment',{'name':'Passport copy'},file_id=cert)
        photo=a.post('/api/profile/files',headers=h,data={'kind':'photo'},files={'file':('me.png',PNG,'image/png')}).json()['file']['id']
        mate,_=add_member(a,h,'p8.mate@example.org')
        team=mate.get(f'/api/profile/team/{oid}').json()['people'];assert [p['name'] for p in team]==['Dr. Priya Rao','Mr. Ravi Kumar'] and team[0]['has_photo'] and team[1]['me']
        r=mate.get(f'/api/profile/people/{me}');assert r.status_code==200,r.text
        raw=r.text;v=r.json()
        assert v['name']=='Dr. Priya Rao' and v['research_roles']==['PI'] and {b['key'] for b in v['blocks']}=={'about','license','place_of_work'}
        for secret in ('p8@example.org','Secret Lane','TS/SECRET/1','passport','Passport',cert):assert secret not in raw     # BRD 23.1.3
        assert mate.get(f'/api/profile/people/{me}/photo').content==PNG and mate.get(f'/api/profile/files/{photo}').status_code==404
        a.put('/api/profile/settings',headers=h,json={'visibility':{'license':False,'basic':False}})
        assert {b['key'] for b in mate.get(f'/api/profile/people/{me}').json()['blocks']}=={'about','place_of_work'}
        # People outside the organization get nothing, and admin rights elsewhere do not help (BRD 23.1.2).
        assert stranger.get(f'/api/profile/people/{me}').status_code==404 and stranger.get(f'/api/profile/people/{me}/photo').status_code==404
        assert stranger.get(f'/api/profile/team/{oid}').status_code==403
        with core.db() as db:assert db.execute('SELECT COUNT(*) n FROM audit WHERE action="profile_viewed" AND subject_id=?',(me,)).fetchone()['n']==2

def test_cv_export_pdf_and_word_without_restricted_data():
    with TestClient(app) as c:
        h=new_org(c,'Larch Research','p9@example.org')
        c.put('/api/profile/about',headers=h,json={'about':'Investigator with long experience in cardiology trials.\n\nSpeaker at national meetings & reviewer for <journals>.'})
        c.put('/api/profile/basic',headers=h,json={'address1':'12 Home Street','city':'Hyderabad','country':'India','research_roles':['PI'],'languages':['English']})
        entry(c,h,'work',{'org_name':'City Hospital','job_title':'Consultant Cardiologist','start':'2018-04','current':True,'description':'Leads the cardiology research unit.'})
        entry(c,h,'work',{'org_name':'Old Clinic','job_title':'Registrar','start':'2012-01','end':'2018-03'})
        entry(c,h,'license',{'license_type':'Medical Council Registration','number':'TS/123','expiry_date':'2030-05-31'})
        entry(c,h,'publication',{'name':'Statins in ACS','source':'IHJ','date_published':'2021-08','weblink':'https://doi.org/10.1/x'})
        c.put('/api/profile/tags/trial_expertise',headers=h,json={'values':['Paediatric','Others: Vaccines']})
        m=c.post('/api/profile/export',headers=h,json={'format':'preview','template':'professional'}).json()
        assert m['name']=='Dr. Priya Rao' and m['contact']==['p9@example.org',m['contact'][1],'Hyderabad, India'] and [b['key'] for b in m['blocks']]==['about','work','license','trial_expertise','publication']
        work=m['blocks'][1]['items'];assert [w['title'] for w in work]==['Consultant Cardiologist','Registrar'] and work[0]['meta']=='Apr 2018 – Present' and work[1]['meta']=='Jan 2012 – Mar 2018'
        assert m['blocks'][3]['tags']==['Paediatric','Vaccines'] and 'TS/123' in m['blocks'][2]['items'][0]['sub']
        m=c.post('/api/profile/export',headers=h,json={'format':'preview','template':'clinical','sections':['work','place_of_work'],'contact':{'email':False,'phone':False,'address':True}}).json()
        assert m['signature'] and [b['key'] for b in m['blocks']]==['place_of_work','work'] and m['contact']==['12 Home Street, Hyderabad, India']
        for template in ('professional','clinical'):
            r=c.post('/api/profile/export',headers=h,json={'format':'pdf','template':template});assert r.status_code==200,r.text
            assert r.content[:5]==b'%PDF-' and 'attachment; filename="CV_Priya_Rao_' in r.headers['content-disposition']
            from pypdf import PdfReader
            txt=' '.join(pg.extract_text() for pg in PdfReader(io.BytesIO(r.content)).pages)
            assert 'Priya Rao' in txt and 'Consultant Cardiologist' in txt and 'reviewer for <journals>' in txt and ('Signature' in txt)==(template=='clinical')
            r=c.post('/api/profile/export',headers=h,json={'format':'docx','template':template});assert r.status_code==200 and mtb_profile.sniff(r.content)=='docx'
            from docx import Document
            words='\n'.join(p.text for p in Document(io.BytesIO(r.content)).paragraphs);assert 'Dr. Priya Rao' in words and 'CITY HOSPITAL' not in words and 'Statins in ACS' in words
        assert c.post('/api/profile/export',headers=h,json={'format':'exe'}).status_code==422
        with core.db() as db:   # BRD 23.3: the export is recorded without its contents
            d=json.loads(db.execute('SELECT details FROM audit WHERE action="profile_cv_exported" ORDER BY id DESC LIMIT 1').fetchone()['details'])
            assert d['format']=='docx' and 'Priya' not in json.dumps(d)

def test_deleting_an_account_erases_its_profile(fake_ai):
    with TestClient(app) as c, TestClient(app) as boss:
        h=new_org(c,'Maple Research','p10@example.org')
        mate,mh=add_member(c,h,'p10.mate@example.org')
        mate.put('/api/profile/about',headers=mh,json={'about':'Coordinator with five years of experience in oncology trials.'})
        fid=mate.post('/api/profile/files',headers=mh,data={'kind':'photo'},files={'file':('me.png',PNG,'image/png')}).json()['file']['id']
        upload_cv(mate,mh);uid=mate.get('/api/me').json()['user']['id']
        assert (mtb_profile.files_dir()/f'{fid}.png').is_file()
        import subprocess
        with core.db() as db:
            db.execute('INSERT INTO users(first,last,email,password_hash,status,email_verified,phone_verified,created) VALUES(?,?,?,?,?,?,?,?)',('Boss','Admin','boss.p10@example.org',core.hasher.hash(PW),'active',1,1,core.now()))
        os.environ['MTB_ADMIN_EMAILS']=os.environ['MTB_ADMIN_EMAILS']+',boss.p10@example.org'
        bh=login(boss,'boss.p10@example.org')
        assert boss.post(f'/api/admin/users/{uid}/action',headers=bh,json={'action':'delete'}).status_code==200
        with core.db() as db:
            for t in ('profiles','profile_entries','profile_files','cv_imports'):assert db.execute(f'SELECT COUNT(*) n FROM {t} WHERE user_id=?',(uid,)).fetchone()['n']==0
        assert not (mtb_profile.files_dir()/f'{fid}.png').exists()
