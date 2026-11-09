"""Hospitals, SMOs and PIs (BRD 4, 5, 14, 16, 19, 20.2-20.4)."""
from helpers import PW, uid, api_org, api_session, login, home, verify_codes, rows, tab, outbox

SITE = {'type': 'Private', 'address1': '4 River Road', 'city': 'Pune', 'state': 'Maharashtra', 'country': 'India', 'pin': '411001', 'declaration': True}


def open_add_hospital(page):
    tab(page, 'Hospitals'); page.click('text=+ Add Hospital / Site'); page.wait_for_selector('#m_name')


def fill_new_site(page, name, pin='411001'):
    page.fill('#m_name', name); page.keyboard.press('Escape'); page.select_option('#m_type', 'Private')
    for f, v in {'m_address1': '4 River Road', 'm_city': 'Pune', 'm_state': 'Maharashtra', 'm_pin': pin}.items(): page.fill('#' + f, v)


def test_registered_hospital_request_approve_reject_again_and_remove(page, base_url):
    h, ph = uid('rh'); s, ps = uid('rs')
    hosp_name = f'{h.title()} Medicity'
    api_org(base_url, 'Site / Hospital / Institution', hosp_name, f'{h}@example.org', ph, city='Pune', pin='411001')
    api_org(base_url, 'SMO', f'{s.title()} Sitecare', f'{s}@example.org', ps)
    # 20.2: SMO searches, sees "Registered", sends a request (no declaration needed for an existing hospital).
    login(page, base_url, f'{s}@example.org', expect='.dash-top h2'); open_add_hospital(page)
    page.type('#m_name', hosp_name[:8], delay=60); page.wait_for_selector('.ac-list')
    assert 'Registered' in page.inner_text('.ac-list')
    page.locator('.ac-list >> text=' + hosp_name).first.click()
    assert page.inner_text('#modalSubmit').startswith('Send affiliation request') and not page.is_visible('#m_declaration')
    page.click('#modalSubmit'); page.wait_for_timeout(1200)
    assert any(hosp_name in r and 'pending' in r for r in rows(page))
    assert any('asked to affiliate' in m for m in outbox(base_url, f'{h}@example.org')), 'hospital admin was not told'
    # Hospital rejects; SMO asks again; hospital approves; then removes the SMO.
    login(page, base_url, f'{h}@example.org', expect='.dash-top h2'); tab(page, 'Hospitals')
    page.locator('button', has_text='Reject').first.click(); page.wait_for_timeout(1000)
    login(page, base_url, f'{s}@example.org', expect='.dash-top h2'); tab(page, 'Hospitals')
    assert any('rejected' in r for r in rows(page)); page.click('text=Request again'); page.wait_for_timeout(1000)
    assert any('pending' in r for r in rows(page))
    login(page, base_url, f'{h}@example.org', expect='.dash-top h2'); tab(page, 'Hospitals')
    page.locator('button', has_text='Approve').first.click(); page.wait_for_timeout(1000)
    assert any(f'{s.title()} Sitecare' in r and 'active' in r for r in rows(page))
    page.once('dialog', lambda d: d.accept()); page.locator('button', has_text='Remove').first.click(); page.wait_for_timeout(1000)
    assert any('removed' in r for r in rows(page))


def test_provisional_site_profile_edit_only_by_the_smo_that_added_it(page, base_url):
    s1, p1 = uid('ps1'); s2, p2 = uid('ps2')
    api_org(base_url, 'SMO', f'{s1.title()} Alpha', f'{s1}@example.org', p1); api_org(base_url, 'SMO', f'{s2.title()} Beta', f'{s2}@example.org', p2)
    site_name = f'{s1.title()} Lotus Clinic'
    login(page, base_url, f'{s1}@example.org', expect='.dash-top h2'); open_add_hospital(page)
    fill_new_site(page, site_name); page.check('#m_declaration'); page.click('#modalSubmit'); page.wait_for_timeout(1200)
    assert any(site_name in r and 'Provisional' in r and 'active' in r for r in rows(page))
    page.click('text=Edit site profile'); page.wait_for_selector('#m_address1')
    assert page.input_value('#m_name') == site_name
    page.fill('#m_address1', '99 Updated Road'); page.check('#m_declaration'); page.click('#modalSubmit')
    page.wait_for_selector('#toast.show'); assert 'saved' in page.inner_text('#toast').lower()
    hid = next(h['id'] for h in api_session(base_url, f'{s1}@example.org').get(f"/api/dashboard/{api_session(base_url, f'{s1}@example.org').org}").json()['hospitals'])
    assert api_session(base_url, f'{s1}@example.org').get(f'/api/hospitals/{hid}').json()['address1'] == '99 Updated Road'
    # The other SMO links to the same record but cannot edit it.
    b = api_session(base_url, f'{s2}@example.org')
    assert b.post('/api/hospitals', json={**SITE, 'name': site_name, 'org_id': b.org, 'hospital_id': hid}).json()['hospital_id'] == hid
    login(page, base_url, f'{s2}@example.org', expect='.dash-top h2'); tab(page, 'Hospitals')
    assert any(site_name in r for r in rows(page)) and page.locator('text=Edit site profile').count() == 0


