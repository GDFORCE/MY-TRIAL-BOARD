"""Registration (BRD 2-9, 20.1), sign-in, lockout and unlock (10, 11), recovery, logout, workspaces."""
import pytest
from helpers import (PW, uid, code, api_org, api_session, home, login, start_registration, fill_org_step, fill_person_step,
                     finish_terms, verify_codes, register_ui, no_horizontal_scroll)


@pytest.mark.parametrize('typ,cats', [('Sponsor', ['Pharmaceutical', 'Medical Device']), ('CRO', ['Clinical Trials']), ('SMO', []), ('Site / Hospital / Institution', ['Trust'])])
def test_register_each_organization_type_end_to_end(page, base_url, typ, cats):
    who, phone = uid('reg')
    name = f'{who.title()} {typ.split()[0]}'  # two words: three-word names can share initials and trigger the duplicate check
    register_ui(page, base_url, typ, name, f'{who}@example.org', phone, cats)
    page.click('.success-card >> text=Login')
    page.fill('#login_email', f'{who}@example.org'); page.fill('#login_password', PW); page.dispatch_event('#login_password', 'input'); page.click('#loginBtn')
    page.wait_for_selector('.dash-top h2')
    assert page.inner_text('.dash-top h2') == name
    assert typ.upper().split()[0] in page.inner_text('.dash-top .overline').upper()


def test_registration_blocks_bad_input_at_each_step(page, base_url):
    start_registration(page, base_url)
    page.click('#regNext')  # nothing filled in
    assert page.locator('#p_first').count() == 0 and page.evaluate("document.querySelectorAll('#registrationForm :invalid').length") > 0
    page.select_option('#o_type', 'Sponsor')  # Sponsor needs at least one category
    who, phone = uid('bad')
    fill_org_step(page, 'Sponsor', f'{who.title()} Pharma', phone, cats=[])
    page.click('#regNext'); page.wait_for_timeout(400)
    assert page.locator('#p_first').count() == 0, 'continued without a sponsor category'
    page.locator('#categoryRow label.chip', has_text='Pharmaceutical').first.click(); page.click('#regNext')
    page.wait_for_selector('#p_first')
    fill_person_step(page, f'{who}@example.org', phone, password='weak')  # password rules
    page.click('#regNext'); page.wait_for_timeout(400)
    assert page.locator('#terms').count() == 0, 'continued with a weak password'
    fill_person_step(page, f'{who}@example.org', phone, password=PW, confirm='Different!123')  # confirmation mismatch
    page.click('#regNext'); page.wait_for_timeout(400)
    assert page.locator('#terms').count() == 0, 'continued with mismatched passwords'
    fill_person_step(page, f'{who}@example.org', phone); page.click('#regNext')
    page.wait_for_selector('#terms')
    for box in ('#authorized', '#accurate', '#terms'): page.check(box)
    page.fill('#captcha', str(page.evaluate('captchaA + captchaB') + 1))  # wrong CAPTCHA answer
    page.click('#regNext'); page.wait_for_timeout(800)
    assert page.locator('#emailCode').count() == 0, 'accepted a wrong CAPTCHA'


def test_duplicate_organization_is_stopped(page, base_url):
    who, phone = uid('dup')
    name = f'{who.title()} Research Services'
    api_org(base_url, 'CRO', name, f'{who}@example.org', phone)
    start_registration(page, base_url)
    fill_org_step(page, 'CRO', name, uid('x')[1], cats=['Clinical Trials']); page.click('#regNext')
    page.wait_for_selector('text=This organization is already on My Trial Board')
    assert page.locator('text=Request to join').count() and page.locator('text=This is my organization').count()
    assert page.locator('#p_first').count() == 0, 'registration continued for a duplicate organization'


def test_wrong_verification_code_is_refused(page, base_url):
    who, phone = uid('vc')
    start_registration(page, base_url)
    fill_org_step(page, 'SMO', f'{who.title()} Sitecare', phone); page.click('#regNext')
    page.wait_for_selector('#p_first'); fill_person_step(page, f'{who}@example.org', phone); page.click('#regNext')
    finish_terms(page); page.wait_for_selector('#emailCode')
    right = code(base_url, f'{who}@example.org')
    page.fill('#emailCode', '000000' if right != '000000' else '111111'); page.click("button[onclick=\"verifyCode('email')\"]")
    page.wait_for_selector('#toast.show'); assert 'invalid' in page.inner_text('#toast').lower()
    assert page.locator('#emailCode[disabled]').count() == 0
    verify_codes(page, base_url, f'{who}@example.org', phone)


