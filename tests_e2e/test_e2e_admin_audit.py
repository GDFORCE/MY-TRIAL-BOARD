"""Organization audit trail (BRD 18) and the MTB Admin console (BRD 15, 19)."""
import httpx
from conftest import ADMIN_EMAIL
from helpers import PW, uid, api_org, api_session, login, rows, tab


def test_org_admin_audit_trail_filters_and_csv(page, base_url):
    who, ph = uid('aud')
    api_org(base_url, 'CRO', f'{who.title()} Audits', f'{who}@example.org', ph)
    httpx.post(base_url + '/api/login', json={'email': f'{who}@example.org', 'password': 'Wrong!123'})  # a failed sign-in to find
    login(page, base_url, f'{who}@example.org', expect='.dash-top h2'); tab(page, 'Audit trail'); page.wait_for_selector('.chip-bar')
    events = ' '.join(rows(page))
    for expected in ('Organization registration submitted', 'Email verified', 'Account activated', 'Sign-in failed', 'Signed in'):
        assert expected in events, expected
    page.locator('.chip-btn', has_text='Sign-in & security').click(); page.wait_for_timeout(300)
    assert all('Sign-in & security' in r for r in rows(page))
    with page.expect_download() as d: page.click('text=Download CSV')
    path = d.value.path(); text = open(path, encoding='utf-8').read()
    assert text.startswith('"When","Who"') and 'Signed in' in text


def test_mtb_admin_console_block_people_and_organizations(page, base_url):
    try: api_org(base_url, 'Sponsor', 'Platform Admin Office', ADMIN_EMAIL, '9100000001')
    except AssertionError: pass  # already created by an earlier run in this session
    v, pv = uid('vic'); api_org(base_url, 'CRO', f'{v.title()} Blockable', f'{v}@example.org', pv)
    api_org(base_url, 'CRO', f'{v.title()} Twin', f'{v}.twin@example.org', pv)  # same phone, different email
    login(page, base_url, ADMIN_EMAIL, expect='.admin-console, .dash-top h2')
    if page.locator('.admin-console').count() == 0: page.click('header >> text=MTB Admin')
    page.wait_for_selector('.integrity'); assert 'Audit log intact' in page.inner_text('.integrity')
    dupes = page.inner_text('text=Possible duplicate people >> xpath=..')
    assert f'{v}@example.org' in dupes and f'{v}.twin@example.org' in dupes
    # Block a person: they cannot sign in.
    tab(page, 'People'); page.fill('.admin-filters input[name=q]', f'{v}@example.org'); page.click('.admin-filters >> text=Search'); page.wait_for_timeout(600)
    page.once('dialog', lambda d: d.accept()); page.select_option('select.manage', 'block'); page.wait_for_timeout(900)
    assert any('blocked' in r for r in rows(page))
    r = httpx.post(base_url + '/api/login', json={'email': f'{v}@example.org', 'password': PW}); assert r.status_code == 403 and 'suspended' in r.json()['detail']
    page.select_option('select.manage', 'unblock'); page.wait_for_timeout(900)
    assert httpx.post(base_url + '/api/login', json={'email': f'{v}@example.org', 'password': PW}).status_code == 200
    # Block an organization: its members lose that workspace.
    tab(page, 'Organizations'); page.fill('.admin-filters input[name=q]', f'{v.title()} Blockable'); page.click('.admin-filters >> text=Search'); page.wait_for_timeout(600)
    page.once('dialog', lambda d: d.accept()); page.select_option('select.manage', 'block'); page.wait_for_timeout(900)
    assert api_session(base_url, f'{v}@example.org').get('/api/me').json()['memberships'] == []
    tab(page, 'Activity log'); page.wait_for_selector('text=Activity (')
    assert 'MTB admin: org block' in page.inner_text('.dash-body')

