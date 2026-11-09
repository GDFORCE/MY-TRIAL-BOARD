import os,sys,re,json,tempfile,base64
from pathlib import Path
os.environ['MTB_DEV_MODE']='1'
os.environ['BREVO_API_KEY']=''  # tests never send real email
os.environ['BREVO_SMTP_KEY']='';os.environ['BREVO_SMTP_LOGIN']=''
os.environ['MTB_PHONE_CODE_ON_SCREEN']='0'
os.environ['MTB_SECRET']='a-long-test-key-for-local-tests-012345'
_tmp=Path(tempfile.mkdtemp())
os.environ['MTB_DB']=str(_tmp/'mtb_test.db')
os.environ['MTB_UPLOADS']=str(_tmp/'uploads')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app import app

CATEGORY={'Sponsor':['Pharmaceutical','Others: Nutraceutical'],'CRO':'Clinical Trials','SMO':None,'Site / Hospital / Institution':'Private'}
CAPTCHA={'captcha_expected':'7','captcha_answer':'7'}

def payload(typ,name,em,**person):
    return {'organization':{'type':typ,'name':name,'subtypes':CATEGORY[typ],'address1':'Street 1','city':'Hyderabad','state':'Telangana','country':'India','pin':'500034'},
            'person':{'first':'Test','last':'Admin','salutation':'Dr.','gender':'Other','email':em,'phone':'9876543210','password':'Complex!123','confirm':'Complex!123',**person},
            'authorized':True,'accurate':True,'terms':True,**CAPTCHA}

def code_for(client,target,kind):
    msgs=client.get('/api/dev/outbox').json()['messages']
    return re.search(r'\d{6}',next(m['body'] for m in msgs if m['kind']==kind and m['target']==target)).group()

def register(client,typ,name,em):
    r=client.post('/api/register',json=payload(typ,name,em));assert r.status_code==200,r.text
    verify(client,r.json()['registration_id'],em);return r.json()['registration_id']

def verify(client,uid,em):
    for channel,target in [('email',em),('phone','9876543210')]:
        r=client.post('/api/verify-registration',json={'registration_id':uid,'channel':channel,'code':code_for(client,target,channel)})
        assert r.status_code==200,r.text

def login(client,em,**extra):
    r=client.post('/api/login',json={'email':em,'password':'Complex!123',**extra});assert r.status_code==200,r.text
    return r.json()['csrf']

def test_register_smo_hospital_pi_invite_and_new_user():
    with TestClient(app) as c:
        register(c,'SMO','Example SMO 2026','smo@example.org')
        csrf=login(c,'smo@example.org');oid=c.get('/api/me').json()['memberships'][0]['org_id']
        site={'org_id':oid,'name':'Example Private Hospital','type':'Private','address1':'12 Street','city':'Hyderabad','state':'Telangana','country':'India','pin':'500001'}
        r=c.post('/api/hospitals',headers={'x-csrf-token':csrf},json=site);assert r.status_code==422  # declaration missing
        r=c.post('/api/hospitals',headers={'x-csrf-token':csrf},json={**site,'declaration':True});assert r.status_code==200,r.text
        hid=r.json()['hospital_id']
        assert c.get('/api/hospital-search?q=example priv').json()['results'][0]['pin']=='500001'
        r=c.post('/api/invitations',headers={'x-csrf-token':csrf},json={'org_id':oid,'kind':'pi','role':'PI','hospital_id':hid,'full_name':'Example PI','email':'pi@example.org'});assert r.status_code==200,r.text
        token=r.json()['dev_invite_token']
        assert c.get('/api/invitation/'+token).status_code==200
    with TestClient(app) as c:
        p={'first':'Example','last':'PI','salutation':'Dr.','gender':'Other','email':'pi@example.org','phone':'9876543210','password':'Complex!123','confirm':'Complex!123'}
        r=c.post('/api/invitation/'+token+'/register',json={'person':p,'terms':True});assert r.status_code==200,r.text
        verify(c,r.json()['registration_id'],'pi@example.org')
        csrf=login(c,'pi@example.org')
        assert c.get('/api/me').json()['memberships']==[]
        r=c.post('/api/invitation/'+token+'/respond',headers={'x-csrf-token':csrf},json={'decision':'accept'});assert r.status_code==200,r.text
        assert c.get('/api/me').json()['memberships']==[] # PI relationship, NOT org membership
    with TestClient(app) as c:
        csrf=login(c,'smo@example.org')
        r=c.get('/api/dashboard/'+str(oid));assert len(r.json()['pis'])==1

def test_failed_login_warnings_captcha_lockout_and_unlock():
    with TestClient(app) as c:
        register(c,'CRO','Other CRO 2026','cro@example.org')
        r=c.post('/api/login',json={'email':'cro@example.org','password':'bad'});assert r.status_code==401 and 'Warning' in r.json()['detail']
        assert c.post('/api/login',json={'email':'cro@example.org','password':'bad'}).status_code==428  # CAPTCHA now required
        r=c.post('/api/login',json={'email':'cro@example.org','password':'bad',**CAPTCHA});assert r.status_code==401 and 'Final warning' in r.json()['detail']
        assert c.post('/api/login',json={'email':'cro@example.org','password':'bad',**CAPTCHA}).status_code==423
        assert c.post('/api/login',json={'email':'cro@example.org','password':'Complex!123',**CAPTCHA}).status_code==423
        assert c.post('/api/unlock/request',json={'email':'cro@example.org'}).status_code==200
        r=c.post('/api/unlock/complete',json={'email':'cro@example.org','code':code_for(c,'cro@example.org','email')});assert r.status_code==200,r.text
        login(c,'cro@example.org')

