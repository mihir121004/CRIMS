import base64
import json
import os
import smtplib
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def get_gmail_access_token():
    data = urllib.parse.urlencode(
        {
            "client_id": os.environ["GMAIL_OAUTH_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "refresh_token": os.environ["GMAIL_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        }
    ).encode()
    req = urllib.request.Request(
        GOOGLE_TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode())
    return payload["access_token"]


def build_xoauth2_string(user, access_token):
    raw = f"user={user}\x01auth=Bearer {access_token}\x01\x01"
    return base64.b64encode(raw.encode()).decode()


class GmailOAuthBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        user = settings.EMAIL_HOST_USER
        access_token = get_gmail_access_token()
        xoauth2 = build_xoauth2_string(user, access_token)

        sent = 0
        for message in email_messages:
            if self.fail_silently:
                try:
                    self._send_one(message, user, xoauth2)
                    sent += 1
                except Exception:
                    pass
            else:
                self._send_one(message, user, xoauth2)
                sent += 1
        return sent

    @staticmethod
    def _send_one(message, user, xoauth2):
        smtp = smtplib.SMTP("smtp.gmail.com", 587, timeout=20)
        try:
            smtp.ehlo("crims")
            smtp.starttls()
            smtp.ehlo("crims")
            code, resp = smtp.docmd("AUTH", "XOAUTH2 " + xoauth2)
            if code != 235:
                raise Exception(f"SMTP auth failed: {code} {resp!r}")
            smtp.sendmail(
                message.from_email,
                message.recipients(),
                message.message().as_string(),
            )
        finally:
            smtp.quit()
