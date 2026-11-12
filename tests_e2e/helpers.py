"""Shared steps for the browser tests: driving screens like a user, plus fast API set-up for preconditions."""
import itertools, re, time
import httpx

PW = 'Complex!123'
_n = itertools.count(1)


def uid(prefix):
    """Unique, readable test data per call (emails, names, phone numbers)."""
    n = next(_n)
    return f'{prefix}{n}', f'90{int(time.time()) % 10_000_000:07d}{n % 10}'


def code(base, target, kind='email'):
    for _ in range(40):
        msgs = httpx.get(base + '/api/dev/outbox').json()['messages']
        m = next((m for m in msgs if m['target'] == target and m['kind'] == kind), None)
        if m: return re.search(r'\d{6}', m['body']).group()
        time.sleep(0.25)
    raise AssertionError(f'No {kind} code for {target}')


def outbox(base, target):
    return [m['body'] for m in httpx.get(base + '/api/dev/outbox').json()['messages'] if m['target'] == target]


# ---------- fast preconditions through the API ----------
CATS = {'Sponsor': ['Pharmaceutical'], 'CRO': 'Clinical Trials', 'SMO': None, 'Site / Hospital / Institution': 'Private'}


def api_org(base, typ, name, email, phone, city='Hyderabad', pin='500034', website=''):
    c = httpx.Client(base_url=base)
    p = {'organization': {'type': typ, 'name': name, 'subtypes': CATS[typ], 'address1': '1 Test Road', 'city': city, 'state': 'Telangana', 'country': 'India', 'pin': pin, 'website': website},
         'person': {'first': 'Test', 'last': name.split()[0], 'salutation': 'Dr.', 'gender': 'Other', 'email': email, 'phone': phone, 'password': PW, 'confirm': PW},
         'authorized': True, 'accurate': True, 'terms': True, 'captcha_expected': '7', 'captcha_answer': '7'}
    r = c.post('/api/register', json=p); assert r.status_code == 200, r.text
    rid = r.json()['registration_id']
    for ch, t in [('email', email), ('phone', phone)]:
        assert c.post('/api/verify-registration', json={'registration_id': rid, 'channel': ch, 'code': code(base, t, ch)}).status_code == 200


def api_session(base, email):
    c = httpx.Client(base_url=base)
    r = c.post('/api/login', json={'email': email, 'password': PW}); assert r.status_code == 200, r.text
    c.headers['x-csrf-token'] = r.json()['csrf']
    c.org = c.get('/api/me').json()['memberships'][0]['org_id'] if c.get('/api/me').json()['memberships'] else None
    return c


# ---------- driving the screens ----------
def home(page, base):
    page.goto(base + '/'); page.wait_for_selector('.hero, .dash-top, .ws-option, .admin-console')
    if page.locator('header >> text=Log out').count():
        page.evaluate('logout()'); page.wait_for_selector('#login_email')
        page.evaluate("go('home')"); page.wait_for_selector('.hero')


def login(page, base, email, password=PW, expect='.dash-top h2, .ws-option, .admin-console, #invitationInfo'):
    home(page, base); page.evaluate("go('login')")
    page.fill('#login_email', email); page.fill('#login_password', password); page.dispatch_event('#login_password', 'input')
    page.click('#loginBtn')
    page.wait_for_selector((expect + ', ' if expect else '') + '.alert, #login_captcha')
    if page.locator('#login_captcha').count() and not (expect and page.locator(expect).count()):
        # After an earlier failed attempt the login asks for the security check (BRD 10.3.1).
        page.fill('#login_password', password); page.dispatch_event('#login_password', 'input')
        page.fill('#login_captcha', str(page.evaluate('loginCaptcha.a + loginCaptcha.b'))); page.click('#loginBtn')
    if expect: page.wait_for_selector(expect)
    if page.evaluate('!!state.me'): dismiss_profile_reminder(page)


def dismiss_profile_reminder(page, keep=False):
    """After sign-in a pop-up says the profile is not complete yet. Most tests close it and carry on."""
    page.wait_for_function("state.pf.nudge === 'done'")
    if not keep and page.locator('.pf-nudge').count(): page.locator('.modal-back', has=page.locator('.pf-nudge')).locator('button', has_text='Later').click()


def fill_org_step(page, typ, name, phone, cats=None, city='Hyderabad'):
    page.select_option('#o_type', typ)
    for cat in (cats or []): page.locator('#categoryRow label.chip', has_text=cat).first.click()
    for f, v in {'o_name': name, 'o_address1': '12 Main Road', 'o_city': city, 'o_state': 'Telangana', 'o_pin': '500034', 'o_phone': phone}.items():
        page.fill('#' + f, v)
    if not page.input_value('#o_country'): page.fill('#o_country', 'India')


def fill_person_step(page, email, phone, password=PW, confirm=None):
    page.select_option('#p_salutation', 'Dr.'); page.select_option('#p_gender', 'Other')
    for f, v in {'p_first': 'Asha', 'p_last': 'Tester', 'p_designation': 'Director', 'p_email': email, 'p_phone': phone, 'p_password': password, 'p_confirm': confirm or password}.items():
        page.fill('#' + f, v)
    page.dispatch_event('#p_confirm', 'input')


def start_registration(page, base):
    home(page, base)
    page.click('.hero-actions >> text=Register Organization'); page.click('[data-close]')
    page.wait_for_selector('#o_type')


def finish_terms(page):
    page.wait_for_selector('#terms')
    for box in ('#authorized', '#accurate', '#terms'): page.check(box)
    page.fill('#captcha', str(page.evaluate('captchaA + captchaB')))
    page.click('#regNext')


def verify_codes(page, base, email, phone):
    page.wait_for_selector('#emailCode')
    page.fill('#emailCode', code(base, email, 'email')); page.click("button[onclick=\"verifyCode('email')\"]")
    page.wait_for_selector('#emailCode[disabled]')
    page.fill('#phoneCode', code(base, phone, 'phone')); page.click("button[onclick=\"verifyCode('phone')\"]")
    page.wait_for_selector('.success-card')


def register_ui(page, base, typ, name, email, phone, cats=None):
    start_registration(page, base)
    fill_org_step(page, typ, name, phone, cats); page.click('#regNext')
    page.wait_for_selector('#p_first'); fill_person_step(page, email, phone); page.click('#regNext')
    finish_terms(page); verify_codes(page, base, email, phone)


def rows(page):
    return [r.inner_text() for r in page.locator('table tbody tr').all()]


def tab(page, label):
    page.locator('.side-link', has_text=label).first.click(); page.wait_for_timeout(250)


def no_horizontal_scroll(page):
    return page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