def test_unknown_email_gets_same_warnings():
    with TestClient(app) as c:
        r=c.post('/api/login',json={'email':'nobody@example.org','password':'bad'})
        assert r.status_code==401 and 'Warning' in r.json()['detail']

def test_registration_validation_rules():
    with TestClient(app) as c:
        weak=payload('CRO','Weak CRO','weak@example.org',password='password',confirm='password')
        assert c.post('/api/register',json=weak).status_code==422
        bad_cat={**payload('CRO','Cat CRO','cat@example.org')};bad_cat['organization']={**bad_cat['organization'],'subtypes':'Private'}
        assert c.post('/api/register',json=bad_cat).status_code==422
        no_spec={**payload('CRO','Spec CRO','spec@example.org')};no_spec['organization']={**no_spec['organization'],'subtypes':'Others'}
        assert c.post('/api/register',json=no_spec).status_code==422
        no_decl={**payload('CRO','Decl CRO','decl@example.org'),'accurate':False}
        assert c.post('/api/register',json=no_decl).status_code==422
        # Multi-select sponsor categories with a specified "Others" value are accepted.
        assert c.post('/api/register',json=payload('Sponsor','Multi Sponsor','sponsor@example.org')).status_code==200

def test_document_upload_type_check():
    with TestClient(app) as c:
        good=payload('CRO','Doc CRO','doc@example.org');good['organization']['legal_doc']={'name':'coi.pdf','data':base64.b64encode(b'%PDF-1.4 test').decode()}
        assert c.post('/api/register',json=good).status_code==200
        bad=payload('CRO','Exe CRO','exe@example.org');bad['organization']['legal_doc']={'name':'x.pdf','data':base64.b64encode(b'MZ\x90\x00').decode()}
        assert c.post('/api/register',json=bad).status_code==422

def test_alternate_email_must_be_verified_before_activation_and_recovery():
    with TestClient(app) as c:
        r=c.post('/api/register',json=payload('CRO','Alt CRO','main@example.org',alt_email='alt@example.org'));assert r.status_code==200,r.text
        uid=r.json()['registration_id'];assert r.json()['alt_email']
        verify(c,uid,'main@example.org')
        assert c.post('/api/login',json={'email':'main@example.org','password':'Complex!123'}).status_code==403  # alt not verified yet
        r=c.post('/api/verify-registration',json={'registration_id':uid,'channel':'alt_email','code':code_for(c,'alt@example.org','alt_email')})
        assert r.json()['complete']
        c.post('/api/recovery/request',json={'email':'alt@example.org'})
        r=c.post('/api/recovery/verify',json={'email':'alt@example.org','code':code_for(c,'alt@example.org','email')});assert r.status_code==200,r.text
        r=c.post('/api/recovery/complete',json={'email':'alt@example.org','reset_token':r.json()['reset_token'],'new_password':'Newer!Pass1'});assert r.status_code==200,r.text

def test_password_recovery_runs_in_separate_steps():
    with TestClient(app) as c:
        register(c,'CRO','Recovery Steps CRO','steps@example.org')
        assert c.post('/api/recovery/request',json={'email':'steps@example.org'}).status_code==200
        # Unknown email and wrong code get the same reply.
        assert c.post('/api/recovery/verify',json={'email':'nobody@example.org','code':'123456'}).json()['detail']=='Invalid or expired code'
        assert c.post('/api/recovery/verify',json={'email':'steps@example.org','code':'000000'}).json()['detail']=='Invalid or expired code'
        # A code alone can no longer change the password; it needs the reset pass from the verify step.
        assert c.post('/api/recovery/complete',json={'email':'steps@example.org','code':code_for(c,'steps@example.org','email'),'new_password':'Newer!Pass1'}).status_code==400
        r=c.post('/api/recovery/verify',json={'email':'steps@example.org','code':code_for(c,'steps@example.org','email')});assert r.status_code==200,r.text
        tok=r.json()['reset_token']
        assert c.post('/api/recovery/complete',json={'email':'steps@example.org','reset_token':tok,'new_password':'Newer!Pass1','confirm':'Other!Pass1'}).status_code==422
        assert c.post('/api/recovery/complete',json={'email':'steps@example.org','reset_token':tok,'new_password':'Newer!Pass1','confirm':'Newer!Pass1'}).status_code==200
        assert c.post('/api/recovery/complete',json={'email':'steps@example.org','reset_token':tok,'new_password':'Third!Pass1'}).status_code==400  # single use
        assert c.post('/api/login',json={'email':'steps@example.org','password':'Newer!Pass1'}).status_code==200

