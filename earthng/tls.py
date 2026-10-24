"""HTTPS for the map builder.

Geofabrik's chain is leaf, Let's Encrypt YE1, Root YE, ISRG Root X2, signed up to
ISRG Root X1. Python 3.13 checks that chain with OpenSSL. On Windows it also trusts
every certificate in the system store, including expired ones, and stops at the first
anchor it finds. An expired copy then fails the region list with "certificate has
expired". A store without ISRG Root X1 fails the download with "unable to get local
issuer certificate". The context below keeps unexpired system certificates and always
adds the two ISRG roots.
"""
from datetime import datetime, timezone
import ssl
import sys
import threading


# Public roots from https://letsencrypt.org/certificates/ (self-signed ISRG Root X1 and X2).
_ROOTS = """
-----BEGIN CERTIFICATE-----
MIIFazCCA1OgAwIBAgIRAIIQz7DSQONZRGPgu2OCiwAwDQYJKoZIhvcNAQELBQAw
TzELMAkGA1UEBhMCVVMxKTAnBgNVBAoTIEludGVybmV0IFNlY3VyaXR5IFJlc2Vh
cmNoIEdyb3VwMRUwEwYDVQQDEwxJU1JHIFJvb3QgWDEwHhcNMTUwNjA0MTEwNDM4
WhcNMzUwNjA0MTEwNDM4WjBPMQswCQYDVQQGEwJVUzEpMCcGA1UEChMgSW50ZXJu
ZXQgU2VjdXJpdHkgUmVzZWFyY2ggR3JvdXAxFTATBgNVBAMTDElTUkcgUm9vdCBY
MTCCAiIwDQYJKoZIhvcNAQEBBQADggIPADCCAgoCggIBAK3oJHP0FDfzm54rVygc
h77ct984kIxuPOZXoHj3dcKi/vVqbvYATyjb3miGbESTtrFj/RQSa78f0uoxmyF+
0TM8ukj13Xnfs7j/EvEhmkvBioZxaUpmZmyPfjxwv60pIgbz5MDmgK7iS4+3mX6U
A5/TR5d8mUgjU+g4rk8Kb4Mu0UlXjIB0ttov0DiNewNwIRt18jA8+o+u3dpjq+sW
T8KOEUt+zwvo/7V3LvSye0rgTBIlDHCNAymg4VMk7BPZ7hm/ELNKjD+Jo2FR3qyH
B5T0Y3HsLuJvW5iB4YlcNHlsdu87kGJ55tukmi8mxdAQ4Q7e2RCOFvu396j3x+UC
B5iPNgiV5+I3lg02dZ77DnKxHZu8A/lJBdiB3QW0KtZB6awBdpUKD9jf1b0SHzUv
KBds0pjBqAlkd25HN7rOrFleaJ1/ctaJxQZBKT5ZPt0m9STJEadao0xAH0ahmbWn
OlFuhjuefXKnEgV4We0+UXgVCwOPjdAvBbI+e0ocS3MFEvzG6uBQE3xDk3SzynTn
jh8BCNAw1FtxNrQHusEwMFxIt4I7mKZ9YIqioymCzLq9gwQbooMDQaHWBfEbwrbw
qHyGO0aoSCqI3Haadr8faqU9GY/rOPNk3sgrDQoo//fb4hVC1CLQJ13hef4Y53CI
rU7m2Ys6xt0nUW7/vGT1M0NPAgMBAAGjQjBAMA4GA1UdDwEB/wQEAwIBBjAPBgNV
HRMBAf8EBTADAQH/MB0GA1UdDgQWBBR5tFnme7bl5AFzgAiIyBpY9umbbjANBgkq
hkiG9w0BAQsFAAOCAgEAVR9YqbyyqFDQDLHYGmkgJykIrGF1XIpu+ILlaS/V9lZL
ubhzEFnTIZd+50xx+7LSYK05qAvqFyFWhfFQDlnrzuBZ6brJFe+GnY+EgPbk6ZGQ
3BebYhtF8GaV0nxvwuo77x/Py9auJ/GpsMiu/X1+mvoiBOv/2X/qkSsisRcOj/KK
NFtY2PwByVS5uCbMiogziUwthDyC3+6WVwW6LLv3xLfHTjuCvjHIInNzktHCgKQ5
ORAzI4JMPJ+GslWYHb4phowim57iaztXOoJwTdwJx4nLCgdNbOhdjsnvzqvHu7Ur
TkXWStAmzOVyyghqpZXjFaH3pO3JLF+l+/+sKAIuvtd7u+Nxe5AW0wdeRlN8NwdC
jNPElpzVmbUq4JUagEiuTDkHzsxHpFKVK7q4+63SM1N95R1NbdWhscdCb+ZAJzVc
oyi3B43njTOQ5yOf+1CceWxG1bQVs5ZufpsMljq4Ui0/1lvh+wjChP4kqKOJ2qxq
4RgqsahDYVvTH9w7jXbyLeiNdd8XM2w9U/t7y0Ff/9yi0GE44Za4rF2LN9d11TPA
mRGunUHBcnWEvgJBQl9nJEiU0Zsnvgc/ubhPgXRR4Xq37Z0j4r7g1SgEEzwxA57d
emyPxgcYxn/eR44/KJ4EBs+lVDR3veyJm+kXQ99b21/+jh5Xos1AnX5iItreGCc=
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIICGzCCAaGgAwIBAgIQQdKd0XLq7qeAwSxs6S+HUjAKBggqhkjOPQQDAzBPMQsw
CQYDVQQGEwJVUzEpMCcGA1UEChMgSW50ZXJuZXQgU2VjdXJpdHkgUmVzZWFyY2gg
R3JvdXAxFTATBgNVBAMTDElTUkcgUm9vdCBYMjAeFw0yMDA5MDQwMDAwMDBaFw00
MDA5MTcxNjAwMDBaME8xCzAJBgNVBAYTAlVTMSkwJwYDVQQKEyBJbnRlcm5ldCBT
ZWN1cml0eSBSZXNlYXJjaCBHcm91cDEVMBMGA1UEAxMMSVNSRyBSb290IFgyMHYw
EAYHKoZIzj0CAQYFK4EEACIDYgAEzZvVn4CDCuwJSvMWSj5cz3es3mcFDR0HttwW
+1qLFNvicWDEukWVEYmO6gbf9yoWHKS5xcUy4APgHoIYOIvXRdgKam7mAHf7AlF9
ItgKbppbd9/w+kHsOdx1ymgHDB/qo0IwQDAOBgNVHQ8BAf8EBAMCAQYwDwYDVR0T
AQH/BAUwAwEB/zAdBgNVHQ4EFgQUfEKWrt5LSDv6kviejM9ti6lyN5UwCgYIKoZI
zj0EAwMDaAAwZQIwe3lORlCEwkSHRhtFcP9Ymd70/aTSVaYgLXTWNLxBo1BfASdW
tL4ndQavEi51mI38AjEAi/V3bNTIZargCyzuFJ0nN6T5U6VR5CmD1/iQMVtCnwr1
/q4AaOeMSQ+2b1tbFfLn
-----END CERTIFICATE-----
"""

