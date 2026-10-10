"""Read Oracle scores and retain feedback for a subsequent attempt."""
import json
import re
from bot.config import LOGS_DIR
from bot.apex_helpers import surfaces, page_text

FEEDBACK_FILE = LOGS_DIR / "assessment_feedback.json"


def normalized(text):
    return " ".join(text.casefold().split())


def feedback_for(question):
    if not FEEDBACK_FILE.exists():
        return []
    return json.loads(FEEDBACK_FILE.read_text(encoding="utf-8")).get(normalized(question), [])


def record_results(page):
    match = re.search(r"Percentage Scored\s*:\s*(\d+(?:\.\d+)?)\s*%", page_text(page), re.I)
    score = float(match.group(1)) if match else None
    feedback = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8")) if FEEDBACK_FILE.exists() else {}
    for frame in surfaces(page):
        rows = frame.locator('table.t-Report-report tbody tr').evaluate_all("""rows => rows.map(row =>
            Object.fromEntries([...row.querySelectorAll('td[headers]')].map(cell =>
                [cell.getAttribute('headers'), cell.innerText.trim()])))""")
        for row in rows:
            if 'SCORE' in row and re.fullmatch(r'\d+(?:\.\d+)?%', row['SCORE']):
                score = float(row['SCORE'].rstrip('%'))
            if row.get('QUESTION') and row.get('USER_CHOICE'):
                key = normalized(row['QUESTION'])
                entry = {'answer': row['USER_CHOICE'], 'feedback': row.get('INCORRECT_RESPONSE_FEEDBACK', '')}
                if entry not in feedback.setdefault(key, []):
                    feedback[key].append(entry)
    if feedback:
        FEEDBACK_FILE.write_text(json.dumps(feedback, ensure_ascii=False, indent=2), encoding="utf-8")
    return score