def test_hospital_can_remove_smo_and_smo_can_request_again():
    with TestClient(app) as c:
        register(c,'Site / Hospital / Institution','Relink Test Hospital','relink.hosp@example.org')
        register(c,'SMO','Relink Test SMO','relink.smo@example.org')
    site={'name':'Relink Test Hospital','type':'Private','address1':'Street 1','city':'Hyderabad','state':'Telangana','country':'India','pin':'500034'}
    with TestClient(app) as smo, TestClient(app) as hosp:
        s_csrf=login(smo,'relink.smo@example.org');s_oid=smo.get('/api/me').json()['memberships'][0]['org_id']
        h_csrf=login(hosp,'relink.hosp@example.org');h_oid=hosp.get('/api/me').json()['memberships'][0]['org_id']
        add=lambda:smo.post('/api/hospitals',headers={'x-csrf-token':s_csrf},json={**site,'org_id':s_oid})
        decide=lambda lid,dec:hosp.post(f'/api/hospital-links/{lid}/decision',headers={'x-csrf-token':h_csrf},json={'decision':dec})
        link=lambda:hosp.get(f'/api/dashboard/{h_oid}').json()['smo_links'][0]
        r=add();assert r.status_code==200 and r.json()['status']=='pending',r.text
        assert decide(link()['id'],'removed').status_code==409  # cannot remove before approval
        assert decide(link()['id'],'rejected').status_code==200
        r=add();assert r.status_code==200 and r.json()['status']=='pending',r.text  # rejected SMO may ask again
        assert add().status_code==409  # but not twice while pending
        assert decide(link()['id'],'active').status_code==200
        assert decide(link()['id'],'removed').status_code==200
        assert link()['status']=='removed'
        lid=smo.get(f'/api/dashboard/{s_oid}').json()['hospitals'][0]['link_id']
        r=smo.post(f'/api/hospital-links/{lid}/request-again',headers={'x-csrf-token':s_csrf});assert r.status_code==200 and r.json()['status']=='pending',r.text
        assert smo.post(f'/api/hospital-links/{lid}/request-again',headers={'x-csrf-token':s_csrf}).status_code==409

def test_pi_sees_all_smo_links_and_hospital_sees_its_pis():
    with TestClient(app) as c:
        register(c,'Site / Hospital / Institution','Shared PI Hospital','shared.hosp@example.org')
        register(c,'SMO','Shared PI SMO One','shared.smo1@example.org')
        register(c,'SMO','Shared PI SMO Two','shared.smo2@example.org')
    site={'name':'Shared PI Hospital','type':'Private','address1':'Street 1','city':'Hyderabad','state':'Telangana','country':'India','pin':'500034'}
    tokens=[]
    with TestClient(app) as hosp:
        h_csrf=login(hosp,'shared.hosp@example.org');h_oid=hosp.get('/api/me').json()['memberships'][0]['org_id']
        for em in ('shared.smo1@example.org','shared.smo2@example.org'):
            with TestClient(app) as smo:
                s_csrf=login(smo,em);s_oid=smo.get('/api/me').json()['memberships'][0]['org_id']
                hid=smo.post('/api/hospitals',headers={'x-csrf-token':s_csrf},json={**site,'org_id':s_oid}).json()['hospital_id']
                lid=next(l['id'] for l in hosp.get(f'/api/dashboard/{h_oid}').json()['smo_links'] if l['status']=='pending')
                assert hosp.post(f'/api/hospital-links/{lid}/decision',headers={'x-csrf-token':h_csrf},json={'decision':'active'}).status_code==200
                r=smo.post('/api/invitations',headers={'x-csrf-token':s_csrf},json={'org_id':s_oid,'kind':'pi','role':'PI','hospital_id':hid,'full_name':'Shared PI','email':'shared.pi@example.org'})
                assert r.status_code==200,r.text;tokens.append(r.json()['dev_invite_token'])
        with TestClient(app) as pi:
            p={'first':'Shared','last':'PI','salutation':'Dr.','gender':'Other','email':'shared.pi@example.org','phone':'9876543210','password':'Complex!123','confirm':'Complex!123'}
            r=pi.post('/api/invitation/'+tokens[0]+'/register',json={'person':p,'terms':True});assert r.status_code==200,r.text
            verify(pi,r.json()['registration_id'],'shared.pi@example.org')
            assert pi.post('/api/invitation/'+tokens[1]+'/register',json={'person':p,'terms':True}).status_code==409  # one account only
            p_csrf=login(pi,'shared.pi@example.org')
            for t in tokens:assert pi.post('/api/invitation/'+t+'/respond',headers={'x-csrf-token':p_csrf},json={'decision':'accept'}).status_code==200
            me=pi.get('/api/me').json()
            assert me['memberships']==[] and sorted(a['smo'] for a in me['pi_affiliations'])==['Shared PI SMO One','Shared PI SMO Two']
        pis=hosp.get(f'/api/dashboard/{h_oid}').json()['hospital_pis']
        assert len(pis)==2 and {x['email'] for x in pis}=={'shared.pi@example.org'} and {x['smo'] for x in pis}=={'Shared PI SMO One','Shared PI SMO Two'}

