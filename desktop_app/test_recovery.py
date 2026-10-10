import unittest
from unittest.mock import Mock

from desktop_app.worker import replacement_ready, error_reason, pause_message, display_log, redact


class ReplacementTests(unittest.TestCase):
    def test_verified_replacement_resumes(self):
        validate, emit = Mock(), Mock()
        self.assertTrue(replacement_ready({'action': 'key'}, validate, emit))
        validate.assert_called_once_with()
        self.assertIn('Resuming', emit.call_args.kwargs['text'])

    def test_invalid_replacement_stays_paused_and_hides_key(self):
        validate = Mock(side_effect=RuntimeError('Invalid gsk_testsecret'))
        emit = Mock()
        self.assertFalse(replacement_ready({'action': 'key'}, validate, emit))
        self.assertNotIn('gsk_testsecret', str(emit.call_args_list))
        self.assertEqual(emit.call_args.kwargs['state'], 'key')

    def test_unrelated_command_does_not_resume(self):
        validate = Mock()
        self.assertFalse(replacement_ready({'action': 'continue'}, validate, Mock()))
        validate.assert_not_called()

class PauseTests(unittest.TestCase):
    def test_empty_exception_has_reason(self):
        self.assertEqual(error_reason(TimeoutError()), "TimeoutError")

    def test_missing_log_does_not_point_to_missing_error(self):
        text = pause_message("")
        self.assertIn("no error details", text)
        self.assertIn("Continue", text)

    def test_quiz_failure_has_specific_recovery(self):
        self.assertIn("Open Classes", pause_message("Assessment scored 66%, below the required 70%."))

    def test_repository_uses_windows_url_handler(self):
        from desktop_app.window import App
        app = Mock()
        with unittest.mock.patch("desktop_app.window.sys.platform", "win32"), unittest.mock.patch("desktop_app.window.os.startfile", create=True) as launch:
            App.open_repository(app)
            launch.assert_called_once_with("https://github.com/Chaitanya-970/oracle-bot")

    def test_repository_failure_is_visible(self):
        from desktop_app.window import App
        app = Mock()
        with unittest.mock.patch("desktop_app.window.sys.platform", "win32"), unittest.mock.patch("desktop_app.window.os.startfile", create=True, side_effect=OSError("No browser")), unittest.mock.patch("desktop_app.window.messagebox.showerror") as alert:
            App.open_repository(app)
            app.append.assert_called_once()
            alert.assert_called_once()


class LogPrivacyTests(unittest.TestCase):
    def test_quota_diagnostic_is_not_displayed(self):
        self.assertIsNone(display_log("[DIAGNOSTIC ALERT] Reason: Groq API limit was reached"))

    def test_rate_limit_payload_is_summarized(self):
        text = display_log("Groq attempt 1 failed: Groq HTTP 429: organization org_private tokens per day")
        self.assertIn("Groq quota reached", text)
        self.assertNotIn("org_private", text)

    def test_diagnostic_shows_reason_without_session_or_paths(self):
        text = display_log("[DIAGNOSTIC ALERT]\nReason: Question did not advance\nPage URL: https://academy.oracle.com/pls/f?p=secret\nScreenshot: C:\\Users\\Private\\diag.png")
        self.assertIn("Question did not advance", text)
        self.assertNotIn("secret", text)
        self.assertNotIn("Private", text)

    def test_session_url_redacted_in_regular_errors(self):
        self.assertNotIn("secret", redact("Navigation failed at https://academy.oracle.com/pls/f?p=secret"))


if __name__ == '__main__':
    unittest.main()
