"""More possibilities: join requests, ownership claims, deactivation, alternate email, "Others (specify)",
admin delete actions, workspace switcher, resending codes, phone-size dashboard, PI invite without a hospital."""
from conftest import ADMIN_EMAIL
from helpers import (PW, uid, code, api_org, api_session, login, start_registration, fill_org_step, fill_person_step,
                     finish_terms, verify_codes, rows, tab, no_horizontal_scroll)


def test_join_request_from_the_duplicate_warning_then_admin_invites(page, base_url):
    adm, ph = uid('join'); name = f'{adm.title()} Clinicals'
    api_org(base_url, 'CRO', name, f'{adm}@example.org', ph)
    start_registration(page, base_url)
    fill_org_step(page, 'CRO', name, uid('x')[1], cats=['Clinical Trials']); page.click('#regNext')
    page.wait_for_selector('text=This organization is already on My Trial Board'); page.click('text=Request to join')
    page.wait_for_selector('#j_name'); page.fill('#j_name', 'Jay Joiner'); page.fill('#j_email', f'{adm}.jay@example.org'); page.fill('#j_message', 'I lead data management here.')
    page.click('text=Send request ↗'); page.wait_for_selector('.alert.ok'); page.click('[data-close]:has-text("Done")')
    login(page, base_url, f'{adm}@example.org', expect='.dash-top h2')
    page.wait_for_selector('text=Jay Joiner'); assert 'I lead data management here.' in page.inner_text('.dash-body')
    page.locator('.join-row', has_text='Jay Joiner').locator('button', has_text='Invite').click()
    page.wait_for_selector('#m_email'); assert page.input_value('#m_email') == f'{adm}.jay@example.org'
    page.select_option('#m_role', 'Research Team'); page.click('#modalSubmit'); page.wait_for_selector('#modalResult code')


def test_ownership_claim_with_a_matching_email_domain_is_approved(page, base_url):
    old, ph = uid('claimold'); name = f'{old.title()} Biologics'
    api_org(base_url, 'Sponsor', name, f'{old}@example.org', ph, website=f'https://{old}-bio.in')
    start_registration(page, base_url)
    fill_org_step(page, 'Sponsor', name, uid('x')[1], cats=['Pharmaceutical']); page.click('#regNext')
    page.wait_for_selector('text=This is my organization'); page.click('text=This is my organization')
    page.click('text=Continue as representative'); page.wait_for_selector('.claim-strip')
    page.click('#regNext'); page.wait_for_selector('#p_first')
    rep_email, rep_phone = f'ceo@{old}-bio.in', uid('rep')[1]
    fill_person_step(page, rep_email, rep_phone); page.click('#regNext')
    finish_terms(page)
    page.wait_for_selector('#emailCode')
    page.fill('#emailCode', code(base_url, rep_email)); page.click("button[onclick=\"verifyCode('email')\"]"); page.wait_for_selector('#emailCode[disabled]')
    page.fill('#phoneCode', code(base_url, rep_phone, 'phone')); page.click("button[onclick=\"verifyCode('phone')\"]")
    page.wait_for_selector('.success-card'); assert page.locator('.success-card .alert.ok').count() == 1, 'claim was not approved'
    login(page, base_url, rep_email, expect='.dash-top h2')
    assert page.inner_text('.dash-top h2') == name and 'Org Admin' in page.inner_text('.dash-body')


def test_admin_deactivates_a_member_who_keeps_other_affiliations(page, base_url):
    a, pa = uid('dea'); b, pb = uid('deb')
    api_org(base_url, 'Sponsor', f'{a.title()} Pharma', f'{a}@example.org', pa); api_org(base_url, 'CRO', f'{b.title()} Trials', f'{b}@example.org', pb)
    owner = api_session(base_url, f'{a}@example.org')
    tok = owner.post('/api/invitations', json={'org_id': owner.org, 'kind': 'member', 'role': 'Research Team', 'full_name': 'B', 'email': f'{b}@example.org'}).json()['dev_invite_token']
    api_session(base_url, f'{b}@example.org').post(f'/api/invitation/{tok}/respond', json={'decision': 'accept'})
    login(page, base_url, f'{a}@example.org', expect='.dash-top h2'); tab(page, 'Team members')
    page.once('dialog', lambda d: d.accept()); page.locator('tr', has_text=f'{b}@example.org').locator('button', has_text='Deactivate').click()
    page.wait_for_timeout(1000); assert any(f'{b}@example.org' in r and 'inactive' in r for r in rows(page))
    left = [m['name'] for m in api_session(base_url, f'{b}@example.org').get('/api/me').json()['memberships']]
    assert left == [f'{b.title()} Trials']