def test_invitation_roles_duplicates_resend_cancel_and_in_app_answer():
    with TestClient(app) as c:
        register(c,'Sponsor','Invite Rules Sponsor','rules.sponsor@example.org')
    with TestClient(app) as a, TestClient(app) as anon:
        csrf=login(a,'rules.sponsor@example.org');oid=a.get('/api/me').json()['memberships'][0]['org_id'];h={'x-csrf-token':csrf}
        inv=lambda role,em:a.post('/api/invitations',headers=h,json={'org_id':oid,'kind':'member','role':role,'full_name':'Some One','email':em})
        assert inv('Super User','x1@example.org').status_code==422      # made-up role
        assert inv('PI','x2@example.org').status_code==422              # PI is not a Sponsor member role
        assert inv('Others: Data Manager','x3@example.org').status_code==200
        r=inv('Org Admin','coadmin@example.org');assert r.status_code==200
        assert inv('Research Team','coadmin@example.org').status_code==409  # already waiting
        iid,old=r.json()['invitation_id'],r.json()['dev_invite_token']
        new=a.post(f'/api/invitations/{iid}/resend',headers=h).json()['dev_invite_token']
        assert anon.get(f'/api/invitation/{old}').status_code==404 and anon.get(f'/api/invitation/{new}').status_code==200
        p={'first':'Co','last':'Admin','salutation':'Dr.','gender':'Other','email':'coadmin@example.org','phone':'9876543210','password':'Complex!123','confirm':'Complex!123'}
        r=anon.post(f'/api/invitation/{new}/register',json={'person':p,'terms':True});assert r.status_code==200,r.text
        verify(anon,r.json()['registration_id'],'coadmin@example.org')
    with TestClient(app) as co:
        co_csrf=login(co,'coadmin@example.org');pending=co.get('/api/me').json()['invitations']
        assert len(pending)==1 and pending[0]['role']=='Org Admin'
        assert co.post(f"/api/invitations/{pending[0]['id']}/respond",headers={'x-csrf-token':co_csrf},json={'decision':'accept'}).status_code==200
        assert co.get('/api/me').json()['memberships'][0]['role']=='Org Admin'
        r=co.post('/api/invitations',headers={'x-csrf-token':co_csrf},json={'org_id':oid,'kind':'member','role':'Research Team','full_name':'Later','email':'later@example.org'})
        assert r.status_code==200  # the co-admin can invite
        later=r.json()['invitation_id']
        assert co.post(f'/api/invitations/{later}/cancel',headers={'x-csrf-token':co_csrf}).status_code==200
        assert co.post(f'/api/invitations/{later}/resend',headers={'x-csrf-token':co_csrf}).status_code==409  # cancelled stays cancelled

def test_mtb_admin_console_block_unblock_delete():
    before=os.environ.get('MTB_ADMIN_EMAILS');os.environ['MTB_ADMIN_EMAILS']='boss@example.org'
    try:
        with TestClient(app) as c:
            register(c,'CRO','Console Test CRO','console.cro@example.org')
            register(c,'Sponsor','Console Admin Org','boss@example.org')
        with TestClient(app) as boss, TestClient(app) as cro:
            b_csrf=login(boss,'boss@example.org');h={'x-csrf-token':b_csrf}
            c_csrf=login(cro,'console.cro@example.org');coid=cro.get('/api/me').json()['memberships'][0]['org_id']
            assert cro.get('/api/admin/overview').status_code==403            # ordinary users are kept out
            ov=boss.get('/api/admin/overview').json()
            assert ov['users']['total']>=2 and len(ov['signups'])==30 and boss.get('/api/me').json()['is_mtb_admin']
            uid=next(u['id'] for u in boss.get('/api/admin/users?q=console.cro').json()['users'])
            # Block a person: signed out at once, cannot sign in, cannot reset the password.
            assert boss.post(f'/api/admin/users/{uid}/action',headers=h,json={'action':'block'}).status_code==200
            assert cro.get('/api/me').status_code==401  # signed out at once
            r=cro.post('/api/login',json={'email':'console.cro@example.org','password':'Complex!123'});assert r.status_code==403 and 'suspended' in r.json()['detail']
            assert boss.post(f'/api/admin/users/{uid}/action',headers=h,json={'action':'unblock'}).status_code==200
            c_csrf=login(cro,'console.cro@example.org')
            # Block the organization: its members lose that workspace.
            assert boss.post(f'/api/admin/organizations/{coid}/action',headers=h,json={'action':'block'}).status_code==200
            assert cro.get(f'/api/dashboard/{coid}').status_code==403 and cro.get('/api/me').json()['memberships']==[]
            assert boss.post(f'/api/admin/organizations/{coid}/action',headers=h,json={'action':'unblock'}).status_code==200
            assert cro.get(f'/api/dashboard/{coid}').status_code==200
            # The only admin of an active organization cannot be deleted before the organization.
            assert boss.post(f'/api/admin/users/{uid}/action',headers=h,json={'action':'delete'}).status_code==409
            assert boss.post(f'/api/admin/organizations/{coid}/action',headers=h,json={'action':'delete','confirm_name':'wrong'}).status_code==422
            assert boss.post(f'/api/admin/organizations/{coid}/action',headers=h,json={'action':'delete','confirm_name':'Console Test CRO'}).status_code==200
            assert boss.post(f'/api/admin/users/{uid}/action',headers=h,json={'action':'delete'}).status_code==200
            assert not boss.get('/api/admin/users?q=console.cro').json()['users']    # personal details erased
            assert any(a['action']=='mtb_admin_user_delete' for a in boss.get('/api/admin/activity').json()['activity'])
            # MTB Admin accounts are protected from these actions, including your own.
            me_id=next(u['id'] for u in boss.get('/api/admin/users?q=boss@').json()['users'])
            assert boss.post(f'/api/admin/users/{me_id}/action',headers=h,json={'action':'block'}).status_code==409
        with TestClient(app) as c:
            register(c,'CRO','Console Test CRO','console.cro2@example.org')  # a deleted name can be registered again
    finally:
        if before is None:os.environ.pop('MTB_ADMIN_EMAILS',None)
        else:os.environ['MTB_ADMIN_EMAILS']=before

