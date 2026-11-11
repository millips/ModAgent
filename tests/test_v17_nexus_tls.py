import datetime
import ipaddress
import os
import ssl
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')

from modagent import nexus


@pytest.mark.parametrize('trusted,matching', [(False, True), (True, False), (True, True)])
def test_nexus_tls_authenticates_before_sending_key(tmp_path, monkeypatch, trusted, matching):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'fixture.invalid')])
    now = datetime.datetime.now(datetime.timezone.utc)
    alt_name = x509.IPAddress(ipaddress.ip_address('127.0.0.1')) if matching else x509.DNSName('fixture.invalid')
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1)).not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([alt_name]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256()))
    cert_path = tmp_path / 'test-cert.pem'; key_path = tmp_path / 'test-key.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            requests.append(self.headers.get('apikey'))
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true}')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert_path), str(key_path))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    if trusted:
        create_context = ssl.create_default_context
        monkeypatch.setattr(ssl, 'create_default_context', lambda: create_context(cafile=str(cert_path)))
    try:
        url = f'https://127.0.0.1:{server.server_port}/'
        if trusted and matching:
            assert nexus._api(url, 'synthetic-only') == {'ok':True}
            assert requests == ['synthetic-only']
        else:
            with pytest.raises(urllib.error.URLError) as caught:
                nexus._api(url, 'synthetic-only')
            assert isinstance(caught.value.reason, ssl.SSLCertVerificationError)
            assert requests == [], 'Do not send API headers before authenticating the server'
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
