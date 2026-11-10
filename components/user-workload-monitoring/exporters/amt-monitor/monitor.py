"""Read-only AMT WS-Management checks, cached for Prometheus scrapes."""
import argparse
import hashlib
import http.client
import http.server
import json
import ssl
import threading
import time
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

SOAP = 'http://www.w3.org/2003/05/soap-envelope'
ENUM = 'http://schemas.xmlsoap.org/ws/2004/09/enumeration'
ADDRESS = 'http://schemas.xmlsoap.org/ws/2004/08/addressing'
WSMAN = 'http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd'
CLASSES = {
    'IPS_HostBasedSetupService': ('http://intel.com/wbem/wscim/1/ips-schema/1/', 'CurrentControlMode'),
    'IPS_OptInService': ('http://intel.com/wbem/wscim/1/ips-schema/1/', 'OptInRequired'),
    'CIM_KVMRedirectionSAP': ('http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/', 'EnabledState'),
}


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, *args, fingerprint, **kwargs):
        super().__init__(*args, **kwargs)
        self.fingerprint = fingerprint

    def connect(self):
        super().connect()
        actual = hashlib.sha256(self.sock.getpeercert(binary_form=True)).hexdigest()
        if actual != self.fingerprint:
            self.close()
            raise ssl.SSLError('AMT certificate pin mismatch')


class PinnedHandler(urllib.request.HTTPSHandler):
    def __init__(self, fingerprint):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        # Required by this AMT generation; certificate identity is pinned before HTTP.
        context.options |= getattr(ssl, 'OP_LEGACY_SERVER_CONNECT', 0x4)
        super().__init__(context=context)
        self.fingerprint = fingerprint

    def https_open(self, request):
        def connection(*args, **kwargs):
            return PinnedHTTPS(*args, fingerprint=self.fingerprint, **kwargs)
        return self.do_open(connection, request, context=self._context)


def opener(target):
    passwords = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    passwords.add_password(None, target['url'], target.get('username', 'admin'),
                           Path(target['password_file']).read_text().strip())
    handlers = [urllib.request.ProxyHandler({}), urllib.request.HTTPDigestAuthHandler(passwords)]
    if target['url'].startswith('https:'):
        handlers.append(PinnedHandler(target['certificate_sha256']))
    return urllib.request.build_opener(*handlers)


def request_xml(target, client, name, operation, context=None):
    if operation not in ('Enumerate', 'Pull'):
        raise ValueError('Only read-only enumeration operations are allowed')
    envelope = ET.Element(ET.QName(SOAP, 'Envelope'))
    header = ET.SubElement(envelope, ET.QName(SOAP, 'Header'))
    for ns, key, value in [
        (ADDRESS, 'To', target['url']),
        (ADDRESS, 'Action', ENUM + '/' + operation),
        (ADDRESS, 'MessageID', 'uuid:' + str(uuid.uuid4())),
        (WSMAN, 'ResourceURI', CLASSES[name][0] + name),
        (WSMAN, 'OperationTimeout', 'PT60S'),
    ]:
        ET.SubElement(header, ET.QName(ns, key)).text = value
    reply = ET.SubElement(header, ET.QName(ADDRESS, 'ReplyTo'))
    ET.SubElement(reply, ET.QName(ADDRESS, 'Address')).text = ADDRESS + '/role/anonymous'
    body = ET.SubElement(envelope, ET.QName(SOAP, 'Body'))
    command = ET.SubElement(body, ET.QName(ENUM, operation))
    if context is not None:
        ET.SubElement(command, ET.QName(ENUM, 'EnumerationContext')).text = context
        ET.SubElement(command, ET.QName(ENUM, 'MaxElements')).text = '32'
    request = urllib.request.Request(target['url'], data=ET.tostring(envelope),
                                     headers={'Content-Type': 'application/soap+xml; charset=utf-8'},
                                     method='POST')
    with client.open(request, timeout=10) as response:
        data = response.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError('Oversized AMT response')
    root = ET.fromstring(data)
    if root.find('.//{' + SOAP + '}Fault') is not None:
        raise ValueError('AMT SOAP fault')
    return root


def check(target):
    client, values = opener(target), {}
    for name, (_, field) in CLASSES.items():
        root = request_xml(target, client, name, 'Enumerate')
        for _ in range(8):
            found = [int(e.text) for e in root.iter() if e.tag.rsplit('}', 1)[-1] == field]
            if found:
                if len(found) != 1:
                    raise ValueError('Expected one AMT singleton')
                values[field] = found[0]
                break
            context = root.find('.//{' + ENUM + '}EnumerationContext')
            if context is None or not context.text:
                raise ValueError('Missing AMT enumeration data')
            root = request_xml(target, client, name, 'Pull', context.text)
        else:
            raise ValueError('AMT enumeration limit exceeded')
    return values


def metrics(results):
    lines = []
    names = [('CurrentControlMode', 'amt_control_mode'), ('OptInRequired', 'amt_user_consent_required'),
             ('EnabledState', 'amt_kvm_enabled_state')]
    for node, value in sorted(results.items()):
        label = '{node=' + json.dumps(node) + '}'
        lines.extend([f'amt_up{label} {value["up"]}',
                      f'amt_last_success_timestamp_seconds{label} {value.get("last_success", 0)}',
                      f'amt_check_duration_seconds{label} {value.get("duration", 0)}'])
        for key, metric in names:
            if key in value:
                lines.append(f'{metric}{label} {value[key]}')
        if 'EnabledState' in value:
            lines.append(f'amt_kvm_available{label} {int(value["EnabledState"] in (2, 6))}')
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--targets', default='/app/targets.json')
    parser.add_argument('--interval', type=int, default=300)
    parser.add_argument('--port', type=int, default=9151)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    targets = json.loads(Path(args.targets).read_text())
    results = {t['name']: {'up': 0} for t in targets}
    lock = threading.Lock()

    def cycle():
        for target in targets:
            start = time.monotonic()
            try:
                value = {'up': 1, **check(target), 'last_success': time.time()}
            except Exception as error:
                # No response bodies, credentials, or raw exception messages in logs.
                value = {'up': 0}
                print(json.dumps({'node': target['name'], 'up': 0, 'error': type(error).__name__}), flush=True)
            value['duration'] = time.monotonic() - start
            with lock:
                value.setdefault('last_success', results[target['name']].get('last_success', 0))
                results[target['name']] = value

    if args.once:
        cycle()
        print(metrics(results), end='')
        raise SystemExit(0 if all(v['up'] for v in results.values()) else 1)

    def background():
        while True:
            cycle()
            time.sleep(args.interval)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ('/metrics', '/healthz'):
                self.send_error(404)
                return
            with lock:
                body = metrics(results).encode() if self.path == '/metrics' else b'ok\n'
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; version=0.0.4')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    threading.Thread(target=background, daemon=True).start()
    http.server.ThreadingHTTPServer(('0.0.0.0', args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