def test_designation_and_role_are_kept_per_organization():
    with TestClient(app) as c:
        r=c.post('/api/register',json=payload('Sponsor','Desig Sponsor','desig.ana@example.org',designation='Research Director'));assert r.status_code==200,r.text
        verify(c,r.json()['registration_id'],'desig.ana@example.org')
        register(c,'CRO','Desig CRO','desig.cro@example.org')
    with TestClient(app) as ana, TestClient(app) as cro:
        a_csrf=login(ana,'desig.ana@example.org');c_csrf=login(cro,'desig.cro@example.org')
        coid=cro.get('/api/me').json()['memberships'][0]['org_id']
        r=cro.post('/api/invitations',headers={'x-csrf-token':c_csrf},json={'org_id':coid,'kind':'member','role':'Research Team','full_name':'Ana','email':'desig.ana@example.org','designation':'Clinical Lead','department':'Oncology'})
        tok=r.json()['dev_invite_token']
        assert ana.post(f'/api/invitation/{tok}/respond',headers={'x-csrf-token':a_csrf},json={'decision':'accept'}).status_code==200
        ms={m['name']:m for m in ana.get('/api/me').json()['memberships']}
        assert (ms['Desig Sponsor']['role'],ms['Desig Sponsor']['designation'])==('Org Admin','Research Director')
        assert (ms['Desig CRO']['role'],ms['Desig CRO']['designation'],ms['Desig CRO']['department'])==('Research Team','Clinical Lead','Oncology')
        m=next(x for x in cro.get(f'/api/dashboard/{coid}').json()['members'] if x['email']=='desig.ana@example.org')
        assert (m['designation'],m['department'])==('Clinical Lead','Oncology')

def test_codes_die_after_five_wrong_tries():
    with TestClient(app) as c:
        r=c.post('/api/register',json=payload('CRO','Five Tries CRO','five@example.org'));uid=r.json()['registration_id']
        code=code_for(c,'five@example.org','email');wrong='000000' if code!='000000' else '111111'
        for _ in range(5):c.post('/api/verify-registration',json={'registration_id':uid,'channel':'email','code':wrong})
        assert c.post('/api/verify-registration',json={'registration_id':uid,'channel':'email','code':code}).status_code==400

def test_org_admin_audit_trail_per_organization_type():
    from app import db as app_db
    with TestClient(app) as c:
        register(c,'Site / Hospital / Institution','Audit Hospital','audit.hosp@example.org')
        register(c,'SMO','Audit SMO One','audit.smo1@example.org');register(c,'SMO','Audit SMO Two','audit.smo2@example.org')
    site={'name':'Audit Hospital','type':'Private','address1':'Street 1','city':'Hyderabad','state':'Telangana','country':'India','pin':'500034'}
    with TestClient(app) as hosp, TestClient(app) as s1, TestClient(app) as s2, TestClient(app) as pi, TestClient(app) as anon:
        hh={'x-csrf-token':login(hosp,'audit.hosp@example.org')};h1={'x-csrf-token':login(s1,'audit.smo1@example.org')};h2={'x-csrf-token':login(s2,'audit.smo2@example.org')}
        hoid,o1,o2=[x.get('/api/me').json()['memberships'][0]['org_id'] for x in (hosp,s1,s2)]
        trail=lambda cl,oid:cl.get(f'/api/organizations/{oid}/audit').json()['events']
        acts=lambda cl,oid:[e['action'] for e in trail(cl,oid)]
        assert {'account_activated','organization_activated','registration_email_verified','login_success'}<=set(acts(s1,o1))
        hid=s1.post('/api/hospitals',headers=h1,json={**site,'org_id':o1}).json()['hospital_id']
        s2.post('/api/hospitals',headers=h2,json={**site,'org_id':o2})
        assert acts(hosp,hoid).count('hospital_affiliation_pending')==2            # the hospital sees both SMOs' requests
        lid=next(l['id'] for l in hosp.get(f'/api/dashboard/{hoid}').json()['smo_links'] if l['smo']=='Audit SMO One')
        hosp.post(f'/api/hospital-links/{lid}/decision',headers=hh,json={'decision':'active'})
        assert 'hospital_affiliation_active' in acts(s1,o1)                          # SMO One sees the hospital's decision
        r=s1.post('/api/invitations',headers=h1,json={'org_id':o1,'kind':'pi','role':'PI','hospital_id':hid,'full_name':'Audit PI','email':'audit.pi@example.org'})
        tok=r.json()['dev_invite_token']
        p={'first':'Audit','last':'PI','salutation':'Dr.','gender':'Other','email':'audit.pi@example.org','phone':'9876543210','password':'Complex!123','confirm':'Complex!123'}
        verify(anon,anon.post(f'/api/invitation/{tok}/register',json={'person':p,'terms':True}).json()['registration_id'],'audit.pi@example.org')
        pi_h={'x-csrf-token':login(pi,'audit.pi@example.org')}
        pi.post(f'/api/invitation/{tok}/respond',headers=pi_h,json={'decision':'accept'})
        assert {'invitation_sent','invitation_accepted','pi_link_created'}<=set(acts(s1,o1))
        assert 'pi_link_created' in acts(hosp,hoid)                                  # the hospital sees PIs joining its site
        smo2_events=json.dumps(trail(s2,o2))
        assert 'Audit SMO One' not in smo2_events and 'audit.pi@example.org' not in smo2_events and 'pi_link_created' not in smo2_events
        assert 'Audit SMO Two' not in json.dumps(trail(s1,o1))                       # competing SMOs never see each other
        # Member security events reach their admin; expired invitations are logged and can be resent.
        r=s1.post('/api/invitations',headers=h1,json={'org_id':o1,'kind':'member','role':'Research Team','full_name':'Late','email':'audit.late@example.org'})
        iid=r.json()['invitation_id']
        with app_db() as c:c.execute('UPDATE invitations SET expires=0 WHERE id=?',(iid,))
        assert 'invitation_expired' in acts(s1,o1)
        assert s1.post(f'/api/invitations/{iid}/resend',headers=h1).status_code==200
        assert pi.get(f'/api/organizations/{o1}/audit').status_code==403             # PIs and non-admins cannot read it

