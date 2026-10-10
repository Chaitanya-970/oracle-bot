import base64
import json
import time
import unittest
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from bot import runner
from bot.apex_helpers import extract_question_and_options, click_button_by_text, option_text, is_step_active
from bot.groq_solver import parse_option_indices, solve_with_session, solve_mcq
from bot.session import maintain_session, session_wait, SessionExpired, native_dialog


class ParserTests(unittest.TestCase):
    def test_nested_apex_entities(self):
        self.assertEqual(option_text('SELECT&amp;#x20;id&amp;#x20;&amp;#x3C;5&amp;#x3B;'), 'SELECT id <5;')
        self.assertEqual(option_text('SELECT&#x20;id<br />FROM employees;'), 'SELECT id\nFROM employees;')

    def test_single_choice_never_guesses_from_multiple_indices(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":"[0,1]"}}]}'
        with patch('bot.groq_solver.GROQ_API_KEY', 'test-key'), patch('bot.groq_solver.urlopen', return_value=response), patch('bot.groq_solver.time.sleep'):
            with self.assertRaises(RuntimeError):
                solve_mcq('Which two are correct?', ['A','B'], retries=1, multiple=False)

    def test_compound_rate_limit_wait(self):
        from bot.groq_solver import rate_limit_delay
        self.assertAlmostEqual(rate_limit_delay('Please try again in 1m16.896s.'), 77.396)
        self.assertAlmostEqual(rate_limit_delay('try again in 32.832s'), 33.332)
        self.assertEqual(rate_limit_delay('Too many requests', {'Retry-After': '60'}), 60.5)

    def test_rate_limit_does_not_consume_answer_retry(self):
        from urllib.error import HTTPError
        from io import BytesIO
        error = HTTPError('http://test', 429, 'rate limited', {}, BytesIO(b'Please try again in 1m16.896s.'))
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":"[0]"}}]}'
        with patch('bot.groq_solver.GROQ_API_KEY', 'test-key'), patch('bot.groq_solver.urlopen', side_effect=[error, response]), patch('bot.groq_solver.time.sleep') as sleep:
            self.assertEqual(solve_mcq('Question', ['A','B'], retries=1), [0])
        sleep.assert_called_once_with(77.396)

    def test_replacing_file_key_takes_effect_without_restart(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from bot.config import current_api_key
        with TemporaryDirectory() as directory, patch('bot.config.PROJECT_ROOT', Path(directory)), patch('bot.config._file_loaded_keys', {'GROQ_API_KEY'}):
            env = Path(directory) / '.env'
            env.write_text('GROQ_API_KEY=first-key')
            self.assertEqual(current_api_key(), 'first-key')
            env.write_text('GROQ_API_KEY=second-key')
            self.assertEqual(current_api_key(), 'second-key')

    def test_external_key_keeps_precedence_over_file(self):
        from bot.config import current_api_key
        with patch('bot.config._file_loaded_keys', set()), patch('bot.config.GROQ_API_KEY', 'external-key'):
            self.assertEqual(current_api_key(), 'external-key')

    def test_feedback_matches_question_despite_number_prefix(self):
        from bot.assessment_results import normalized
        self.assertEqual(normalized('Question 3 of 15\nArcs model an Exclusive OR constraint.'), normalized('Arcs model an Exclusive OR constraint.'))

    def test_valid_outputs(self):
        for text, answer in [('0', [0]), ('[0,2]', [0, 2]), ('0, 2', [0, 2]), ('B', [1]), ('```json\n[1]\n```', [1])]:
            self.assertEqual(parse_option_indices(text, 4), answer)

    def test_reject_ambiguous_or_invalid(self):
        for text in ('[0,8]', '[true]', 'true', '-1', '0.5', 'Option 2 because there are 3 columns', '[1,"2"]', '[]', 'A, Z'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_option_indices(text, 4)


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel='chrome', headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.page.on('dialog', native_dialog)

    def tearDown(self):
        self.page.close()

    def test_session_warning_and_expiry(self):
        self.page.set_content('''<button onclick="window.wrong=true">Yes</button>
          <div role="dialog">Your session is about to expire
          <input type="button" value="Extend Session" onclick="window.extended=true;this.parentNode.remove()"></div>''')
        self.assertTrue(maintain_session(self.page))
        self.assertTrue(self.page.evaluate('window.extended'))
        self.assertIsNone(self.page.evaluate('window.wrong'))
        self.page.set_content('<div role="dialog">Your session has expired<button>OK</button></div>')
        with self.assertRaises(SessionExpired):
            maintain_session(self.page)

    def test_dialog_disappearing_during_session_check_does_not_wait(self):
        self.page.set_content('<div role="dialog">Session will expire<button>Yes</button></div>')
        real_frame = self.page.main_frame
        frame = unittest.mock.MagicMock()
        frame.is_detached.return_value = False
        def snapshot(selector):
            locator = real_frame.locator(selector)
            if 'password' in selector:
                return locator
            handles = locator.element_handles()
            self.page.evaluate("document.querySelector('[role=dialog]').remove()")
            proxy = unittest.mock.MagicMock()
            proxy.element_handles.return_value = handles
            return proxy
        frame.locator.side_effect = snapshot
        with patch('bot.session.surfaces', return_value=[frame]), patch('bot.session.page_text', return_value=''):
            self.assertFalse(maintain_session(self.page))

    def test_unknown_session_extension_control_is_not_swallowed(self):
        self.page.set_content('<div role="dialog">Your session will expire<button>Unrecognized</button></div>')
        with self.assertRaises(RuntimeError):
            maintain_session(self.page)

    def test_active_sidebar_url_needs_no_jump(self):
        self.page.route('http://oracle.test/current', lambda route: route.fulfill(body='<li class="t-WizardSteps-step"><a href="/current">Current</a></li>', content_type='text/html'))
        self.page.goto('http://oracle.test/current')
        self.assertTrue(is_step_active(self.page.locator('li')))

    def test_oracle_sidebar_marks_every_entry_current(self):
        self.page.set_content('<ul><li class="t-WizardSteps-step is-complete is-active-module" aria-current="step"><a href="/read">Read</a></li><li class="t-WizardSteps-step is-incomplete-assessment" aria-current="step"><a href="/quiz">Quiz</a></li></ul>')
        steps = self.page.locator('li')
        self.assertTrue(is_step_active(steps.nth(0)))
        self.assertFalse(is_step_active(steps.nth(1)))

    def test_completed_lesson_jumps_directly_to_remaining_step(self):
        visited = []
        def route(request):
            visited.append(request.request.url)
            if request.request.url.endswith('/quiz'):
                body = '<li class="t-WizardSteps-step is-complete">Done</li>'
            else:
                body = '<li class="t-WizardSteps-step is-complete is-active-module" aria-current="step"><a href="/read">Read</a></li><li class="t-WizardSteps-step" aria-current="step"><a href="/quiz">Quiz</a></li><a href="/wrong">Save and Continue</a>'
            request.fulfill(body=body, content_type='text/html')
        self.page.route('http://oracle.test/**', route)
        self.page.goto('http://oracle.test/read')
        with patch('bot.runner.STEP_DELAY', 0):
            self.assertTrue(runner.process_course_lessons(self.page))
        self.assertEqual(visited, ['http://oracle.test/read', 'http://oracle.test/quiz'])

    def test_completed_quiz_landing_does_not_start_another_attempt(self):
        visited = []
        def route(request):
            visited.append(request.request.url)
            body = ('<li class="t-WizardSteps-step is-complete">Done</li>'
                    if request.request.url.endswith('/next') else
                    '<li class="t-WizardSteps-step is-complete is-active-module"><a href="/quiz">Quiz 1</a></li>'
                    '<li class="t-WizardSteps-step"><a href="/next">Next lesson</a></li>'
                    '<a href="/wrong">Take an Assessment</a>')
            request.fulfill(body=body, content_type='text/html')
        self.page.route('http://oracle.test/**', route)
        self.page.goto('http://oracle.test/quiz')
        with patch('bot.runner.STEP_DELAY', 0):
            self.assertTrue(runner.process_course_lessons(self.page))
        self.assertEqual(visited, ['http://oracle.test/quiz', 'http://oracle.test/next'])

    def test_resumable_assessment_uses_finish_assessment_opener(self):
        from bot.apex_helpers import is_quiz_landing_page
        self.page.set_content('''<a onclick="document.querySelector('div').style.display='block'">Finish Assessment</a><div role="dialog" style="display:none"><button onclick="document.body.innerHTML='Question 1 of 1'">Start</button></div>''')
        self.assertTrue(is_quiz_landing_page(self.page))
        with patch('bot.runner.solve_current_quiz', return_value=True):
            self.assertTrue(runner.handle_quiz_landing_and_start(self.page))

    def test_low_score_records_feedback_and_pauses(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from bot.assessment_results import feedback_for
        self.page.set_content('<h1>Results Summary</h1><table class="t-Report-report"><tbody><tr><td headers="SCORE">66.67%</td></tr><tr><td headers="QUESTION">Arcs model exclusive OR?</td><td headers="USER_CHOICE">False</td><td headers="INCORRECT_RESPONSE_FEEDBACK">Incorrect</td></tr></tbody></table><button>Return to Course Lessons</button>')
        with TemporaryDirectory() as directory, patch('bot.assessment_results.FEEDBACK_FILE', Path(directory)/'feedback.json'), patch('bot.runner.capture_diagnostic'):
            self.assertFalse(runner.finish_assessment(self.page))
            self.assertEqual(feedback_for('Arcs model exclusive OR?')[0]['answer'], 'False')

    def test_return_control_alone_is_not_success(self):
        self.page.set_content('<button>Exit</button>')
        with patch('bot.runner.capture_diagnostic'):
            self.assertFalse(runner.finish_assessment(self.page))

    def test_section_entry_does_not_recurse_forever(self):
        self.page.set_content('<li class="t-WizardSteps-step is-complete">Done</li>')
        with patch('bot.runner.STEP_DELAY', 0):
            self.assertTrue(runner.walk_courses(self.page))

    def test_warning_during_ai_request(self):
        self.page.set_content('''<script>setTimeout(()=>{document.body.innerHTML =
          '<div role="dialog">Session will expire<button onclick="window.extended=true;this.parentNode.remove()">Yes</button></div>'},200)</script>''')
        def slow(*args, **kwargs):
            time.sleep(0.8)
            return [0]
        with patch('bot.groq_solver.solve_mcq', side_effect=slow):
            self.assertEqual(solve_with_session(self.page, 'Question', ['A','B']), [0])
        self.assertTrue(self.page.evaluate('window.extended'))

    def test_http_timeout_is_propagated(self):
        self.page.set_content('<p>Lesson</p>')
        with patch('bot.groq_solver.solve_mcq', side_effect=TimeoutError('HTTP request timed out')):
            with self.assertRaises(TimeoutError):
                solve_with_session(self.page, 'Question', ['A','B'])

    def test_modal_scope(self):
        self.page.set_content('''<button onclick="window.wrong=true">Start</button>
          <div role="dialog" style="display:none"><button>Start</button></div>
          <div role="dialog"><input type="button" value="Start" onclick="window.right=true"></div>''')
        self.assertTrue(click_button_by_text(self.page, ['^Start$'], modal_only=True))
        self.assertTrue(self.page.evaluate('window.right'))
        self.assertIsNone(self.page.evaluate('window.wrong'))

    def test_button_search_handles_disabled_hidden_and_input_controls(self):
        self.page.set_content('''<button disabled>Save Progress</button><button style="display:none">Save Progress</button>
          <input type="submit" value="Save Progress" onclick="window.saved=true;return false">''')
        self.assertTrue(click_button_by_text(self.page, ['^Save Progress$']))
        self.assertTrue(self.page.evaluate('window.saved'))

    def test_button_labels_click_their_parent_control_once(self):
        self.page.set_content('''<button onclick="window.clicks=(window.clicks||0)+1"><span class="t-Button-label">Submit Answer</span></button>''')
        self.assertTrue(click_button_by_text(self.page, ['^Submit Answer$']))
        self.assertEqual(self.page.evaluate('window.clicks'), 1)

    def test_native_session_confirmation(self):
        self.page.set_content('<p>Lesson</p>')
        self.assertTrue(self.page.evaluate("confirm('Your session will expire. Extend session?')"))
        self.assertTrue(self.page.evaluate("confirm('Submit assessment?')"))
        self.assertFalse(self.page.evaluate("confirm('Delete account?')"))

    def test_statistics_are_not_sections(self):
        self.page.set_content('''<li class="t-MediaList-item"><a class="t-MediaList-itemWrap" href="">Sections in Course 24</a></li>
            <li class="t-MediaList-item"><a class="t-MediaList-itemWrap" href="/lesson"><h3 class="t-MediaList-title">SQL</h3><span>55%</span></a></li>''')
        sections = runner.section_controls(self.page)
        self.assertEqual(len(sections), 1)
        self.assertEqual(runner.item_label(sections[0][1]), 'SQL')

    def test_stalled_save_is_failure(self):
        self.page.set_content('<button>Save and Continue</button>')
        with patch('bot.runner.STEP_DELAY', 0), patch('bot.runner.wait_until', return_value=False), patch('bot.runner.capture_diagnostic'):
            self.assertFalse(runner.process_course_lessons(self.page))

    def test_full_course_traversal_with_iframe_quizzes(self):
        self.run_course_fixture(False)

    def test_course_list_in_unnamed_iframe(self):
        self.run_course_fixture(True)

    def run_course_fixture(self, iframe_list):
        done, opened, answers = set(), set(), []
        def route(request_route):
            from urllib.parse import urlsplit
            parts = urlsplit(request_route.request.url).path.strip('/').split('/')
            kind = parts[0]
            html = ''
            if kind == 'shell':
                html = '<iframe src="/classes" style="width:1000px;height:700px"></iframe>'
            elif kind == 'classes':
                html = '<h1>My Classes</h1>' + ''.join(f'<a href="/course/{c}">Take Class</a>' for c in range(2))
            elif kind == 'course':
                c = int(parts[1])
                html = '<h1>Course Outline</h1><ul>' + ''.join(f'<li class="t-MediaList-item"><a class="t-MediaList-itemWrap" href="/lesson/{c}/{s}/0">Section {s}</a></li>' for s in range(2)) + '</ul>'
            elif kind in ('lesson', 'save'):
                c, s, step = map(int, parts[1:])
                opened.add((c, s))
                if kind == 'save':
                    done.add((c,s,0))
                    step = 1
                html = '<ul>' + ''.join(f'<li class="t-WizardSteps-step {"is-complete" if (c,s,i) in done else ""}"><a class="t-WizardSteps-wrap" href="/lesson/{c}/{s}/{i}">Step {i}</a></li>' for i in range(2)) + '</ul>'
                if step == 0:
                    html += f'<p>Read the SQL lesson</p><a href="/save/{c}/{s}/0">Save and Continue</a>'
                else:
                    html += f'''<a onclick="document.querySelector('[role=dialog]').style.display='block'">Take an Assessment</a>
                    <div role="dialog" style="display:none"><a href="/quiz/{c}/{s}">Start</a></div>'''
            elif kind == 'quiz':
                c, s = map(int, parts[1:])
                html = f'<iframe src="/question/{c}/{s}/0" style="width:900px;height:600px"></iframe>'
            elif kind == 'question':
                c, s, q = map(int, parts[1:])
                if q == 2:
                    html = f'<a href="/complete/{c}/{s}">Complete Assessment</a>'
                else:
                    if q:
                        answers.append((c, s, q-1))
                    role = 'checkbox' if q else 'radio'
                    html = f'<p>Question {q+1} of 2</p><div region-id="question-Text">Which statements are valid?</div>'
                    for i in range(3):
                        js = "this.setAttribute('aria-checked', this.getAttribute('aria-checked')==='true'?'false':'true')"
                        html += f'<button class="choice-SelectArea" role="{role}" aria-checked="false" aria-label="Option {i}" onclick="{js}">Option {i}</button>'
                    expected = '[0,2]' if q else '[0]'
                    html += f'''<button onclick="let indices=[...document.querySelectorAll('[aria-checked=true]')].map(x=>Number(x.getAttribute('aria-label').slice(-1)));if(JSON.stringify(indices)==='{expected}')location.href='/question/{c}/{s}/{q+1}'">Submit Answer</button>'''
            elif kind == 'complete':
                c, s = map(int, parts[1:])
                answers.append((c,s,1))
                html = f'<div role="dialog">Submit this assessment?<a href="/results/{c}/{s}">Yes</a></div>'
            elif kind == 'results':
                c, s = map(int, parts[1:])
                done.add((c,s,1))
                html = f'<h1>Results Summary</h1><p>Assessment Score: 100%</p><a target="_top" href="/lesson/{c}/{s}/1">Return to Course Lessons</a>'
            request_route.fulfill(status=200, content_type='text/html', body=html)
        self.page.route('http://oracle.test/**', route)
        self.page.goto('http://oracle.test/shell' if iframe_list else 'http://oracle.test/classes')
        def solve(page, text, opts, image, multiple):
            return [0, 2] if multiple else [0]
        with patch('bot.runner.STEP_DELAY', 0), patch('bot.runner.solve_with_session', side_effect=solve):
            self.assertTrue(runner.walk_courses(self.page))
        self.assertEqual(opened, {(c,s) for c in range(2) for s in range(2)})
        self.assertEqual(done, {(c,s,i) for c in range(2) for s in range(2) for i in range(2)})
        self.assertEqual(len(answers), 8)

    def test_failure_does_not_report_success(self):
        self.page.set_content('<p>Question 1 of 1</p><div region-id="question-Text">Question</div><button class="choice-SelectArea" role="radio">A</button><button class="choice-SelectArea" role="radio">B</button>')
        with patch('bot.runner.solve_with_session', side_effect=RuntimeError('unavailable')), patch('bot.runner.capture_diagnostic'):
            self.assertFalse(runner.solve_current_quiz(self.page))


if __name__ == '__main__':
    unittest.main()