def test_wrong_passwords_lock_then_unlock_screens_and_reset(page, base_url):
    who, phone = uid('lock'); email = f'{who}@example.org'
    api_org(base_url, 'CRO', f'{who.title()} Clinical', email, phone)
    home(page, base_url); page.evaluate("go('login')")
    page.fill('#login_email', email); page.fill('#login_password', 'Wrong!123'); page.dispatch_event('#login_password', 'input'); page.click('#loginBtn')
    page.wait_for_selector('.alert'); assert 'Warning' in page.inner_text('.alert')
    assert page.locator('#login_captcha').count() == 1, 'no CAPTCHA after the first failure'
    for expected in ('Final warning', 'locked'):
        page.fill('#login_password', 'Wrong!123'); page.dispatch_event('#login_password', 'input')
        page.fill('#login_captcha', str(page.evaluate('loginCaptcha.a + loginCaptcha.b'))); page.click('#loginBtn')
        page.wait_for_function(f"document.querySelector('.alert') && document.querySelector('.alert').innerText.includes('{expected}')")
    assert 'Account locked' in page.inner_text('.auth-card h2')
    # Unlock: one screen per step.
    page.click('#unlockBtn'); page.wait_for_selector('#unlock_code')
    page.fill('#unlock_code', code(base_url, email)); page.click('#unlockBtn')
    page.wait_for_selector('text=Account unlocked')
    page.click('text=Reset my password'); page.wait_for_selector('#recover_password')  # straight to the new password, no second code
    page.fill('#recover_password', 'Brand!New9'); page.fill('#recover_confirm', 'Brand!New9'); page.dispatch_event('#recover_confirm', 'input')
    page.click('#recoverBtn'); page.wait_for_selector('.success-card')
    page.click('text=Go to sign in'); assert page.input_value('#login_email') == email
    page.fill('#login_password', 'Brand!New9'); page.dispatch_event('#login_password', 'input'); page.click('#loginBtn')
    page.wait_for_selector('.dash-top h2')


def test_unknown_email_gets_the_same_warning(page, base_url):
    home(page, base_url); page.evaluate("go('login')")
    page.fill('#login_email', 'nobody.here@example.org'); page.fill('#login_password', 'Wrong!123'); page.dispatch_event('#login_password', 'input'); page.click('#loginBtn')
    page.wait_for_selector('.alert'); assert 'Incorrect email or password' in page.inner_text('.alert')


def test_password_recovery_is_four_separate_screens(page, base_url):
    who, phone = uid('rec'); email = f'{who}@example.org'
    api_org(base_url, 'Sponsor', f'{who.title()} Bio', email, phone)
    home(page, base_url); page.evaluate("go('login')"); page.click('text=Forgot password?')
    page.fill('#recover_email', email); page.click('#recoverBtn'); page.wait_for_selector('#recover_code')
    assert 'step 2 of 3' in page.inner_text('.recover-card').lower()
    page.fill('#recover_code', '000000'); page.click('#recoverBtn'); page.wait_for_selector('.alert')  # wrong code stays on step 2
    page.fill('#recover_code', code(base_url, email)); page.click('#recoverBtn'); page.wait_for_selector('#recover_password')
    page.fill('#recover_password', 'Another!Pass1'); page.fill('#recover_confirm', 'Mismatch!Pass1'); page.click('#recoverBtn')
    page.wait_for_timeout(300); assert page.locator('.success-card').count() == 0
    page.fill('#recover_confirm', 'Another!Pass1'); page.dispatch_event('#recover_confirm', 'input'); page.click('#recoverBtn')
    page.wait_for_selector('.success-card')
    login(page, base_url, email, 'Another!Pass1', expect='.dash-top h2')


def test_logout_and_back_button_do_not_restore_access(page, base_url):
    who, phone = uid('out'); email = f'{who}@example.org'
    api_org(base_url, 'CRO', f'{who.title()} Trials', email, phone)
    page.goto(base_url + '/health')
    login(page, base_url, email, expect='.dash-top h2')
    page.click('header >> text=Log out'); page.wait_for_selector('#login_email')
    page.go_back(); page.go_forward(); page.wait_for_timeout(800)
    assert page.locator('.dash-top').count() == 0


def test_workspace_choice_after_login_and_refresh_keeps_it(page, base_url):
    a, pa = uid('wsa'); b, pb = uid('wsb')
    api_org(base_url, 'Sponsor', f'{a.title()} Pharma', f'{a}@example.org', pa)
    api_org(base_url, 'CRO', f'{b.title()} Research', f'{b}@example.org', pb)
    owner = api_session(base_url, f'{b}@example.org')
    tok = owner.post('/api/invitations', json={'org_id': owner.org, 'kind': 'member', 'role': 'Research Team', 'full_name': 'A', 'email': f'{a}@example.org', 'designation': 'Clinical Lead'}).json()['dev_invite_token']
    api_session(base_url, f'{a}@example.org').post(f'/api/invitation/{tok}/respond', json={'decision': 'accept'})
    login(page, base_url, f'{a}@example.org', expect='.ws-option')
    assert page.locator('.ws-option').count() == 2 and 'Clinical Lead' in page.inner_text('.ws-list')
    page.locator('.ws-option', has_text=f'{b.title()} Research').click(); page.wait_for_selector('.dash-top h2')
    page.reload(); page.wait_for_selector('.dash-top h2')
    assert page.inner_text('.dash-top h2') == f'{b.title()} Research'


@pytest.mark.parametrize('route', ['home', 'login', 'register', 'recover'])
def test_public_pages_fit_a_phone_screen(browser, base_url, route):
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}); pg = ctx.new_page()
    pg.goto(base_url + '/'); pg.wait_for_selector('.hero')
    if route == 'register': pg.click('.hero-actions >> text=Register Organization'); pg.click('[data-close]')
    elif route == 'recover': pg.evaluate('startRecovery()')
    elif route == 'login': pg.evaluate("go('login')")
    pg.wait_for_timeout(500)
    assert no_horizontal_scroll(pg), f'{route} page scrolls sideways on a phone'
    ctx.close()
