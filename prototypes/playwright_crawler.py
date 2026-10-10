import json
import urllib.parse
from pathlib import Path
from playwright.sync_api import sync_playwright

USER_DATA_DIR = Path(__file__).parent / "browser_profile"
AUTH_STATE_FILE = Path(__file__).parent / "auth_state.json"

# The specific link you want to open
TARGET_URL = "https://academy.oracle.com/pls/f?p=63000:14:413510813844704:::14:P14_ID,P14_COURSE_ID:60865,62&cs=3OpGq58uJEHVT1KWlUvYzPWxibNqX7cljqjGJr6ZHcQcx-rAhl4mVXhmuQtVV2fd9L6aWM-zFNHzQqzSUeNAECw"

def clean_apex_url(url):
    """
    Oracle APEX URLs contain a temporary Session ID and a Checksum (cs).
    If we send an expired Session ID, Oracle rejects the connection and forces a login redirect.
    This function strips the dead session ID and checksum so Oracle generates fresh ones for us.
    """
    parsed = urllib.parse.urlparse(url)
    if 'f?p=' not in url:
        return url
        
    query = urllib.parse.parse_qs(parsed.query)
    if 'p' not in query:
        return url
        
    parts = query['p'][0].split(':')
    if len(parts) >= 3:
        parts[2] = '' # Clear the expired Session ID
        
    new_p = ':'.join(parts)
    new_qs = [f'p={new_p}']
    
    for k, v in query.items():
        if k not in ('p', 'cs'): # Remove the old checksum
            new_qs.append(f'{k}={v[0]}')
            
    return f'{parsed.scheme}://{parsed.netloc}{parsed.path}?' + '&'.join(new_qs)

def get_frame_with_locator(context, selector):
    """Searches all frames in all pages for a specific CSS selector."""
    for p_obj in context.pages:
        for f in p_obj.frames:
            try:
                if f.locator(selector).count() > 0:
                    return f
            except Exception:
                pass
    return None

