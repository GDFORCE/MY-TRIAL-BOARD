"""My Profile in the browser: reminder after sign-in, CV auto-fill with review, entries, e-signature, export, team view."""
import io
from helpers import uid, api_org, login, dismiss_profile_reminder, PW, no_horizontal_scroll


def make_pdf(path):
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path)); c.drawString(72, 760, 'Dr. Asha Tester - Curriculum Vitae'); c.save()


def test_profile_from_cv_to_signed_declaration_and_export(page, base_url, ai, tmp_path):
    who, phone = uid('prof')
    email = f'{who}@example.org'
    api_org(base_url, 'Site / Hospital / Institution', f'{who.title()} Heart', email, phone)
    login(page, base_url, email)   # the helper closes the reminder pop-up; open it again to check it
    page.evaluate('profileNudge()'); page.wait_for_selector('.pf-nudge')
    assert 'not complete yet' in page.inner_text('.modal-back')
    page.click('text=Complete my profile'); page.wait_for_selector('.pf-steps')
    assert page.locator('.pf-pill').count() == 16 and 'Clinical Trial' not in page.inner_text('.pf-steps')
    # CV auto-fill: preview first, nothing saved until confirmed.
    pdf = tmp_path / 'cv.pdf'; make_pdf(pdf)
    page.click('#cvUploadBtn'); page.set_input_files('#cvFile', str(pdf)); page.click('#cvGo')
    page.wait_for_selector('.pf-reading'); page.wait_for_selector('.pf-review', timeout=30000)
    assert any(r['body']['text']['format']['name'] == 'cv_profile' for r in ai.requests)
    assert page.locator('.rv-locked').count() == 1                      # registered name is never changed by a CV
    assert page.evaluate("PF.data.entries.education.length") == 0       # not saved yet
    page.click('#rvSave'); page.wait_for_selector('.pf-steps')
    assert page.evaluate("PF.data.entries.education.length") == 2       # the third degree lacked a type and stays out
    # Manual entry with duplicate warning.
    page.evaluate("pfGoKey('education')"); page.click('#pfAdd'); page.wait_for_selector('#entryForm')
    page.select_option('#e_degree_type', 'Master'); page.fill('#e_degree_name', 'md general medicine'); page.fill('#e_institution', "Osmania Medical College")
    page.click('#entrySave'); page.wait_for_selector('text=Possible duplicate')
    page.locator('.modal-back').last.locator('text=Cancel').click(); page.locator('#entryForm [data-close]').first.click()   # close the warning, then the form
    # Declaration: e-signature needs the exact name and the password.
    page.evaluate("pfGoKey('declaration')"); page.wait_for_selector('#declForm')
    page.check('#d_agree'); page.fill('#d_name', 'Wrong Name'); page.fill('#d_pw', PW); page.click('#declBtn')
    page.wait_for_selector('#declBtn:not(.busy)'); assert page.evaluate("!PF.data.declaration.signed_at")
    page.fill('#d_name', page.evaluate("[PF.data.user.first,PF.data.user.middle,PF.data.user.last].filter(Boolean).join(' ')")); page.click('#declBtn')
    page.wait_for_selector('.pf-signed'); assert page.evaluate("!!PF.data.declaration.signed_at")
    # Export: preview, PDF and Word.
    page.click('#cvExportBtn'); page.wait_for_selector('.cvp')
    with page.expect_download() as d: page.click('#exPdf')
    assert d.value.suggested_filename.endswith('.pdf')
    with page.expect_download() as d: page.click('#exDocx')
    assert d.value.suggested_filename.endswith('.docx')
    page.click('.modal-back [data-close]')
    # Team view shows the professional part only.
    page.evaluate("state.tab='team';openDashboard()"); page.wait_for_selector('.pf-person'); page.click('.pf-person'); page.wait_for_selector('.pf-person-page')
    text = page.inner_text('.pf-person-page')
    assert 'Education Details' in text and email not in text and 'TSMC/FMR' not in text
    page.set_viewport_size({'width': 390, 'height': 800}); page.evaluate("openProfile('work')"); page.wait_for_selector('#pfAdd')
    assert no_horizontal_scroll(page)
