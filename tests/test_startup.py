"""Loopback startup regressions; no production service or database is changed."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import start


class StartupTests(unittest.TestCase):
    def test_closed_windows_port_is_normal_startup_and_has_enough_timeout(self):
        with patch.object(start.socket,'create_connection',side_effect=ConnectionRefusedError()) as connect:
            self.assertFalse(start.existing_application())
        self.assertGreaterEqual(connect.call_args.kwargs['timeout'],3)

    def test_slow_refusal_checks_free_port_without_starting_a_listener(self):
        with patch.object(start.socket,'create_connection',side_effect=TimeoutError()), patch.object(start.socket,'socket') as factory:
            self.assertFalse(start.existing_application())
            probe=factory.return_value.__enter__.return_value
            probe.bind.assert_called_once_with((start.HOST,start.PORT))
            probe.listen.assert_not_called()
            if start.os.name=='nt':
                probe.setsockopt.assert_called_once_with(start.socket.SOL_SOCKET,start.socket.SO_EXCLUSIVEADDRUSE,1)

    def test_timeout_with_occupied_port_does_not_start_another_server(self):
        with patch.object(start.socket,'create_connection',side_effect=TimeoutError()), patch.object(start.socket,'socket') as factory:
            factory.return_value.__enter__.return_value.bind.side_effect=OSError('occupied')
            with self.assertRaises(start.StartupError):start.existing_application()

    def test_permission_denial_is_not_treated_as_a_free_port(self):
        with patch.object(start.socket,'create_connection',side_effect=PermissionError('10013')), patch.object(start.socket,'socket') as factory:
            with self.assertRaisesRegex(start.StartupError,'10013'):start.existing_application()
            factory.assert_not_called()

    def test_existing_app_is_recognized_and_other_http_server_is_preserved(self):
        for title,expected in [(start.APP_TITLE,True),('Other application',False)]:
            with self.subTest(title=title),patch.object(start.socket,'create_connection'),patch.object(start,'build_opener') as opener:
                response=opener.return_value.open.return_value.__enter__.return_value
                response.read.return_value=json.dumps({'info':{'title':title},'paths':dict.fromkeys(('/auth/login','/schedules','/health'),{})}).encode()
                if expected:self.assertTrue(start.existing_application())
                else:
                    with self.assertRaises(start.StartupError):start.existing_application()


if __name__=='__main__':unittest.main()