def test_audit_records_are_protected_and_complete():
    import sqlite3, logging
    import app as app_module
    from app import db as app_db, verify_audit_chain, RedactTokens
    with TestClient(app) as c:
        register(c,'CRO','Sealed Audit CRO','sealed@example.org')
        c.post('/api/recovery/request',json={'email':'sealed@example.org'})
        tok=c.post('/api/recovery/verify',json={'email':'sealed@example.org','code':code_for(c,'sealed@example.org','email')}).json()['reset_token']
        c.post('/api/recovery/complete',json={'email':'sealed@example.org','reset_token':tok,'new_password':'Newer!Pass1'},headers={'user-agent':'AuditTest/1.0'})
    with app_db() as c:
        row=c.execute('SELECT * FROM audit WHERE action="password_reset" ORDER BY id DESC LIMIT 1').fetchone()
        assert row['ip'] and json.loads(row['details'])['device']=='AuditTest/1.0' and row['row_hash']   # IP + device on security events
        assert verify_audit_chain(c)['ok']
        for sql in ('UPDATE audit SET action="nothing" WHERE id=?','DELETE FROM audit WHERE id=?'):
            try:c.execute(sql,(row['id'],));assert False,'audit record was changed'
            except sqlite3.DatabaseError as e:assert 'Audit records cannot' in str(e)
    # Nothing secret is written to logs: passwords, codes and tokens never appear in audit details.
    with app_db() as c:
        everything=' '.join(r['details'] or '' for r in c.execute('SELECT details FROM audit'))
    assert 'Newer!Pass1' not in everything and tok not in everything
    # Tokens are masked in the server's request log, and outside test mode the outbox keeps no readable codes.
    rec=logging.LogRecord('uvicorn.access',logging.INFO,'',0,'%s "%s %s"',('1.2.3.4','GET','/api/invitation/'+'A'*40+'/respond'),None)
    RedactTokens().filter(rec);assert 'A'*40 not in rec.getMessage() and '[redacted]' in rec.getMessage()
    app_module.DEV=False
    try:
        with app_db() as c:app_module.outbox(c,'x@example.org','Your code is 123456. Open /#invite='+'B'*40)
        with app_db() as c:body=c.execute('SELECT body FROM outbox ORDER BY id DESC LIMIT 1').fetchone()['body']
        assert '123456' not in body and 'B'*40 not in body
    finally:app_module.DEV=True

