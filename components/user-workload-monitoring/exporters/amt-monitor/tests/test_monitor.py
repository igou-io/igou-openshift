import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location('monitor', Path(__file__).parents[1] / 'monitor.py')
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


class Client:
    def __init__(self, fault=False, missing=False):
        self.actions = []
        self.fault = fault
        self.missing = missing

    def open(self, request, timeout):
        xml = ET.fromstring(request.data)
        action = xml.find('.//{' + monitor.ADDRESS + '}Action').text
        self.actions.append(action)
        if self.fault:
            return io.BytesIO(('<s:Envelope xmlns:s="' + monitor.SOAP + '"><s:Body>'
                               '<s:Fault/></s:Body></s:Envelope>').encode())
        if action.endswith('/Enumerate'):
            return io.BytesIO(('<EnumerateResponse xmlns="' + monitor.ENUM + '">'
                               '<EnumerationContext>context</EnumerationContext>'
                               '</EnumerateResponse>').encode())
        uri = xml.find('.//{' + monitor.WSMAN + '}ResourceURI').text
        name = uri.rsplit('/', 1)[-1]
        field = monitor.CLASSES[name][1]
        value = {'CurrentControlMode': 2, 'OptInRequired': 0, 'EnabledState': 6}[field]
        body = '' if self.missing else f'<{field}>{value}</{field}>'
        return io.BytesIO(('<PullResponse xmlns="' + monitor.ENUM + '"><Items>'
                           + body + '</Items><EndOfSequence/></PullResponse>').encode())


class Checks(unittest.TestCase):
    def test_real_state_requires_authenticated_enumeration_and_only_reads(self):
        client = Client()
        with patch.object(monitor, 'opener', return_value=client):
            value = monitor.check({'url': 'http://amt.example/wsman'})
        self.assertEqual(value, {'CurrentControlMode': 2, 'OptInRequired': 0, 'EnabledState': 6})
        self.assertEqual(len(client.actions), 6)
        self.assertTrue(all(a in (monitor.ENUM + '/Enumerate', monitor.ENUM + '/Pull')
                            for a in client.actions))

    def test_fault_or_missing_state_cannot_be_reported_healthy(self):
        for client in [Client(fault=True), Client(missing=True)]:
            with self.subTest(client=client), patch.object(monitor, 'opener', return_value=client):
                with self.assertRaises(ValueError):
                    monitor.check({'url': 'http://amt.example/wsman'})

    def test_power_operations_are_rejected_before_network_io(self):
        client = Client()
        with self.assertRaises(ValueError):
            monitor.request_xml({}, client, 'IPS_OptInService', 'RequestPowerStateChange')
        self.assertEqual(client.actions, [])

    def test_idle_kvm_is_healthy_and_failed_checks_have_no_stale_policy_values(self):
        result = monitor.metrics({'worker': {'up': 1, 'EnabledState': 6}})
        self.assertIn('amt_kvm_available{node="worker"} 1', result)
        failed = monitor.metrics({'worker': {'up': 0}})
        self.assertNotIn('amt_kvm_available', failed)


if __name__ == '__main__':
    unittest.main()
