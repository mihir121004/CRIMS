"""Renew the Gmail OAuth refresh token used by ``accounts.email_backend``.

Production cannot send mail until this is run: Google returns
``invalid_grant: Token has been expired or revoked`` for the current
``GMAIL_REFRESH_TOKEN``, so every verification email fails and registration
rolls back.

Why a script
------------
Getting a refresh token is two steps and the first one has to happen in a
browser: you consent to the OAuth scope, Google redirects back with a
one-time ``code``, and only then can an exchange for a long-lived refresh
token happen. Doing step two by hand means pasting a client secret and a code
into a form; doing it here keeps the credentials out of shell history.

Note this does not use ``accounts.email_backend.get_gmail_access_token`` -
that exchanges a *refresh* token for a short-lived *access* token. This needs
the opposite direction.

Usage
-----
1. In Google Cloud Console -> APIs & Services -> Credentials, open the OAuth
   2.0 client that production uses and note its Client ID and Client secret.
2. Run::

       python scripts/renew_gmail_token.py --client-id ID --client-secret SECRET

   (or omit the flags to be prompted, which keeps them out of your shell
   history entirely)

3. Open the printed URL, sign in as the sending account, approve the request.
4. Google redirects to a page that will not load. Copy the ``code`` from the
   address bar and paste it at the prompt.
5. The script prints a refresh token. Put it in Vercel as
   ``GMAIL_REFRESH_TOKEN`` (production only) and redeploy.
"""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'

# mail.send is what the OTP email needs. The narrower
# https://www.googleapis.com/auth/gmail.modify is NOT interchangeable.
SCOPES = 'https://www.googleapis.com/auth/gmail.send'

REDIRECT_URI = 'urn:ietf:wg:oauth:2.0:oob'
OFFLINE = 'access_type=offline prompt=consent include_granted_scopes=true'


def post_form(url, fields):
    data = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(
        url, data=data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors='replace')
        sys.exit('Google rejected the exchange (HTTP {}):\n{}'.format(exc.code, body))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--client-id', default=os.environ.get('GMAIL_OAUTH_CLIENT_ID', ''),
        help='not a secret; safe to pass on the command line',
    )
    args = parser.parse_args()

    client_id = args.client_id or input('OAuth client ID: ').strip()
    if not client_id:
        sys.exit('an OAuth client ID is required')

    state = base64.urlsafe_b64encode(os.urandom(16)).decode().rstrip('=')
    url = '{}?{}'.format(AUTH_URL, urllib.parse.urlencode({
        'client_id': client_id,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'scope': SCOPES,
        'state': state,
        'access_type': 'offline',
        'prompt': 'consent',
        'include_granted_scopes': 'true',
    }))

    print('\n1. Open this URL and approve the request:\n\n{}\n'.format(url))

    redirect = input('\n2. Paste the full redirect URL (or just its code): ').strip()
    if redirect.startswith('http'):
        query = urllib.parse.urlparse(redirect).query
        params = urllib.parse.parse_qs(query)
        returned_state = params.get('state', [''])[0]
        if returned_state != state:
            sys.exit('state mismatch - aborting, this may not be your redirect')
        if params.get('error'):
            sys.exit('Google returned an error: {}'.format(params['error'][0]))
        code = params.get('code', [''])[0]
    else:
        code = redirect

    if not code:
        sys.exit('no authorization code found in that value')

    # Asked for only now, so the secret is never needed before the consent
    # step and stays out of shell history.
    client_secret = (
        os.environ.get('GOOGLE_CLIENT_SECRET')
        or input('OAuth client secret: ').strip()
    )
    if not client_secret:
        sys.exit('an OAuth client secret is required to exchange the code')

    payload = post_form(TOKEN_URL, {
        'client_id': client_id,
        'client_secret': client_secret,
        'code': code,
        'grant_type': 'authorization_code',
        'redirect_uri': REDIRECT_URI,
    })

    token = payload.get('refresh_token')
    if not token:
        sys.exit(
            'Google returned no refresh token. This happens when the consent '
            'screen was already approved for this scope, so nothing new was '
            'issued.\nRevoke the app at '
            'https://myaccount.google.com/permissions, then run this again.'
        )

    print('\nRefresh token (set this as GMAIL_REFRESH_TOKEN in Vercel):\n\n{}\n'.format(token))
    print('Access token expires in {}s; the refresh token does not expire '
          'on a short timescale.'.format(payload.get('expires_in')))


if __name__ == '__main__':
    main()