def test_site_profile_edit_duplicates_notice_unlock_reset_and_invite_wording():
    import app as app_module
    with TestClient(app) as c:
        register(c,'Site / Hospital / Institution','Sunrise Registered Hospital','fx.hosp@example.org')
        register(c,'SMO','Fix SMO One','fx.smo1@example.org');register(c,'SMO','Fix SMO Two','fx.smo2@example.org')
    site=lambda name,**k:{'name':name,'type':'Private','address1':'1 Road','city':'Chennai','state':'TN','country':'India','pin':'600001','declaration':True,**k}
    with TestClient(app) as s1, TestClient(app) as s2, TestClient(app) as anon:
        h1={'x-csrf-token':login(s1,'fx.smo1@example.org')};h2={'x-csrf-token':login(s2,'fx.smo2@example.org')}
        o1=s1.get('/api/me').json()['memberships'][0]['org_id'];o2=s2.get('/api/me').json()['memberships'][0]['org_id']
        # Near-duplicate hospital: asked first; linking by id or confirming "different" both work.
        hid=s1.post('/api/hospitals',headers=h1,json={**site('Lotus Clinic'),'org_id':o1}).json()['hospital_id']
        r=s2.post('/api/hospitals',headers=h2,json={**site('Lotus Clinic Pvt Ltd'),'org_id':o2})
        assert r.status_code==409 and r.json()['detail']['code']=='possible_duplicate' and r.json()['detail']['matches'][0]['id']==hid
        assert s2.post('/api/hospitals',headers=h2,json={**site('Lotus Clinic Pvt Ltd'),'org_id':o2,'hospital_id':hid}).json()['hospital_id']==hid
        r=s1.post('/api/hospitals',headers=h1,json={**site('Lotus Clinics',city='Chennai'),'org_id':o1,'different_confirmed':True});assert r.status_code==200 and r.json()['hospital_id']!=hid
        # Site profile: only the SMO that added the provisional site may edit it.
        assert s1.get(f'/api/hospitals/{hid}').json()['name']=='Lotus Clinic'
        assert s2.put(f'/api/hospitals/{hid}',headers=h2,json=site('Lotus Clinic')).status_code==403
        r=s1.put(f'/api/hospitals/{hid}',headers=h1,json=site('Lotus Clinic',address1='22 New Road',phone='9811122233'));assert r.json()['changed']==['address1','phone']
        assert any(e['action']=='hospital_profile_updated' for e in s1.get(f'/api/organizations/{o1}/audit').json()['events'])
        # Registered hospital: the SMO's request notifies the hospital admin; its profile is not editable by SMOs.
        rh=s1.post('/api/hospitals',headers=h1,json={**site('Sunrise Registered Hospital',city='Hyderabad',pin='500034'),'org_id':o1}).json()
        assert rh['status']=='pending' and any('asked to affiliate' in m['body'] for m in anon.get('/api/dev/outbox').json()['messages'] if m['target']=='fx.hosp@example.org')
        assert s1.get(f"/api/hospitals/{rh['hospital_id']}").status_code==403
        # Invitations are worded for people with / without an account.
        t=s1.post('/api/invitations',headers=h1,json={'org_id':o1,'kind':'member','role':'Research Team','full_name':'Two','email':'fx.smo2@example.org'}).json()['dev_invite_token']
        assert anon.get(f'/api/invitation/{t}').json()['has_account'] is True
        t=s1.post('/api/invitations',headers=h1,json={'org_id':o1,'kind':'member','role':'Research Team','full_name':'New','email':'fx.new@example.org'}).json()['dev_invite_token']
        assert anon.get(f'/api/invitation/{t}').json()['has_account'] is False
        msgs={m['target']:m['body'] for m in anon.get('/api/dev/outbox').json()['messages'] if m['kind']=='invite'}
        assert 'Sign in' in msgs['fx.smo2@example.org'] and 'Create your account' in msgs['fx.new@example.org']
    # Unlocking hands back a reset pass, so "Reset my password" needs no second code.
    with TestClient(app) as c:
        c.post('/api/login',json={'email':'fx.smo2@example.org','password':'bad'})
        for _ in range(2):c.post('/api/login',json={'email':'fx.smo2@example.org','password':'bad',**CAPTCHA})  # third failure locks
        c.post('/api/unlock/request',json={'email':'fx.smo2@example.org'})
        r=c.post('/api/unlock/complete',json={'email':'fx.smo2@example.org','code':code_for(c,'fx.smo2@example.org','email')});assert r.status_code==200
        assert c.post('/api/recovery/complete',json={'email':'fx.smo2@example.org','reset_token':r.json()['reset_token'],'new_password':'Fresh!Pass9'}).status_code==200
        assert c.post('/api/login',json={'email':'fx.smo2@example.org','password':'Fresh!Pass9'}).status_code==200
    # Outside test mode, plain http is redirected to https (local addresses excepted).
    app_module.FORCE_HTTPS=True
    try:
        with TestClient(app,base_url='http://mtb.example.org') as c:
            r=c.get('/health',follow_redirects=False);assert r.status_code==308 and r.headers['location'].startswith('https://')
        with TestClient(app,base_url='https://mtb.example.org') as c:
            assert 'max-age' in c.get('/health').headers['strict-transport-security']
    finally:app_module.FORCE_HTTPS=False

def test_mtb_admin_sees_possible_duplicates():
    before=os.environ.get('MTB_ADMIN_EMAILS');os.environ['MTB_ADMIN_EMAILS']='dup.boss@example.org'
    try:
        with TestClient(app) as c:
            register(c,'Sponsor','Dup Boss Org','dup.boss@example.org')
            r=c.post('/api/register',json=payload('CRO','Dup CRO','dup.one@example.org',phone='9555512345'));verify_phone=r.json()['registration_id']
            r2=c.post('/api/register',json=payload('Sponsor','Dup Sponsor','dup.two@example.org',phone='+91 95555 12345'))
        with TestClient(app) as boss:
            login(boss,'dup.boss@example.org')
            groups=boss.get('/api/admin/overview').json()['duplicate_people']
            g=next(g for g in groups if g['phone'].endswith('2345'))
            assert {'dup.one@example.org','dup.two@example.org'}<={a['email'] for a in g['accounts']}
    finally:
        if before is None:os.environ.pop('MTB_ADMIN_EMAILS',None)
        else:os.environ['MTB_ADMIN_EMAILS']=before

