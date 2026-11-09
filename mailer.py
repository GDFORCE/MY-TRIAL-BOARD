"""Email delivery through Brevo (free plan: 300 emails a day), by its API or its SMTP relay.

Settings in .env (use EITHER the API key OR the SMTP login + key; with neither, nothing is sent
and messages only reach the local test inbox):
  BREVO_API_KEY       Brevo > SMTP & API > API keys (starts with xkeysib-).
  BREVO_SMTP_LOGIN    Brevo > SMTP & API > SMTP tab: the "Login" shown there (often ...@smtp-brevo.com).
  BREVO_SMTP_KEY      Brevo > SMTP & API > SMTP tab: an SMTP key (starts with xsmtpsib-).
  MTB_MAIL_FROM       Sender address. It must be added and verified in Brevo (Senders, Domains, IPs > Senders).
  MTB_MAIL_FROM_NAME  Sender name shown in inboxes.
  MTB_APP_URL         Public address of the site, used for links in emails.
SMS is not sent from here; phone codes stay in the test inbox until an SMS provider is chosen.
"""
import html, logging, os, re, smtplib, ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
import httpx

BREVO_API = 'https://api.brevo.com/v3'
SMTP_HOST, SMTP_PORT = 'smtp-relay.brevo.com', 587
log = logging.getLogger('mtb.mail')
CODE = re.compile(r'\b(\d{6})\b')
LINK = re.compile(r'(https?://[^\s)]+)')


class MailError(Exception):
    """Brevo refused or could not be reached."""


def settings():
    return {'key': os.getenv('BREVO_API_KEY', '').strip(),
            'smtp_login': os.getenv('BREVO_SMTP_LOGIN', '').strip(), 'smtp_key': os.getenv('BREVO_SMTP_KEY', '').strip(),
            # BREVO_FROM_EMAIL / BREVO_FROM_NAME are accepted as other names for the same settings.
            'sender': (os.getenv('MTB_MAIL_FROM') or os.getenv('BREVO_FROM_EMAIL') or 'bhanodai2005@gmail.com').strip(),
            'name': (os.getenv('MTB_MAIL_FROM_NAME') or os.getenv('BREVO_FROM_NAME') or 'My Trial Board').strip(),
            'app_url': os.getenv('MTB_APP_URL', 'http://127.0.0.1:8000').strip().rstrip('/')}


def mode():
    """'api', 'smtp' or '' (not set up). The API key wins when both are present."""
    s = settings()
    return 'api' if s['key'] else 'smtp' if s['smtp_login'] and s['smtp_key'] else ''


def enabled():
    return bool(mode())


# Addresses reserved for examples and tests (RFC 2606 / 6761) can never receive mail; skipping them saves the daily allowance.
TEST_DOMAINS = ('example.com', 'example.org', 'example.net')
TEST_ENDINGS = ('.example', '.invalid', '.test', '.localhost')


def undeliverable(address):
    domain = address.rsplit('@', 1)[-1].lower().strip()
    return domain in TEST_DOMAINS or domain.endswith(TEST_ENDINGS) or any(domain.endswith('.' + d) for d in TEST_DOMAINS)


def app_url():
    return settings()['app_url']


def render(subject, body):
    """Plain-text and branded HTML versions. A 6-digit code is shown large; a link becomes a button."""
    footer = "You received this email because of activity on your My Trial Board account. If this wasn't you, you can ignore it."
    text = f'{body}\n\n— My Trial Board\n{footer}'
    link = LINK.search(body)
    code = CODE.search(LINK.sub('', body))
    words = LINK.sub('', body).replace(' : ', ': ').strip().rstrip(':').strip()
    para = html.escape(words)
    if code:
        para = para.replace(code.group(1), f'<b>{code.group(1)}</b>')
    code_block = (f'<div style="font-size:30px;letter-spacing:8px;font-weight:800;color:#14213D;background:#F4EDE0;'
                  f'border-radius:12px;padding:16px 0;text-align:center;margin:22px 0">{code.group(1)}</div>') if code else ''
    button = (f'<p style="margin:26px 0 10px"><a href="{html.escape(link.group(1))}" style="background:#FF685B;color:#ffffff;'
              f'text-decoration:none;font-weight:700;padding:13px 24px;border-radius:10px;display:inline-block">Open My Trial Board</a></p>'
              f'<p style="font-size:12px;color:#748093;word-break:break-all;margin:0">Or copy this link into your browser:<br>{html.escape(link.group(1))}</p>') if link else ''
    page = f'''<!doctype html><html><body style="margin:0;background:#f8f7f4;font-family:Arial,Helvetica,sans-serif;color:#152540">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f8f7f4;padding:28px 12px"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border-radius:16px;border:1px solid #e8e9ed">
<tr><td style="padding:22px 28px;border-bottom:1px solid #e8e9ed;font-size:19px;font-weight:800;color:#14213D">&#10035; my trial board<span style="color:#FF685B">.</span></td></tr>
<tr><td style="padding:28px">
<h1 style="font-size:21px;margin:0 0 14px;color:#14213D">{html.escape(subject)}</h1>
<p style="font-size:15px;line-height:1.7;margin:0">{para}</p>{code_block}{button}
</td></tr>
<tr><td style="padding:18px 28px;border-top:1px solid #e8e9ed;font-size:12px;line-height:1.6;color:#748093">{html.escape(footer)}</td></tr>
</table></td></tr></table></body></html>'''
    return page, text


