#!/usr/bin/env python3
"""
Jarvis Email Checker — Checks Gmail via IMAP with App Password
Usage: python3 check-email.py [--unread] [--limit N] [--search "query"]
"""

import imaplib
import email
import email.header
import argparse
import json
import os
import sys
from datetime import datetime

GMAIL_USER = "jarvis.is.my.coo@gmail.com"
# App password stored in env or file (never hardcoded)
APP_PASSWORD_FILE = os.path.expanduser("~/.openclaw/secrets/gmail_app_password")

def get_app_password():
    """Read app password from env or file"""
    pwd = os.environ.get("GMAIL_APP_PASSWORD")
    if pwd:
        return pwd
    if os.path.exists(APP_PASSWORD_FILE):
        with open(APP_PASSWORD_FILE) as f:
            return f.read().strip()
    print("ERROR: No Gmail app password found.")
    print(f"Set GMAIL_APP_PASSWORD env var or create {APP_PASSWORD_FILE}")
    print("")
    print("To create an App Password:")
    print("1. Go to https://myaccount.google.com/security")
    print("2. Enable 2-Step Verification (if not already)")
    print("3. Go to https://myaccount.google.com/apppasswords")
    print("4. Create app password for 'Mail' on 'Other (Jarvis)'")
    print(f"5. Save the 16-char password to {APP_PASSWORD_FILE}")
    sys.exit(1)

def decode_header(header_val):
    """Decode email header (handles encoded subjects)"""
    if not header_val:
        return ""
    decoded = email.header.decode_header(header_val)
    parts = []
    for text, charset in decoded:
        if isinstance(text, bytes):
            parts.append(text.decode(charset or 'utf-8', errors='replace'))
        else:
            parts.append(text)
    return " ".join(parts)

def check_email(unread_only=True, limit=10, search_query=None):
    """Check Gmail inbox"""
    password = get_app_password()
    
    try:
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(GMAIL_USER, password)
        mail.select('inbox')
        
        # Build search criteria
        if search_query:
            criteria = f'(SUBJECT "{search_query}")'
        elif unread_only:
            criteria = 'UNSEEN'
        else:
            criteria = 'ALL'
        
        status, messages = mail.search(None, criteria)
        
        if status != 'OK':
            print(f"Search failed: {status}")
            return []
        
        msg_ids = messages[0].split()
        if not msg_ids:
            print("No messages found.")
            return []
        
        # Get latest N messages
        msg_ids = msg_ids[-limit:]
        
        results = []
        for msg_id in reversed(msg_ids):  # newest first
            status, msg_data = mail.fetch(msg_id, '(RFC822)')
            if status != 'OK':
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            
            subject = decode_header(msg['Subject'])
            sender = decode_header(msg['From'])
            date = msg['Date']
            
            # Get body
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == 'text/plain':
                        body = part.get_payload(decode=True).decode('utf-8', errors='replace')
                        break
            else:
                body = msg.get_payload(decode=True).decode('utf-8', errors='replace')
            
            result = {
                'subject': subject,
                'from': sender,
                'date': date,
                'body_preview': body[:500].strip(),
                'body_full': body.strip()
            }
            results.append(result)
            
            print(f"📧 {subject}")
            print(f"   From: {sender}")
            print(f"   Date: {date}")
            print(f"   Preview: {body[:200].strip()}")
            print()
        
        mail.close()
        mail.logout()
        
        print(f"Total: {len(results)} message(s)")
        return results
        
    except imaplib.IMAP4.error as e:
        print(f"IMAP Error: {e}")
        if 'AUTHENTICATIONFAILED' in str(e):
            print("\nAuthentication failed. You need a Gmail App Password.")
            print("Regular passwords don't work with IMAP.")
            print("See instructions: python3 check-email.py --help")
        return []
    except Exception as e:
        print(f"Error: {e}")
        return []

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check Jarvis Gmail inbox")
    parser.add_argument("--unread", action="store_true", default=True, help="Only unread messages")
    parser.add_argument("--all", action="store_true", help="All messages (not just unread)")
    parser.add_argument("--limit", type=int, default=10, help="Max messages to fetch")
    parser.add_argument("--search", type=str, help="Search by subject")
    args = parser.parse_args()
    
    check_email(
        unread_only=not args.all,
        limit=args.limit,
        search_query=args.search
    )
