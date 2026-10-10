"""Explicit paid/network smoke test, separate from offline regressions."""
import base64
from playwright.sync_api import sync_playwright
from bot.groq_solver import validate_api, solve_mcq

validate_api()
assert solve_mcq('Which Oracle SQL statement reads rows?', ['SELECT', 'DROP']) == [0]
with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page()
    page.set_content('<div style="font:36px Arial;width:500px;height:180px">CUSTOMER → ORDER</div>')
    image = base64.b64encode(page.locator('div').screenshot()).decode()
    assert solve_mcq('Which word appears on the left in the diagram?', ['CUSTOMER', 'ORDER'], image) == [0]
    browser.close()
print('Live text and vision checks passed.')