def send(to, subject, body, tag='mtb'):
    """Send one email. Returns Brevo's message id; raises MailError on any failure."""
    s = settings()
    if not mode():
        raise MailError('Email delivery is not configured (no Brevo API key or SMTP login/key)')
    page, text = render(subject, body)
    if mode() == 'smtp':
        return _send_smtp(s, to, subject, page, text, tag)
    try:
        r = httpx.post(f'{BREVO_API}/smtp/email', timeout=10,
                       headers={'api-key': s['key'], 'accept': 'application/json', 'content-type': 'application/json'},
                       json={'sender': {'name': s['name'], 'email': s['sender']}, 'to': [{'email': to}], 'subject': subject,
                             'htmlContent': page, 'textContent': text, 'tags': [tag]})
    except httpx.HTTPError as e:
        raise MailError(f'Could not reach Brevo: {e.__class__.__name__}') from None
    if r.status_code != 201:
        try:
            detail = r.json().get('message') or r.text
        except ValueError:
            detail = r.text
        raise MailError(f'Brevo refused the email ({r.status_code}): {str(detail)[:200]}')
    return r.json().get('messageId', '')


def _smtp_connect(s):
    smtp = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15)
    smtp.starttls(context=ssl.create_default_context())
    smtp.login(s['smtp_login'], s['smtp_key'])
    return smtp


def _send_smtp(s, to, subject, page, text, tag):
    msg = EmailMessage()
    msg['Subject'], msg['From'], msg['To'] = subject, formataddr((s['name'], s['sender'])), to
    msg['Message-ID'] = make_msgid(domain='mytrialboard.local')
    msg['X-Mailin-Tag'] = tag  # Brevo shows this tag in its logs
    msg.set_content(text)
    msg.add_alternative(page, subtype='html')
    try:
        with _smtp_connect(s) as smtp:
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise MailError('Brevo did not accept the SMTP login or key') from None
    except smtplib.SMTPRecipientsRefused:
        raise MailError(f'Brevo refused the recipient {to}') from None
    except smtplib.SMTPSenderRefused as e:
        raise MailError(f'Brevo refused the sender {s["sender"]} (is it verified in Brevo?): {e.smtp_error[:150]!r}') from None
    except (smtplib.SMTPException, OSError) as e:
        raise MailError(f'Could not send through Brevo SMTP: {e.__class__.__name__}') from None
    return msg['Message-ID']


def account_status():
    """Checks the key without sending anything: Brevo account email and plan, or the error."""
    s = settings()
    out = {'configured': enabled(), 'mode': mode(), 'sender': s['sender'], 'sender_name': s['name'], 'app_url': s['app_url'], 'ok': False}
    if not enabled():
        return {**out, 'error': 'Add BREVO_API_KEY (or BREVO_SMTP_LOGIN and BREVO_SMTP_KEY) to .env and restart the site.'}
    if mode() == 'smtp':  # signs in to the relay without sending anything
        try:
            with _smtp_connect(s):
                pass
            return {**out, 'ok': True, 'account_email': s['smtp_login'], 'plan': 'SMTP relay'}
        except smtplib.SMTPAuthenticationError:
            return {**out, 'error': 'Brevo did not accept the SMTP login or key.'}
        except (smtplib.SMTPException, OSError) as e:
            return {**out, 'error': f'Could not reach Brevo SMTP: {e.__class__.__name__}'}
    try:
        r = httpx.get(f'{BREVO_API}/account', timeout=10, headers={'api-key': s['key'], 'accept': 'application/json'})
    except httpx.HTTPError as e:
        return {**out, 'error': f'Could not reach Brevo: {e.__class__.__name__}'}
    if r.status_code != 200:
        try:
            msg = r.json().get('message') or r.text
        except ValueError:
            msg = r.text
        return {**out, 'error': f'Brevo said ({r.status_code}): {str(msg)[:200]}'}
    a = r.json()
    plans = ', '.join(f"{p.get('type', '')}" + (f" ({p.get('credits')} credits)" if p.get('credits') is not None else '') for p in a.get('plan', []))
    return {**out, 'ok': True, 'account_email': a.get('email'), 'company': a.get('companyName'), 'plan': plans}
