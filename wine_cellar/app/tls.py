"""HTTPS for direct access.

Uses the certificate named in the `certfile`/`keyfile` options (files in Home Assistant's /ssl folder) when set.
Otherwise the app makes its own small certificate authority, once, and from it a server certificate for the
Home Assistant host's names and IP addresses. Install the authority's certificate (/ca.crt) once on each device
and the browser trusts the connection, so Chrome can install Wine Cellar as an app.

The authority is name-constrained: it can only vouch for .local names, single-label host names and private IP
addresses, so trusting it cannot be misused for public websites.
"""
import json
import os
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.request

DATA = os.path.dirname(os.environ.get("WINE_DB", "/data/wine_cellar.db")) or "/data"
OPTIONS_FILE = os.environ.get("WINE_OPTIONS", "/data/options.json")
SSL_DIR = os.environ.get("WINE_SSL_DIR", "/ssl")
CA_KEY, CA_CRT = os.path.join(DATA, "tls_ca.key"), os.path.join(DATA, "tls_ca.crt")
SRV_KEY, SRV_CRT = os.path.join(DATA, "tls_server.key"), os.path.join(DATA, "tls_server.crt")
SRV_NAMES = os.path.join(DATA, "tls_server.names")
SERVER_DAYS = 397
RENEW_BEFORE = 30 * 24 * 3600


def _options():
    try:
        with open(OPTIONS_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _openssl(*args, stdin=None):
    subprocess.run(["openssl", *args], check=True, capture_output=True, input=stdin)


def _supervisor(path):
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return {}
    req = urllib.request.Request(f"http://supervisor{path}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r).get("data") or {}


def host_names():
    """DNS names and IP addresses the Home Assistant host is reached by on the local network."""
    dns, ips = {"homeassistant.local", "homeassistant"}, set()
    try:
        host = (_supervisor("/host/info").get("hostname") or "").strip().lower()
        if host:
            dns |= {host, host + ".local"}
    except Exception as e:  # noqa: BLE001
        print("TLS: could not read the host name:", e, flush=True)
    try:
        for iface in _supervisor("/network/info").get("interfaces") or []:
            for addr in (iface.get("ipv4") or {}).get("address") or []:
                ips.add(addr.split("/")[0])
    except Exception as e:  # noqa: BLE001
        print("TLS: could not read the IP addresses:", e, flush=True)
    for extra in _options().get("extra_hostnames") or []:
        extra = str(extra).strip().lower()
        if not extra:
            continue
        try:
            socket.inet_aton(extra)
            ips.add(extra)
        except OSError:
            dns.add(extra)
    return sorted(dns), sorted(ips)


def _make_ca():
    cnf = """[req]
distinguished_name = dn
x509_extensions = ca
prompt = no
[dn]
CN = Wine Cellar local CA
O = Wine Cellar (Home Assistant app)
[ca]
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
nameConstraints = critical, permitted;DNS:local, permitted;DNS:homeassistant, permitted;IP:10.0.0.0/255.0.0.0, permitted;IP:172.16.0.0/255.240.0.0, permitted;IP:192.168.0.0/255.255.0.0
"""
    with tempfile.NamedTemporaryFile("w", suffix=".cnf", delete=False) as f:
        f.write(cnf)
    try:
        _openssl("ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", CA_KEY)
        os.chmod(CA_KEY, 0o600)
        _openssl("req", "-x509", "-new", "-key", CA_KEY, "-sha256", "-days", "3650", "-config", f.name, "-out", CA_CRT)
    finally:
        os.unlink(f.name)
    print("TLS: created the Wine Cellar local certificate authority", flush=True)


def _expires_soon(crt):
    try:
        subprocess.run(["openssl", "x509", "-checkend", str(RENEW_BEFORE), "-noout", "-in", crt],
                       check=True, capture_output=True)
        return False
    except (subprocess.CalledProcessError, OSError):
        return True


def _make_server(dns, ips):
    # The CA may only vouch for .local names, "homeassistant" and private addresses; keep the rest out.
    dns = [d for d in dns if d.endswith(".local") or "." not in d]
    ips = [i for i in ips if i.startswith(("10.", "192.168.")) or
           (i.startswith("172.") and 16 <= int(i.split(".")[1]) <= 31)]
    san = ", ".join([f"DNS:{d}" for d in dns] + [f"IP:{i}" for i in ips])
    ext = f"""basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature
extendedKeyUsage = serverAuth
subjectAltName = {san}
authorityKeyIdentifier = keyid
subjectKeyIdentifier = hash
"""
    with tempfile.NamedTemporaryFile("w", suffix=".ext", delete=False) as f:
        f.write(ext)
    csr = SRV_CRT + ".csr"
    try:
        _openssl("ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", SRV_KEY)
        os.chmod(SRV_KEY, 0o600)
        _openssl("req", "-new", "-key", SRV_KEY, "-subj", f"/CN={dns[0]}", "-out", csr)
        _openssl("x509", "-req", "-in", csr, "-CA", CA_CRT, "-CAkey", CA_KEY, "-CAcreateserial",
                 "-days", str(SERVER_DAYS), "-sha256", "-extfile", f.name, "-out", SRV_CRT)
    finally:
        os.unlink(f.name)
        if os.path.exists(csr):
            os.unlink(csr)
    with open(SRV_NAMES, "w") as f:
        json.dump([dns, ips], f)
    print("TLS: server certificate for " + ", ".join(dns + ips), flush=True)


def context():
    """SSL context for the direct port, and whether it uses the app's own CA (so /ca.crt is offered)."""
    opts = _options()
    certfile, keyfile = (opts.get("certfile") or "").strip(), (opts.get("keyfile") or "").strip()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    if certfile and keyfile:
        ctx.load_cert_chain(os.path.join(SSL_DIR, certfile), os.path.join(SSL_DIR, keyfile))
        print(f"TLS: using {certfile} from the /ssl folder", flush=True)
        return ctx, False
    if not (os.path.exists(CA_KEY) and os.path.exists(CA_CRT)):
        _make_ca()
    dns, ips = host_names()
    try:
        with open(SRV_NAMES) as f:
            same = json.load(f) == [dns, ips]
    except (OSError, ValueError):
        same = False
    if not same or not os.path.exists(SRV_KEY) or _expires_soon(SRV_CRT):
        _make_server(dns, ips)
    with tempfile.NamedTemporaryFile("wb", suffix=".pem", delete=False) as f:
        chain = f.name  # server certificate followed by the CA, so clients see the full chain
        f.write(open(SRV_CRT, "rb").read() + open(CA_CRT, "rb").read())
    try:
        ctx.load_cert_chain(chain, SRV_KEY)
    finally:
        os.unlink(chain)
    return ctx, True


def ca_pem():
    with open(CA_CRT, "rb") as f:
        return f.read()


def renew_loop(server, every=24 * 3600):
    """Renew the server certificate in time; new connections pick it up without a restart."""
    while True:
        time.sleep(every)
        try:
            if os.path.exists(SRV_CRT) and _expires_soon(SRV_CRT) and not (_options().get("certfile") or "").strip():
                server.ssl_ctx, _ = context()
        except Exception as e:  # noqa: BLE001
            print("TLS renewal failed:", e, flush=True)
