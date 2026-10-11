"""Shared recovery policy for temporary Oracle loading failures."""
import re


class RecoveryBudget:
    delays = (5, 15, 30, 60, 60, 60, 60, 60)

    def __init__(self):
        self.counts = {}

    def next_delay(self, reason, state):
        if re.search(r'Groq|API limit|below the required 70%|question changed|Question did not advance|Invalid answer|session expired|sign-in', reason, re.I):
            return None
        categories = (
            ('lesson', r'lesson controls|Incomplete sidebar lesson|Save action|confirm saving|Save and Continue control'),
            ('selection', r'selection state|Answer selection'),
            ('results', r'View Results|results-navigation waits|Return to Course did not leave'),
            ('navigation', r'TimeoutError|frame was detached|execution context was destroyed'),
        )
        category = next((name for name, pattern in categories if re.search(pattern, reason, re.I)), None)
        if category is None:
            return None
        key = (category, state)
        count = self.counts.get(key, 0)
        if count >= len(self.delays) or (key not in self.counts and len(self.counts) >= 128):
            return None
        self.counts[key] = count + 1
        return self.delays[count]


def recovery_state(page):
    from bot.apex_helpers import question_identity, wizard_steps, is_step_active
    identity = question_identity(page)
    active = tuple(item.inner_text(timeout=1000) for _, item in wizard_steps(page) if is_step_active(item))
    return repr((page.url, identity, active))
