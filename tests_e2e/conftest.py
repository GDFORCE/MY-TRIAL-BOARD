"""Browser end-to-end tests (Playwright).

Run:  pytest tests_e2e            (needs: pip install -r requirements-e2e.txt)
Watch: set MTB_E2E_HEADED=1 and MTB_E2E_SLOWMO=300 to see the tests click through a visible Chrome window.
Each run starts its own copy of the site on a free port with an empty, temporary database,
so real data is never touched. Uses the installed Google Chrome; set MTB_E2E_BROWSER=chromium
to use Playwright's own Chromium instead (after `playwright install chromium`).
"""
import os, sys, socket, subprocess, tempfile, time
from pathlib import Path
import httpx, pytest
from playwright.sync_api import sync_playwright
import fake_openai

APP_DIR = Path(__file__).resolve().parents[1]
ADMIN_EMAIL = 'e2e.admin@example.org'


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); return s.getsockname()[1]


@pytest.fixture(scope='session')
def ai():
    """Stand-in for the OpenAI API (see fake_openai.py): CV auto-fill is tested without calling the real service."""
    server = fake_openai.start()
    yield server
    server.shutdown()


@pytest.fixture(scope='session')
def base_url(ai):
    tmp = Path(tempfile.mkdtemp(prefix='mtb-e2e-'))
    port = free_port()
    env = {**os.environ, 'MTB_DB': str(tmp / 'e2e.sqlite3'), 'MTB_UPLOADS': str(tmp / 'uploads'), 'MTB_DEV_MODE': '1',
           'MTB_SECRET': 'e2e-only-secret-0123456789abcdef0123456789', 'MTB_GOOGLE_MAPS_KEY': '', 'MTB_ADMIN_EMAILS': ADMIN_EMAIL,
           'MTB_FORCE_HTTPS': '0', 'BREVO_API_KEY': '', 'BREVO_SMTP_KEY': '', 'BREVO_SMTP_LOGIN': '', 'MTB_PHONE_CODE_ON_SCREEN': '0',  # never sends real email
           'OPENAI_API_KEY': 'sk-e2e-stub', 'OPENAI_BASE_URL': ai.url, 'MTB_OPENAI_MODEL': 'e2e-model'}   # never calls the real AI service
    log = open(tmp / 'server.log', 'w')
    proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', str(port)], cwd=APP_DIR, env=env, stdout=log, stderr=subprocess.STDOUT)
    url = f'http://127.0.0.1:{port}'
    for _ in range(100):
        try:
            if httpx.get(url + '/health', timeout=1).status_code == 200: break
        except Exception: pass
        time.sleep(0.2)
    else:
        proc.kill(); raise RuntimeError('Test server did not start; see ' + str(tmp / 'server.log'))
    yield url
    proc.terminate(); proc.wait(10); log.close()


@pytest.fixture(scope='session')
def browser():
    with sync_playwright() as p:
        kind = os.getenv('MTB_E2E_BROWSER', 'chrome')
        # Watch the tests: MTB_E2E_HEADED=1 opens a visible window; MTB_E2E_SLOWMO=300 waits 300 ms between actions.
        opts = {'headless': os.getenv('MTB_E2E_HEADED', '0') != '1', 'slow_mo': int(os.getenv('MTB_E2E_SLOWMO', '0'))}
        b = p.chromium.launch(channel='chrome', **opts) if kind == 'chrome' else p.chromium.launch(**opts)
        yield b
        b.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, 'rep_' + rep.when, rep)


@pytest.fixture
def page(request, browser, base_url):
    ctx = browser.new_context(viewport={'width': 1300, 'height': 950}, accept_downloads=True)
    pg = ctx.new_page()
    pg.errors = []
    pg.on('pageerror', lambda e: pg.errors.append(str(e)))
    pg.set_default_timeout(15000)
    yield pg
    if getattr(request.node, 'rep_call', None) and request.node.rep_call.failed:
        shots = APP_DIR / 'tests_e2e' / 'failures'; shots.mkdir(exist_ok=True)
        pg.screenshot(path=str(shots / (request.node.name.replace('/', '_')[:120] + '.png')), full_page=True)
    errors = pg.errors
    ctx.close()
    assert not errors, f'JavaScript errors on the page: {errors}'
