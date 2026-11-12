"""A stand-in for the OpenAI Responses API, so the browser tests never call the real service or spend credit.

It answers POST /responses the way the real API does for structured output. The CV answer below is fixed;
the "About" rewrite answer is a fixed sentence. Every request body is kept in `requests` for the tests to inspect.
"""
import json, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CV = {
    'is_cv': True,
    'basic': {'first_name': 'Asha', 'middle_name': None, 'last_name': 'Tester', 'email': 'asha.personal@example.net', 'phone': '+91 98480 22338',
              'designation': 'Senior Consultant Cardiologist', 'department': 'Cardiology', 'address_line1': '14 Lake View Road', 'address_line2': 'Banjara Hills',
              'city': 'Hyderabad', 'state': 'Telangana', 'country': 'India', 'postal_code': '500034', 'salutation': 'Dr.', 'gender': None,
              'languages': ['English', 'Telugu', 'Hindi'], 'research_roles': ['PI', 'Co-I']},
    'about': {'text': 'Consultant cardiologist with 12 years of clinical research experience as Principal Investigator and Co-Investigator in phase II to IV cardiovascular trials. '
                      'Experienced in site set-up, GCP-compliant conduct and regulatory inspections.', 'drafted': False},
    'trial_expertise': ['Randomized Controlled', 'Placebo-controlled', 'Multi-Regional'],
    'tech_expertise': ['EDC', 'eConsent'],
    'education': [
        {'degree_type': 'Super Speciality', 'degree_name': 'DM Cardiology', 'institution': 'Nizam\'s Institute of Medical Sciences', 'specialization': 'Cardiology', 'completed_year': '2012'},
        {'degree_type': 'Master', 'degree_name': 'MD General Medicine', 'institution': 'Osmania Medical College', 'specialization': 'Internal Medicine', 'completed_year': '2008'},
        {'degree_type': None, 'degree_name': 'MBBS', 'institution': 'Gandhi Medical College', 'specialization': None, 'completed_year': '2004'}],
    'license': [{'license_type': 'Medical Council Registration', 'issuer': 'Telangana State Medical Council', 'number': 'TSMC/FMR/04512', 'region': 'Telangana', 'issue_date': '2005-03', 'expiry_date': '2030-03'}],
    'place_of_work': [{'org_type': 'Site', 'org_name': 'Lakeside Heart Institute', 'department': 'Cardiology', 'designation': 'Senior Consultant Cardiologist', 'research_roles': ['PI'], 'status': 'Current', 'date_of_joining': '2016-07'}],
    'training': [{'title': 'GCP', 'date': '2024-02-10', 'issued_by': 'CITI', 'status': 'Completed'},
                 {'title': 'BLS', 'date': '2023-08', 'issued_by': 'American Heart Association', 'status': 'Completed'}],
    'certification': [{'name': 'ACRP Certified Principal Investigator (ACRP-CPI)', 'issuing_org': 'ACRP', 'number': 'CPI-20931', 'issue_date': '2019-05', 'valid_until': '2027-05'}],
    'publication': [{'name': 'Early high-intensity statin therapy after acute coronary syndrome: a multicentre Indian registry', 'therapeutic_area': 'Cardiology', 'source': 'Indian Heart Journal', 'date_published': '2021-08', 'weblink': 'https://doi.org/10.1016/example'},
                    {'name': 'Outcomes of primary PCI in octogenarians', 'therapeutic_area': 'Cardiology', 'source': 'Journal of the Association of Physicians of India', 'date_published': '2018', 'weblink': None}],
    'audit': [{'regulatory_body': 'CDSCO', 'scope': 'I took part personally', 'organization': 'Lakeside Heart Institute', 'date': '2022-11-14', 'outcome': 'No critical findings'}],
    'work': [{'org_name': 'Lakeside Heart Institute', 'org_address': 'Hyderabad, Telangana', 'job_title': 'Senior Consultant Cardiologist', 'start': '2016-07', 'end': None, 'current': True, 'description': 'Leads the cardiology research unit. Principal Investigator for 9 industry-sponsored trials.'},
             {'org_name': 'City General Hospital', 'org_address': 'Hyderabad', 'job_title': 'Consultant Cardiologist', 'start': '2012-08', 'end': '2016-06', 'current': False, 'description': None}],
    'membership': [{'association': 'Cardiological Society of India', 'type': 'Life member', 'number': 'L-8841', 'start_date': '2013', 'valid_until': None}],
    'award': [{'name': 'Best Investigator Award', 'issued_by': 'Indian Society for Clinical Research', 'year': '2022'}],
}
REWRITE = 'Consultant cardiologist with 12 years of experience leading cardiovascular trials as a Principal Investigator.'


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
        self.server.requests.append({'path': self.path, 'auth': self.headers.get('Authorization'), 'body': body})
        if not self.path.endswith('/responses'):
            return self.reply(404, {'error': {'message': 'not found'}})
        name = body.get('text', {}).get('format', {}).get('name')
        if name == 'cv_profile': time.sleep(self.server.delay)  # long enough for the "Reading your CV" screen to show
        answer = self.server.cv if name == 'cv_profile' else {'text': REWRITE}
        self.reply(200, {'id': 'resp_test', 'status': 'completed', 'output': [{'type': 'reasoning', 'summary': []},
                   {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': json.dumps(answer), 'annotations': []}]}]})

    def reply(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data))); self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args): pass


def start(delay=1.2):
    """Returns the running server; its address is server.url and received requests are in server.requests."""
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.requests, server.cv, server.delay = [], CV, delay
    server.url = f'http://127.0.0.1:{server.server_address[1]}/v1'
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
