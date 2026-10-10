import unittest
from unittest.mock import Mock

from desktop_app.worker import replacement_ready


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


if __name__ == '__main__':
    unittest.main()