def test_emails_go_through_brevo_when_a_key_is_set(monkeypatch):
    """Uses a fake Brevo: checks what would be sent, without sending anything."""
    import mailer, app as app_module
    sent,mode=[],{'ok':True}
    class FakeResponse:
        def __init__(self,code,body):self.status_code,self._body,self.text=code,body,str(body)
        def json(self):return self._body
    def fake_post(url,**kw):
        sent.append({'url':url,**kw})
        return FakeResponse(201,{'messageId':'<m%d@brevo>'%len(sent)}) if mode['ok'] else FakeResponse(400,{'message':'sender not valid'})
    monkeypatch.setattr(mailer.httpx,'post',fake_post)
    monkeypatch.setenv('BREVO_API_KEY','test-key');monkeypatch.setenv('MTB_MAIL_FROM','bhanodai2005@gmail.com');monkeypatch.setenv('MTB_APP_URL','https://mtb.example.org')
    with TestClient(app) as c:
        r=c.post('/api/register',json=payload('CRO','Mail Test CRO','mail.cro@mailcheck-mtb.in'));assert r.status_code==200,r.text
        mail=next(m for m in sent if m['json']['to'][0]['email']=='mail.cro@mailcheck-mtb.in')
        assert mail['url']=='https://api.brevo.com/v3/smtp/email' and mail['headers']['api-key']=='test-key'
        assert mail['json']['sender']=={'name':'My Trial Board','email':'bhanodai2005@gmail.com'}
        code=code_for(c,'mail.cro@mailcheck-mtb.in','email')
        assert mail['json']['subject']=='Verify your email for My Trial Board' and code in mail['json']['htmlContent'] and code in mail['json']['textContent']
        assert not any(m['json']['to'][0]['email']=='9876543210' for m in sent)            # SMS is not sent yet
        before=len(sent);c.post('/api/register',json=payload('CRO','Reserved Domain CRO','someone@example.org',phone='9123400000'))
        assert len(sent)==before                                                            # example.org etc. are never really sent
        verify(c,r.json()['registration_id'],'mail.cro@mailcheck-mtb.in')
        h={'x-csrf-token':login(c,'mail.cro@mailcheck-mtb.in')};oid=c.get('/api/me').json()['memberships'][0]['org_id']
        c.post('/api/invitations',headers=h,json={'org_id':oid,'kind':'member','role':'Research Team','full_name':'Mia','email':'mail.mia@mailcheck-mtb.in'})
        inv=sent[-1]['json'];assert inv['subject']=='Mail Test CRO invited you to My Trial Board' and 'https://mtb.example.org/#invite=' in inv['textContent']
        # Brevo refuses: a code or invitation fails loudly so the person can retry; nothing half-done is kept.
        mode['ok']=False
        r=c.post('/api/register',json=payload('Sponsor','Mail Fail Sponsor','mail.fail@mailcheck-mtb.in'));assert r.status_code==502
        mode['ok']=True
        assert c.post('/api/register',json=payload('Sponsor','Mail Fail Sponsor','mail.fail@mailcheck-mtb.in')).status_code==200
        # A notice that fails does not block the action; the failure is logged.
        mode['ok']=False
        assert c.post('/api/join-requests',json={'org_id':oid,'full_name':'Joiner','email':'mail.joiner@mailcheck-mtb.in','phone':'9876543210','message':'Hi'}).status_code==200
        with app_module.db() as x:assert x.execute('SELECT COUNT(*) FROM audit WHERE action="email_send_failed"').fetchone()[0]>=1

def test_emails_can_go_through_brevo_smtp(monkeypatch):
    """Uses a fake SMTP server: checks the login, sender and message, without sending anything."""
    import mailer
    seen={}
    class FakeSMTP:
        def __init__(self,host,port,timeout=None):seen['server']=(host,port)
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def starttls(self,context=None):seen['tls']=True
        def login(self,user,key):
            if key!='right-key':raise mailer.smtplib.SMTPAuthenticationError(535,b'bad')
            seen['login']=user
        def send_message(self,msg):seen['msg']=msg
    monkeypatch.setattr(mailer.smtplib,'SMTP',FakeSMTP)
    monkeypatch.setenv('BREVO_API_KEY','');monkeypatch.setenv('BREVO_SMTP_LOGIN','abc123@smtp-brevo.com');monkeypatch.setenv('BREVO_SMTP_KEY','right-key')
    assert mailer.mode()=='smtp' and mailer.account_status()['ok']
    mailer.send('person@example.org','Verify your email for My Trial Board','Your My Trial Board verification code is 123456.','email')
    m=seen['msg']
    assert seen['server']==('smtp-relay.brevo.com',587) and seen['tls'] and seen['login']=='abc123@smtp-brevo.com'
    assert m['To']=='person@example.org' and 'bhanodai2005@gmail.com' in m['From'] and m['Subject']=='Verify your email for My Trial Board'
    assert '123456' in m.get_body(('html',)).get_content() and '123456' in m.get_body(('plain',)).get_content()
    monkeypatch.setenv('BREVO_SMTP_KEY','wrong-key')
    assert not mailer.account_status()['ok']
    try:mailer.send('person@example.org','x','y');assert False
    except mailer.MailError as e:assert 'did not accept' in str(e)

def test_phone_code_shown_on_screen_only_when_switched_on(monkeypatch):
    import app as app_module
    with TestClient(app) as c:
        r=c.post('/api/register',json=payload('CRO','Harbor Analytics','screen.off@example.org',phone='9333300001'))
        assert 'phone_code_on_screen' not in r.json()
        monkeypatch.setattr(app_module,'PHONE_CODE_ON_SCREEN',True)
        r=c.post('/api/register',json=payload('CRO','Meridian Biostat','screen.on@example.org',phone='9333300002')).json()
        shown=r['phone_code_on_screen'];assert shown==code_for(c,'9333300002','phone')
        assert c.post('/api/verify-registration',json={'registration_id':r['registration_id'],'channel':'phone','code':shown}).json()['phone_verified']
        again=c.post('/api/resend-otp',json={'registration_id':r['registration_id'],'channel':'email'}).json()
        assert 'phone_code_on_screen' not in again                       # email codes are never shown on screen