def test_alternate_email_needs_its_own_code(page, base_url):
    who, phone = uid('alt'); email, alt = f'{who}@example.org', f'{who}.alt@example.org'
    start_registration(page, base_url)
    fill_org_step(page, 'SMO', f'{who.title()} Sitecare', phone); page.click('#regNext'); page.wait_for_selector('#p_first')
    fill_person_step(page, email, phone); page.fill('#p_alt_email', alt); page.click('#regNext')
    finish_terms(page); page.wait_for_selector('#alt_emailCode')
    page.fill('#emailCode', code(base_url, email)); page.click("button[onclick=\"verifyCode('email')\"]"); page.wait_for_selector('#emailCode[disabled]')
    page.fill('#phoneCode', code(base_url, phone, 'phone')); page.click("button[onclick=\"verifyCode('phone')\"]"); page.wait_for_selector('#phoneCode[disabled]')
    assert page.locator('.success-card').count() == 0, 'account activated before the alternate email was verified'
    page.fill('#alt_emailCode', code(base_url, alt, 'alt_email')); page.click("button[onclick=\"verifyCode('alt_email')\"]")
    page.wait_for_selector('.success-card')


def test_resend_code_and_the_newest_code_works(page, base_url):
    who, phone = uid('resend'); email = f'{who}@example.org'
    start_registration(page, base_url)
    fill_org_step(page, 'CRO', f'{who.title()} Analytics', phone, cats=['Bioanalytical']); page.click('#regNext'); page.wait_for_selector('#p_first')
    fill_person_step(page, email, phone); page.click('#regNext'); finish_terms(page); page.wait_for_selector('#emailCode')
    first = code(base_url, email)
    page.click("button[onclick=\"resendCode('email')\"]"); page.wait_for_selector('#toast.show'); page.wait_for_timeout(500)
    newest = code(base_url, email)
    if newest != first:  # the earlier code stops working once a new one is sent
        page.fill('#emailCode', first); page.click("button[onclick=\"verifyCode('email')\"]"); page.wait_for_timeout(600)
        assert page.locator('#emailCode[disabled]').count() == 0
    verify_codes(page, base_url, email, phone)


def test_others_specify_for_category_and_role(page, base_url):
    who, phone = uid('oth'); email = f'{who}@example.org'
    start_registration(page, base_url)
    fill_org_step(page, 'Sponsor', f'{who.title()} Wellness', phone, cats=['Others'])
    assert page.is_visible('#o_cat_other'); page.click('#regNext'); page.wait_for_timeout(400)
    assert page.locator('#p_first').count() == 0, 'continued without describing "Others"'
    page.fill('#o_cat_other', 'Nutraceutical'); page.click('#regNext'); page.wait_for_selector('#p_first')
    fill_person_step(page, email, phone); page.click('#regNext'); finish_terms(page); verify_codes(page, base_url, email, phone)
    login(page, base_url, email, expect='.dash-top h2'); assert 'Nutraceutical' in page.inner_text('.dash-body')
    page.click('text=+ Invite Organization Members'); page.wait_for_selector('#m_role')
    page.fill('#m_full_name', 'Dee Manager'); page.fill('#m_email', f'{who}.dee@example.org'); page.select_option('#m_role', 'Others')
    page.fill('#m_role_other', 'Data Manager'); page.click('#modalSubmit'); page.wait_for_selector('#modalResult code')
    page.click('.modal >> text=Cancel'); tab(page, 'Invitations')
    assert any('Others: Data Manager' in r for r in rows(page))