def main():
    print("Launching Playwright Chrome...")
    
    with sync_playwright() as p:
        try:
            # Use Playwright's built-in persistent context so it's guaranteed we track the correct window
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(USER_DATA_DIR),
                headless=False,
                channel="chrome",
                args=[
                    "--start-maximized", 
                    "--disable-blink-features=AutomationControlled",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process"
                ],
                ignore_default_args=["--enable-automation"],
                no_viewport=True
            )
            
            # RESTORE SESSION COOKIES
            if AUTH_STATE_FILE.exists():
                try:
                    with open(AUTH_STATE_FILE, "r", encoding="utf-8") as f:
                        state = json.load(f)
                        if "cookies" in state and state["cookies"]:
                            context.add_cookies(state["cookies"])
                            print(f"Loaded {len(state['cookies'])} session cookies!")
                except Exception as e:
                    print(f"Notice: Could not load auth state: {e}")
            
            page = context.pages[0] if context.pages else context.new_page()
            
            # Clean the URL so Oracle doesn't reject our old session ID
            TARGET_URL = "https://academy.oracle.com/pls/f?p=63000:14:410854854456046::::P14_ID:60866&cs=39gqaKtu0t3B32vCfMF6l-w58qVtONGEHnmgQG5kNxSyrElm771yUowrMsjAzo55cmn7djwKVAZ5mEre--ovc7w"
            safe_url = clean_apex_url(TARGET_URL)
            print(f"\nNavigating to: {safe_url}")
            
            page.goto(safe_url)
            
            print("\n" + "=" * 65)
            print("If you are not logged in, please sign in now inside the Chrome window that just opened.")
            print("WAIT until the course SECTIONS LIST is fully visible on your screen.")
            print("=" * 65 + "\n")
            
            input("Press Enter ONLY AFTER the course sections have fully loaded...")
            
            import time
            print("\nSearching for the Course Sections list...")
            
            # 1. Find the Sections frame
            sections_frame = None
            for attempt in range(5):
                sections_frame = get_frame_with_locator(context, "li.t-MediaList-item")
                if sections_frame: break
                time.sleep(2)
                
            if not sections_frame:
                print("\n[!] Could not find the sections list (t-MediaList).")
                print("Make sure you are on the page with all the course sections!")
            else:
                # Extract all section URLs
                section_links = sections_frame.locator("li.t-MediaList-item a.t-MediaList-itemWrap")
                section_count = section_links.count()
                print(f"Found {section_count} course sections!")
                
                section_urls = []
                for i in range(section_count):
                    href = section_links.nth(i).get_attribute("href")
                    if href:
                        section_urls.append(href)
                
                # OUTER LOOP: Iterate through each course section
                for s_idx, relative_s_url in enumerate(section_urls):
                    print(f"\n{'='*50}")
                    print(f"Processing Section [{s_idx+1}/{section_count}]")
                    print(f"{'='*50}")
                    
                    full_s_url = f"https://academy.oracle.com/pls/{relative_s_url}" if not relative_s_url.startswith("http") else relative_s_url
                    
                    # Navigate the main page to the section
                    page.goto(full_s_url, wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)
                    
                    # 2. Find the Wizard Steps frame for this section
                    wizard_frame = None
                    for attempt in range(5):
                        wizard_frame = get_frame_with_locator(context, "li.t-WizardSteps-step")
                        if wizard_frame: break
                        time.sleep(2)
                        
                    if not wizard_frame:
                        print("  -> No wizard steps found in this section. It might be an exam or empty. Moving to next section.")
                        continue
                        
                    step_count = wizard_frame.locator("li.t-WizardSteps-step").count()
                    print(f"  -> Found {step_count} wizard steps in this section.")
                    
                    # INNER LOOP: Click each step and click Save and Continue
                    for i in range(step_count):
                        print(f"\n    [{i+1}/{step_count}] Processing step...")
                        
                        # Re-fetch frame because clicking "Save and Continue" reloads the page
                        current_frame = get_frame_with_locator(context, "li.t-WizardSteps-step")
                        if not current_frame:
                            print("    -> Frame lost! Attempting to recover...")
                            time.sleep(3)
                            current_frame = get_frame_with_locator(context, "li.t-WizardSteps-step")
                            if not current_frame:
                                print("    -> Could not recover frame. Skipping step.")
                                continue
                                
                        try:
                            # Click the step link in the sidebar
                            current_link = current_frame.locator("li.t-WizardSteps-step a.t-WizardSteps-wrap").nth(i)
                            if current_link.is_visible():
                                print(f"      -> Opening course section step...")
                                current_link.click()
                                page.wait_for_load_state("domcontentloaded")
                                page.wait_for_timeout(2500)
                        except Exception as e:
                            print(f"      -> Note: Could not click sidebar link: {e}")

                        # Re-fetch frame after navigating to the step
                        current_frame = get_frame_with_locator(context, "li.t-WizardSteps-step") or current_frame

                        # Click Save and Continue
                        btn = current_frame.locator("span.t-Button-label", has_text="Save and Continue")
                        if btn.count() > 0 and btn.first.is_visible():
                            print(f"      -> Clicking 'Save and Continue'...")
                            btn.first.click()
                            page.wait_for_load_state("domcontentloaded")
                            page.wait_for_timeout(2500)
                        else:
                            print("      -> Button 'Save and Continue' not found on this step. Moving to next.")
                            
            print("\n" + "=" * 50)
            print("All course sections have been processed!")
            print("=" * 50)
            
            input("\nPress Enter to save session cookies and close browser...")
            
            # SAVE SESSION COOKIES
            try:
                context.storage_state(path=str(AUTH_STATE_FILE))
                print(f"Successfully saved session state to {AUTH_STATE_FILE.name}!")
            except Exception as e:
                print(f"Error saving storage state: {e}")
                
            context.close()
            
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