def test_possible_duplicate_hospital_prompt(page, base_url):
    s1, p1 = uid('dh1'); s2, p2 = uid('dh2')
    api_org(base_url, 'SMO', f'{s1.title()} Gamma', f'{s1}@example.org', p1); api_org(base_url, 'SMO', f'{s2.title()} Delta', f'{s2}@example.org', p2)
    a = api_session(base_url, f'{s1}@example.org')
    original = f'{s1.title()} Sunrise Hospital'
    hid = a.post('/api/hospitals', json={**SITE, 'name': original, 'org_id': a.org}).json()['hospital_id']
    login(page, base_url, f'{s2}@example.org', expect='.dash-top h2')
    # "Use this hospital": links to the existing record.
    open_add_hospital(page); fill_new_site(page, f'{s1.title()} Sunrise Hospitals Pvt Ltd'); page.check('#m_declaration'); page.click('#modalSubmit')
    page.wait_for_selector('text=Is it the same one?'); page.click('text=Use this hospital')
    assert page.inner_text('#modalSubmit').startswith('Link to this site'); page.click('#modalSubmit'); page.wait_for_timeout(1200)
    assert [r for r in rows(page) if 'Sunrise' in r] and len([r for r in rows(page) if 'Sunrise' in r]) == 1
    # "No, it's a different hospital": a new record, flagged for MTB review.
    open_add_hospital(page); fill_new_site(page, f'{s1.title()} Sunrise Hospitals Annexe'.replace(' Annexe', ''), pin='411002')
    page.fill('#m_name', f'{s1.title()} Sunrise Hospitals'); page.check('#m_declaration'); page.click('#modalSubmit')
    page.wait_for_selector("text=No, it's a different hospital"); page.click("text=No, it's a different hospital"); page.wait_for_timeout(1500)
    assert len([r for r in rows(page) if 'Sunrise' in r]) == 2


def test_pi_with_two_smos_one_login_and_no_cross_smo_visibility(page, base_url):
    s1, p1 = uid('pa'); s2, p2 = uid('pb'); pi, ppi = uid('pi')
    api_org(base_url, 'SMO', f'{s1.title()} One', f'{s1}@example.org', p1); api_org(base_url, 'SMO', f'{s2.title()} Two', f'{s2}@example.org', p2)
    a, b = api_session(base_url, f'{s1}@example.org'), api_session(base_url, f'{s2}@example.org')
    site = f'{pi.title()} Riverside Clinic'
    hid = a.post('/api/hospitals', json={**SITE, 'name': site, 'org_id': a.org}).json()['hospital_id']
    b.post('/api/hospitals', json={**SITE, 'name': site, 'org_id': b.org, 'hospital_id': hid})
    # 20.3: PI accepts SMO One through the link (creates an account).
    login(page, base_url, f'{s1}@example.org', expect='.dash-top h2'); page.click('text=+ Invite affiliated PI'); page.wait_for_selector('#m_hospital_id')
    page.select_option('#m_hospital_id', label=page.locator('#m_hospital_id option', has_text=site).inner_text())
    page.fill('#m_full_name', 'Dr Pia'); page.fill('#m_email', f'{pi}@example.org'); page.select_option('#m_role', 'PI'); page.click('#modalSubmit')
    page.wait_for_selector('#modalResult code'); link = page.inner_text('#modalResult code')
    page.evaluate('logout()'); page.wait_for_selector('#login_email'); page.goto(link); page.reload()
    page.click('#invitationInfo >> text=Create your account'); page.wait_for_selector('#p_first')
    page.select_option('#p_salutation', 'Dr.'); page.select_option('#p_gender', 'Female')
    for f, v in {'p_first': 'Pia', 'p_last': 'Investigator', 'p_phone': ppi, 'p_password': PW, 'p_confirm': PW}.items(): page.fill('#' + f, v)
    page.check('#inviteTerms'); page.click('#inviteSubmit'); verify_codes(page, base_url, f'{pi}@example.org', ppi)
    page.click('.success-card >> text=Login'); page.fill('#login_email', f'{pi}@example.org'); page.fill('#login_password', PW)
    page.dispatch_event('#login_password', 'input'); page.click('#loginBtn'); page.click('text=Accept invitation'); page.wait_for_selector('text=My SMO affiliations')
    # 20.4: SMO Two invites the same PI; the PI accepts from the dashboard with the same login.
    b.post('/api/invitations', json={'org_id': b.org, 'kind': 'pi', 'role': 'Research Team', 'hospital_id': hid, 'full_name': 'Dr Pia', 'email': f'{pi}@example.org'})
    login(page, base_url, f'{pi}@example.org', expect='.dash-top'); page.wait_for_selector('text=Pending invitations for you')
    page.locator('.attention button', has_text='Accept').click(); page.wait_for_timeout(1500)
    panel = page.inner_text('.own-card')
    assert f'{s1.title()} One' in panel and f'{s2.title()} Two' in panel and 'Research Team' in panel
    assert [t.strip() for t in page.locator('.sidebar .side-link').all_inner_texts()][0].endswith('My affiliations')
    assert page.locator('.sidebar >> text=Team members').count() == 0, 'empty workspace tabs shown to a PI'
    # Neither SMO sees the other through the shared PI.
    login(page, base_url, f'{s2}@example.org', expect='.dash-top h2'); tab(page, 'Affiliated PIs')
    body = page.inner_text('.dash-body')
    assert f'{pi}@example.org' in body and f'{s1.title()} One' not in body
