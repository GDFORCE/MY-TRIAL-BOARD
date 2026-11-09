"""Member invitations (BRD 12-14): roles per organization type, new vs existing people, resend, cancel, duplicates, tabs."""
import pytest
from helpers import PW, uid, api_org, api_session, login, home, verify_codes, rows, tab, outbox, code

ROLE_OPTIONS = {'Sponsor': ['Org Admin', 'Research Team'], 'CRO': ['Org Admin', 'Research Team'],
                'SMO': ['Org Admin', 'PI', 'Research Team'], 'Site / Hospital / Institution': ['Org Admin', 'PI', 'Research Team']}


@pytest.mark.parametrize('typ', list(ROLE_OPTIONS))
def test_invite_popup_offers_the_right_roles(page, base_url, typ):
    who, phone = uid('roles'); api_org(base_url, typ, f'{who.title()} {typ.split()[0]}', f'{who}@example.org', phone)
    login(page, base_url, f'{who}@example.org', expect='.dash-top h2')
    page.click('text=+ Invite Organization Members'); page.wait_for_selector('#m_role')
    offered = [o for o in page.locator('#m_role option').all_inner_texts()[1:] if not o.startswith('Others')]
    assert offered == ROLE_OPTIONS[typ]
    # The popup sits above the top bar (it used to be hidden behind it).
    hit = page.evaluate("(() => { const r = document.querySelector('#modalTitle').getBoundingClientRect(); const el = document.elementFromPoint(r.left + 5, r.top + r.height / 2); return !!el.closest('.modal'); })()")
    assert hit, 'the top bar covers the popup title'


def test_new_person_gets_a_create_account_invitation_and_joins(page, base_url):
    adm, ph = uid('inva'); new, ph2 = uid('invn')
    api_org(base_url, 'CRO', f'{adm.title()} Clinical', f'{adm}@example.org', ph)
    login(page, base_url, f'{adm}@example.org', expect='.dash-top h2')
    page.click('text=+ Invite Organization Members'); page.wait_for_selector('#m_role')
    page.fill('#m_full_name', 'Nina New'); page.fill('#m_email', f'{new}@example.org'); page.fill('#m_designation', 'Study Coordinator')
    page.select_option('#m_role', 'Research Team'); page.click('#modalSubmit'); page.wait_for_selector('#modalResult code')
    link = page.inner_text('#modalResult code'); assert '#invite=' in link
    assert any('Create your account' in b for b in outbox(base_url, f'{new}@example.org'))
    page.evaluate('logout()'); page.wait_for_selector('#login_email')
    page.goto(link); page.reload(); page.wait_for_selector('text=Create your account')
    assert page.locator('text=Sign in to accept').count() == 0  # no account yet: only the sign-up path
    page.click('#invitationInfo >> text=Create your account'); page.wait_for_selector('#p_first')
    page.select_option('#p_salutation', 'Ms.'); page.select_option('#p_gender', 'Female')
    for f, v in {'p_first': 'Nina', 'p_last': 'New', 'p_phone': ph2, 'p_password': PW, 'p_confirm': PW}.items(): page.fill('#' + f, v)
    page.check('#inviteTerms'); page.click('#inviteSubmit')
    verify_codes(page, base_url, f'{new}@example.org', ph2)
    page.click('.success-card >> text=Login'); page.fill('#login_email', f'{new}@example.org'); page.fill('#login_password', PW)
    page.dispatch_event('#login_password', 'input'); page.click('#loginBtn')
    page.click('text=Accept invitation'); page.wait_for_selector('.dash-top h2')
    assert page.inner_text('.dash-top h2') == f'{adm.title()} Clinical'
    # A member who is not an admin only sees the tabs they can use.
    sidebar = page.inner_text('.sidebar')
    for hidden in ('Team members', 'Invitations', 'Audit trail'): assert hidden not in sidebar
    for shown in ('Overview', 'Hospitals / Sites', 'Affiliated PIs'): assert shown in sidebar


def test_existing_user_signs_in_and_answers_from_the_dashboard(page, base_url):
    a, pa = uid('exa'); b, pb = uid('exb')
    api_org(base_url, 'Sponsor', f'{a.title()} Therapeutics', f'{a}@example.org', pa)
    api_org(base_url, 'SMO', f'{b.title()} Sitecare', f'{b}@example.org', pb)
    owner = api_session(base_url, f'{a}@example.org')
    tok = owner.post('/api/invitations', json={'org_id': owner.org, 'kind': 'member', 'role': 'Research Team', 'full_name': 'B', 'email': f'{b}@example.org'}).json()['dev_invite_token']
    owner.post('/api/invitations', json={'org_id': owner.org, 'kind': 'member', 'role': 'Org Admin', 'full_name': 'B', 'email': f'{b}.other@example.org'})
    assert any('Sign in with this email' in m for m in outbox(base_url, f'{b}@example.org'))
    home(page, base_url); page.goto(base_url + '/#invite=' + tok); page.reload()
    page.wait_for_selector('text=You already have an MTB account')
    assert page.locator('#invitationInfo >> text=Create your account').count() == 0
    login(page, base_url, f'{b}@example.org', expect='.dash-top h2')
    page.wait_for_selector('text=Pending invitations for you')
    page.locator('.attention button', has_text='Decline').click(); page.wait_for_timeout(1200)
    assert page.locator('text=Pending invitations for you').count() == 0
    assert all(m['org_id'] != owner.org for m in api_session(base_url, f'{b}@example.org').get('/api/me').json()['memberships'])


def test_resend_cancel_and_no_duplicate_pending_invitations(page, base_url):
    adm, ph = uid('rsa')
    api_org(base_url, 'Site / Hospital / Institution', f'{adm.title()} Hospital', f'{adm}@example.org', ph)
    login(page, base_url, f'{adm}@example.org', expect='.dash-top h2')
    for attempt in range(2):
        page.click('text=+ Invite Organization Members'); page.wait_for_selector('#m_role')
        page.fill('#m_full_name', 'Pat Twice'); page.fill('#m_email', f'{adm}.twice@example.org'); page.select_option('#m_role', 'PI')
        page.click('#modalSubmit')
        if attempt == 0: page.wait_for_selector('#modalResult code'); page.click('.modal >> text=Cancel')
    page.wait_for_selector('#toast.show'); assert 'already waiting' in page.inner_text('#toast')
    page.click('.modal >> text=Cancel'); tab(page, 'Invitations')
    page.click('.row-actions >> text=Resend'); page.wait_for_selector('.dev code')
    assert '#invite=' in page.inner_text('.dev code')
    page.once('dialog', lambda d: d.accept()); page.click('.row-actions >> text=Cancel'); page.wait_for_timeout(1000)
    assert any('cancelled' in r for r in rows(page))