def test_workspace_switcher_changes_organization(page, base_url):
    a, pa = uid('swa'); b, pb = uid('swb')
    api_org(base_url, 'Sponsor', f'{a.title()} Pharma', f'{a}@example.org', pa); api_org(base_url, 'SMO', f'{b.title()} Sites', f'{b}@example.org', pb)
    owner = api_session(base_url, f'{b}@example.org')
    tok = owner.post('/api/invitations', json={'org_id': owner.org, 'kind': 'member', 'role': 'Org Admin', 'full_name': 'A', 'email': f'{a}@example.org'}).json()['dev_invite_token']
    api_session(base_url, f'{a}@example.org').post(f'/api/invitation/{tok}/respond', json={'decision': 'accept'})
    login(page, base_url, f'{a}@example.org', expect='.ws-option'); page.locator('.ws-option', has_text=f'{a.title()} Pharma').click()
    page.wait_for_selector('.dash-top h2'); assert page.inner_text('.dash-top h2') == f'{a.title()} Pharma'
    value = page.locator('select.org-switch option', has_text=f'{b.title()} Sites').get_attribute('value')
    page.select_option('select.org-switch', value); page.wait_for_function(f"document.querySelector('.dash-top h2').innerText === '{b.title()} Sites'")
    assert 'SMO WORKSPACE' in page.inner_text('.dash-top .overline').upper()


def test_pi_invite_needs_an_active_hospital_first(page, base_url):
    who, ph = uid('nohosp'); api_org(base_url, 'SMO', f'{who.title()} Sites', f'{who}@example.org', ph)
    login(page, base_url, f'{who}@example.org', expect='.dash-top h2'); page.click('text=+ Invite affiliated PI'); page.wait_for_selector('#m_hospital_id')
    assert page.locator('#m_hospital_id option').count() == 1 and 'Add a hospital with an active affiliation first' in page.inner_text('.modal')


def test_dashboard_fits_a_phone_screen(browser, base_url):
    who, ph = uid('phone'); api_org(base_url, 'Site / Hospital / Institution', f'{who.title()} Hospital', f'{who}@example.org', ph)
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}); pg = ctx.new_page()
    login(pg, base_url, f'{who}@example.org', expect='.dash-top h2'); pg.wait_for_timeout(500)
    assert no_horizontal_scroll(pg); ctx.close()


def test_mtb_admin_delete_person_and_organization(page, base_url):
    try: api_org(base_url, 'Sponsor', 'Platform Admin Office', ADMIN_EMAIL, '9100000001')
    except AssertionError: pass
    v, pv = uid('del'); org = f'{v.title()} Removable'
    api_org(base_url, 'CRO', org, f'{v}@example.org', pv)
    login(page, base_url, ADMIN_EMAIL, expect='.admin-console, .dash-top h2')
    if page.locator('.admin-console').count() == 0: page.click('header >> text=MTB Admin')
    tab(page, 'People'); page.fill('.admin-filters input[name=q]', f'{v}@example.org'); page.click('.admin-filters >> text=Search'); page.wait_for_timeout(600)
    page.once('dialog', lambda d: d.accept()); page.select_option('select.manage', 'delete')
    page.wait_for_selector('#toast.show'); assert 'only admin' in page.inner_text('#toast')  # protected while they are the only admin
    tab(page, 'Organizations'); page.fill('.admin-filters input[name=q]', org); page.click('.admin-filters >> text=Search'); page.wait_for_timeout(600)
    page.once('dialog', lambda d: d.accept(org)); page.select_option('select.manage', 'delete'); page.wait_for_timeout(1200)
    assert not [r for r in rows(page) if org in r]
    tab(page, 'People'); page.fill('.admin-filters input[name=q]', f'{v}@example.org'); page.click('.admin-filters >> text=Search'); page.wait_for_timeout(600)
    page.once('dialog', lambda d: d.accept()); page.select_option('select.manage', 'delete'); page.wait_for_timeout(1200)
    page.fill('.admin-filters input[name=q]', f'{v}@example.org'); page.click('.admin-filters >> text=Search'); page.wait_for_timeout(600)
    assert 'People (0)' in page.inner_text('.dash-body')
    assert httpx_login(base_url, f'{v}@example.org') == 401


def httpx_login(base, email):
    import httpx
    return httpx.post(base + '/api/login', json={'email': email, 'password': PW}).status_code
