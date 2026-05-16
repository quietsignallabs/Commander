from __future__ import annotations

import ipaddress
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from commander.config import Settings


CERT_COMMON_NAME = "Commander Client Encryption"
PAIRING_PIN_TTL = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class ClientCertificateInfo:
    cert_path: Path
    key_path: Path
    fingerprint_sha256: str


def ensure_client_certificate(settings: Settings) -> ClientCertificateInfo:
    settings.ensure_directories()
    if not settings.client_tls_cert_path.exists() or not settings.client_tls_key_path.exists():
        _write_self_signed_certificate(settings.client_tls_cert_path, settings.client_tls_key_path)
    return ClientCertificateInfo(
        cert_path=settings.client_tls_cert_path,
        key_path=settings.client_tls_key_path,
        fingerprint_sha256=certificate_fingerprint(settings.client_tls_cert_path),
    )


def certificate_fingerprint(cert_path: Path) -> str:
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    digest = cert.fingerprint(hashes.SHA256()).hex().upper()
    return ":".join(digest[index : index + 2] for index in range(0, len(digest), 2))


def generate_pairing_pin(settings: Settings, *, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    pin = f"{secrets.randbelow(1_000_000):06d}"
    settings.client_pairing_pin = pin
    settings.client_pairing_pin_expires_at = (now + PAIRING_PIN_TTL).isoformat()
    settings.save_runtime_settings()
    return pin


def pairing_pin_is_valid(settings: Settings, supplied_pin: str, *, now: datetime | None = None) -> bool:
    if not settings.client_pairing_pin or not settings.client_pairing_pin_expires_at:
        return False
    if supplied_pin != settings.client_pairing_pin:
        return False
    now = now or datetime.now(UTC)
    expires_at = datetime.fromisoformat(settings.client_pairing_pin_expires_at)
    return now <= expires_at


def client_encryption_base_url(settings: Settings) -> str:
    return f"https://<server-ip>:{settings.client_encryption_port}"


def encrypted_uvicorn_kwargs(settings: Settings) -> dict[str, str | int]:
    cert_info = ensure_client_certificate(settings)
    return {
        "host": settings.host,
        "port": settings.client_encryption_port,
        "ssl_certfile": str(cert_info.cert_path),
        "ssl_keyfile": str(cert_info.key_path),
    }


def _write_self_signed_certificate(cert_path: Path, key_path: Path) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CERT_COMMON_NAME)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
