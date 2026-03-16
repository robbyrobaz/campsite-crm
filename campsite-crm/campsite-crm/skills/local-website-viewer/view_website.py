#!/usr/bin/env python3
"""
Local Website Viewer - Take screenshots of local websites
Usage: python3 view_website.py <url> [output_dir]
"""

import sys
import subprocess
import json
from pathlib import Path

def view_website(url, output_dir="."):
    """Screenshot a local website and extract visible text."""
    
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)
    
    # Normalize URL
    if not url.startswith(("http://", "https://")):
        url = f"http://{url}"
    
    # Filename from URL
    safe_name = url.replace("://", "_").replace("/", "_").replace(":", "_")[:50]
    screenshot_file = output_dir / f"{safe_name}_screenshot.png"
    
    print(f"📸 Capturing: {url}")
    
    # Try different methods to take screenshot
    success = False
    
    # Method 1: Try playwright (most reliable)
    try:
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.screenshot(path=str(screenshot_file), full_page=True)
            
            # Extract visible text
            text = page.evaluate("""
                () => {
                    return document.body.innerText;
                }
            """)
            
            browser.close()
            success = True
            visible_text = text
            
    except ImportError:
        print("  (playwright not installed, trying alternatives...)")
    except Exception as e:
        print(f"  (playwright failed: {e})")
    
    # Method 2: Try Selenium
    if not success:
        try:
            from selenium import webdriver
            from selenium.webdriver.common.by import By
            
            options = webdriver.ChromeOptions()
            options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            
            driver = webdriver.Chrome(options=options)
            driver.get(url)
            
            driver.save_screenshot(str(screenshot_file))
            visible_text = driver.find_element(By.TAG_NAME, "body").text
            
            driver.quit()
            success = True
            
        except Exception as e:
            print(f"  (Selenium failed: {e})")
    
    # Method 3: Simple curl + extract via regex
    if not success:
        try:
            import requests
            from html.parser import HTMLParser
            
            response = requests.get(url, timeout=10)
            html = response.text
            
            # Use wkhtmltoimage if available
            try:
                subprocess.run([
                    "wkhtmltoimage",
                    "--width", "1920",
                    "--height", "1080",
                    url,
                    str(screenshot_file)
                ], check=True, capture_output=True, timeout=30)
                success = True
            except FileNotFoundError:
                print("  (wkhtmltoimage not found)")
            
            # Extract visible text (crude but works)
            import re
            text = html
            text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', '\n', text)
            text = re.sub(r'\n\n+', '\n', text)
            visible_text = text.strip()
            
        except Exception as e:
            print(f"  (Requests failed: {e})")
    
    if not success:
        print("❌ Could not capture screenshot. Install: playwright, selenium, or wkhtmltoimage")
        print("   pip install playwright")
        print("   or: sudo apt install wkhtmltopdf")
        return None
    
    # Save text
    text_file = output_dir / f"{safe_name}_text.txt"
    text_file.write_text(visible_text)
    
    print(f"✓ Screenshot: {screenshot_file}")
    print(f"✓ Text: {text_file}")
    print(f"\n--- VISIBLE TEXT PREVIEW (first 50 lines) ---")
    lines = visible_text.split('\n')[:50]
    print('\n'.join(lines))
    if len(visible_text.split('\n')) > 50:
        print(f"\n... ({len(visible_text.split('\n'))} total lines)")
    
    return {
        "url": url,
        "screenshot": str(screenshot_file),
        "text": str(text_file),
        "text_content": visible_text
    }

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 view_website.py <url> [output_dir]")
        sys.exit(1)
    
    url = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "."
    
    result = view_website(url, output_dir)
    if result:
        print(f"\n✓ Done. Check {result['screenshot']} to see the page.")
