#!/usr/bin/env python3
"""
Google OAuth2 Setup for Jarvis COO Account
Run once to authorize, then tokens auto-refresh forever.
"""

import json
import os
import sys

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets',
]

TOKEN_FILE = os.path.expanduser("~/.openclaw/secrets/google_token.json")
CREDS_FILE = os.path.expanduser("~/.openclaw/secrets/google_credentials.json")

def setup():
    print("""
=== JARVIS GOOGLE ACCOUNT SETUP ===

One-time setup for jarvis.is.my.coo@gmail.com
Services: Gmail, Calendar, Drive, Sheets

STEP 1: Create Google Cloud Project
  1. Go to: https://console.cloud.google.com/
  2. Sign in as jarvis.is.my.coo@gmail.com
  3. Click "Select a project" > "New Project"
  4. Name: "Jarvis COO" > Create

STEP 2: Enable APIs
  Go to: https://console.cloud.google.com/apis/library
  Enable: Gmail API, Google Calendar API, Google Drive API, Google Sheets API

STEP 3: OAuth Consent Screen
  1. Go to: https://console.cloud.google.com/apis/credentials/consent
  2. Choose "External" > Create
  3. App name: "Jarvis COO"
  4. User support email: jarvis.is.my.coo@gmail.com
  5. Developer email: jarvis.is.my.coo@gmail.com
  6. Save and Continue through all steps
  7. Add test user: jarvis.is.my.coo@gmail.com

STEP 4: Create OAuth Credentials
  1. Go to: https://console.cloud.google.com/apis/credentials
  2. "+ Create Credentials" > "OAuth client ID"
  3. Type: "Desktop app", Name: "Jarvis CLI"
  4. Download JSON > Save to: ~/.openclaw/secrets/google_credentials.json

STEP 5: Authorize
  Run: python3 google-oauth-setup.py --authorize
""")

def authorize():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        print("Install: pip3 install --break-system-packages google-auth google-auth-oauthlib google-api-python-client")
        sys.exit(1)
    
    if not os.path.exists(CREDS_FILE):
        print(f"ERROR: {CREDS_FILE} not found. Run without --authorize for setup instructions.")
        sys.exit(1)
    
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired token...")
            creds.refresh(Request())
        else:
            print("Starting OAuth2 flow... Browser will open.")
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=8080)
        
        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        with open(TOKEN_FILE, 'w') as f:
            f.write(creds.to_json())
        os.chmod(TOKEN_FILE, 0o600)
        print(f"Token saved to {TOKEN_FILE}")
    
    print("\nTesting Gmail...")
    svc = build('gmail', 'v1', credentials=creds)
    labels = svc.users().labels().list(userId='me').execute().get('labels', [])
    print(f"  Gmail: {len(labels)} labels")
    msgs = svc.users().messages().list(userId='me', labelIds=['INBOX','UNREAD'], maxResults=5).execute().get('messages', [])
    print(f"  Unread: {len(msgs)}")
    
    print("\nTesting Calendar...")
    try:
        cal = build('calendar', 'v3', credentials=creds)
        cals = cal.calendarList().list().execute().get('items', [])
        print(f"  Calendars: {len(cals)}")
    except Exception as e:
        print(f"  Calendar: {e}")
    
    print("\nAll set! Jarvis has full Google access.")

if __name__ == "__main__":
    if "--authorize" in sys.argv:
        authorize()
    else:
        setup()