_lock = threading.Lock()
_context = None


def _der(data, offset):
    if offset + 2 > len(data):
        raise ValueError('truncated certificate')
    tag = data[offset]
    length = data[offset + 1]
    pos = offset + 2
    if length & 0x80:
        count = length & 0x7F
        if count == 0 or pos + count > len(data):
            raise ValueError('truncated certificate')
        length = int.from_bytes(data[pos:pos + count], 'big')
        pos += count
    end = pos + length
    if end > len(data):
        raise ValueError('truncated certificate')
    return tag, pos, end


def _time(tag, raw):
    text = raw.decode('ascii')
    if tag == 0x17:  # YYMMDDHHMMSSZ
        year = int(text[0:2])
        year += 2000 if year < 50 else 1900
        parts = (year, text[2:4], text[4:6], text[6:8], text[8:10], text[10:12])
    elif tag == 0x18:  # YYYYMMDDHHMMSSZ
        parts = (text[0:4], text[4:6], text[6:8], text[8:10], text[10:12], text[12:14])
    else:
        raise ValueError('not a certificate time')
    return datetime(*(int(part) for part in parts), tzinfo=timezone.utc)


def certificate_dates(der):
    """(not_before, not_after) from a DER certificate, or None when the layout is unfamiliar."""
    try:
        tag, start, _ = _der(der, 0)
        if tag != 0x30:
            return None
        tag, start, _ = _der(der, start)
        if tag != 0x30:
            return None
        tag, _, nxt = _der(der, start)
        if tag == 0xA0:  # version
            start = nxt
            tag, _, nxt = _der(der, start)
        if tag != 0x02:  # serial
            return None
        for _ in range(2):  # signature algorithm, issuer
            start = nxt
            tag, _, nxt = _der(der, start)
            if tag != 0x30:
                return None
        start = nxt
        tag, body, _ = _der(der, start)
        if tag != 0x30:
            return None
        first, a, b = _der(der, body)
        second, c, d = _der(der, b)
        return _time(first, der[a:b]), _time(second, der[c:d])
    except (ValueError, UnicodeError, IndexError):
        return None


def certificate_current(der, now=None):
    """False only when the certificate's dates are readable and it is outside them."""
    span = certificate_dates(der)
    if span is None:
        return True
    now = now or datetime.now(timezone.utc)
    return span[0] <= now < span[1]


def _load_system(ctx):
    if sys.platform != 'win32' or not hasattr(ssl, 'enum_certificates'):
        ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
        return
    purpose = ssl.Purpose.SERVER_AUTH.oid
    for storename in ('CA', 'ROOT'):
        try:
            entries = ssl.enum_certificates(storename)
        except PermissionError:
            continue
        for cert, encoding, trust in entries:
            if encoding != 'x509_asn':
                continue
            if trust is not True and purpose not in trust:
                continue
            if not certificate_current(cert):
                continue
            try:
                ctx.load_verify_locations(cadata=cert)
            except ssl.SSLError:
                continue


def build_context(system=True):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = True
    flags = 0
    for name in ('VERIFY_X509_PARTIAL_CHAIN', 'VERIFY_X509_STRICT', 'VERIFY_X509_TRUSTED_FIRST'):
        flags |= getattr(ssl, name, 0)
    if flags:
        ctx.verify_flags |= flags
    if system:
        _load_system(ctx)
    ctx.load_verify_locations(cadata=_ROOTS)
    return ctx


def context():
    """One shared client context. Building it reads the system store, so it is cached."""
    global _context
    with _lock:
        if _context is None:
            _context = build_context()
        return _context
