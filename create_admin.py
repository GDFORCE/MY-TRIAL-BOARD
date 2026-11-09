"""Create an MTB Admin login.

Usage:  python create_admin.py you@example.com "First Last"

The account gets a random password that nobody knows. Set your own with
"Forgot password?" on the login page (the code goes to this email).
The email must also be listed in MTB_ADMIN_EMAILS in .env to open the MTB Admin console.
"""
import sys
import secrets

from app import db, hasher, email, clean, now, audit, mtb_admins


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    e = email(sys.argv[1])
    first, _, last = clean(sys.argv[2]).partition(' ')
    with db() as c:
        if c.execute('SELECT 1 FROM users WHERE email=?', (e,)).fetchone():
            print(f'{e} already has an MTB account. Nothing created.')
        else:
            c.execute('INSERT INTO users(first,last,email,phone,password_hash,status,email_verified,email_verified_at,created) VALUES(?,?,?,?,?,?,?,?,?)',
                      (first or 'MTB', last or 'Admin', e, '', hasher.hash(secrets.token_urlsafe(32)), 'active', 1, now(), now()))
            uid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
            audit(c, None, 'mtb_admin_account_created', 'user', uid)
            print(f'Created {e}. Set a password with "Forgot password?" on the login page.')
    if e not in mtb_admins():
        print(f'Note: add {e} to MTB_ADMIN_EMAILS in .env, then restart the server.')


if __name__ == '__main__':
    main()
