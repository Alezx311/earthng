"""Builder HTTPS: unexpired system anchors plus the bundled ISRG roots."""
import base64
import ssl
import unittest
from datetime import datetime, timezone

import tls


def tlv(tag, body):
    size = len(body)
    if size < 128:
        length = bytes([size])
    elif size < 256:
        length = bytes([0x81, size])
    else:
        length = bytes([0x82, size // 256, size % 256])
    return bytes([tag]) + length + body


def certificate(not_before, not_after):
    """A DER certificate whose validity the reader can see. The signature is not real."""
    version = tlv(0xA0, tlv(0x02, b'\x02'))
    serial = tlv(0x02, b'\x01')
    algorithm = tlv(0x30, tlv(0x06, b'\x2a'))
    name = tlv(0x30, tlv(0x31, b'\x00'))
    validity = tlv(0x30, tlv(0x17, not_before) + tlv(0x17, not_after))
    body = tlv(0x30, version + serial + algorithm + name + validity)
    return tlv(0x30, body + algorithm + tlv(0x03, b'\x00'))


def pem_bodies(text):
    chunks, collecting, lines = [], False, []
    for line in text.splitlines():
        if 'BEGIN CERTIFICATE' in line:
            collecting, lines = True, []
        elif 'END CERTIFICATE' in line:
            chunks.append(base64.b64decode(''.join(lines)))
            collecting = False
        elif collecting:
            lines.append(line.strip())
    return chunks


class TlsTests(unittest.TestCase):
    def test_reader_sees_the_bundled_isrg_roots(self):
        spans = [tls.certificate_dates(der) for der in pem_bodies(tls._ROOTS)]
        self.assertEqual(len(spans), 2)
        endings = sorted(span[1] for span in spans)
        self.assertEqual(endings[0].year, 2035)  # ISRG Root X1
        self.assertEqual(endings[1].year, 2040)  # ISRG Root X2

    def test_an_expired_certificate_is_not_trusted(self):
        expired = certificate(b'150101000000Z', b'200101000000Z')
        current = certificate(b'200101000000Z', b'350101000000Z')
        self.assertFalse(tls.certificate_current(expired, datetime(2026, 10, 24, tzinfo=timezone.utc)))
        self.assertTrue(tls.certificate_current(current, datetime(2026, 10, 24, tzinfo=timezone.utc)))
        self.assertTrue(tls.certificate_current(b'not a certificate'))

    def test_context_trusts_isrg_and_drops_expired_anchors(self):
        ctx = tls.build_context()
        certs = ctx.get_ca_certs()
        names = [value for cert in certs for rdn in cert['subject'] for _, value in rdn]
        self.assertIn('ISRG Root X1', names)
        self.assertIn('ISRG Root X2', names)
        now = datetime.now(timezone.utc)
        for cert in certs:
            expiry = datetime.fromtimestamp(ssl.cert_time_to_seconds(cert['notAfter']), timezone.utc)
            self.assertGreater(expiry, now, cert['subject'])

    def test_bundled_roots_alone_verify_geofabrik(self):
        # The chain Geofabrik sends ends at a cross-sign of ISRG Root X2 by ISRG Root X1.
        # A machine whose system store has neither root still has to open the index.
        ctx = tls.build_context(system=False)
        self.assertEqual(len(ctx.get_ca_certs()), 2)
        import socket
        host = 'download.geofabrik.de'
        with socket.create_connection((host, 443), timeout=20) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as connected:
                self.assertEqual(connected.getpeercert()['subject'][0][0][1], host)


if __name__ == '__main__':
    unittest.main()
