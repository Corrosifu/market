"""Exerce la vraie configuration NGINX sur un réseau isolé et des amonts factices."""
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

pytestmark = pytest.mark.live
ROOT = Path(__file__).resolve().parents[4]

PEER = '''
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

class Peer(BaseHTTPRequestHandler):
    def handle_request(self):
        if self.path == '/v1/auth/verify':
            assert self.command == 'GET' and not self.headers.get('Content-Length')
            authorization = self.headers.get('Authorization')
            status = 204 if authorization == 'Bearer accepted' else 401
            if authorization == 'Bearer unavailable':
                status = 500
            self.send_response(status)
            self.send_header('X-User-Id', 'trusted-id')
            self.send_header('X-User-Role', 'client')
            self.send_header('WWW-Authenticate', 'Bearer')
            self.end_headers()
            return
        self.send_response(500 if self.path == '/v1/catalog/error' else 200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({
            'id': self.headers.get('X-User-Id', ''), 'role': self.headers.get('X-User-Role', ''),
            'body': self.rfile.read(int(self.headers.get('Content-Length', '0'))).decode(),
        }).encode())

    do_GET = do_POST = handle_request

HTTPServer(('0.0.0.0', 8000), Peer).serve_forever()
'''

CHECK = '''
import json
import urllib.error
import urllib.request

def request(path, token=None, body=None):
    headers = {'X-User-Id': 'attacker', 'X-User-Role': 'ops'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request('http://gateway' + path, headers=headers, data=body)
    try:
        response = urllib.request.urlopen(req, timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        assert response.headers['Server'] == 'nginx'
        assert response.headers['X-Content-Type-Options'] == 'nosniff'
        assert response.headers['X-Frame-Options'] == 'DENY'
        return response.status, response.read()

for path, body in [('/v1/auth/login', b'login-body'), ('/.well-known/jwks.json', None)]:
    status, raw = request(path, body=body)
    assert status == 200
    identity = json.loads(raw)
    assert identity['id'] == identity['role'] == ''

assert request('/_auth')[0] == 404
assert request('/v1/auth/verify')[0] == 404
assert request('/v1/catalog/products')[0] == 401
for path in ('/v1/catalog/products', '/v1/stream/events'):
    status, raw = request(path, 'accepted', b'original-body')
    assert status == 200
    assert json.loads(raw) == {'id': 'trusted-id', 'role': 'client', 'body': 'original-body'}
assert request('/v1/catalog/products', 'unavailable')[0] == 503
assert request('/v1/catalog/error', 'accepted')[0] == 500
'''


def test_nginx_overwrites_identity_strips_auth_body_and_preserves_business_500(tmp_path):
    (tmp_path / "peer.py").write_text(PEER, encoding="utf-8")
    spec = {
        "services": {
            "peers": {
                "image": "python:3.12.10-slim", "command": ["python", "/peer.py"],
                "volumes": [f"{tmp_path / 'peer.py'}:/peer.py:ro"],
                "networks": {"default": {"aliases": ["auth", "catalog"]}},
                "healthcheck": {"test": ["CMD", "python", "-c",
                    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz').close()"],
                    "interval": "1s", "timeout": "2s", "retries": 15},
            },
            "gateway": {
                "image": "nginx:1.28.0-alpine",
                "volumes": [f"{ROOT / 'gateway/nginx'}:/etc/nginx/conf.d:ro"],
                "depends_on": {"peers": {"condition": "service_healthy"}},
                "healthcheck": {"test": ["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1/healthz"],
                                "interval": "1s", "timeout": "2s", "retries": 15},
            },
        },
    }
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text(yaml.safe_dump(spec), encoding="utf-8")

    def compose(*args, code=None):
        result = subprocess.run(  # noqa: S603 -- Arguments définis par ce test, sans shell.
            ["docker", "compose", "--env-file", "/dev/null", "-p", "auth-gateway-" + project,  # noqa: S607
             "-f", str(compose_file), *args],
            input=code, capture_output=True, text=True, check=False, encoding="utf-8", timeout=90,
        )
        assert result.returncode == 0, result.stderr

    project = uuid4().hex[:12]
    try:
        compose("up", "-d", "--wait")
        compose("exec", "-T", "peers", "python", "-", code=CHECK)
    finally:
        compose("down")
