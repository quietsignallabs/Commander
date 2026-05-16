# Commander Client Encryption for iPhone

## Overview

Commander can optionally expose a second HTTPS endpoint for iPhone clients. The default server remains HTTP on port `6767`; Client Encryption adds HTTPS on port `6768` by default.

The HTTPS endpoint uses a locally generated self-signed certificate. iOS will not trust that certificate automatically. The iPhone app must pair with Commander, pin the certificate fingerprint, and then reject future connections if the certificate changes.

Relevant Apple APIs:

- `URLSession` for HTTPS requests.
- `URLSessionDelegate` / authentication challenges for certificate evaluation.
- Keychain for storing the pinned certificate fingerprint and API token.
- CryptoKit is not required for the transport encryption because TLS provides the encryption.

Apple documentation:

- App Transport Security: https://developer.apple.com/documentation/BundleResources/Information-Property-List/NSAppTransportSecurity
- Certificate pinning configuration: https://developer.apple.com/documentation/bundleresources/information-property-list/nsapptransportsecurity/nspinneddomains
- CryptoKit overview: https://developer.apple.com/documentation/cryptokit

## Server Setup

1. Open Commander Settings.
2. Enable **Client Encryption**.
3. Keep the encrypted port at `6768` unless that port is already in use.
4. Save Settings.
5. Note the encrypted URL:

```text
https://<server-ip>:6768
```

6. Note the certificate SHA-256 fingerprint shown in Settings.
7. Click **Generate Pairing PIN** when pairing a new iPhone.

The pairing PIN is valid for 10 minutes. Generate a new PIN if it expires.

## iPhone Pairing Flow

The app should have a pairing screen with:

- Server IP or hostname.
- Encrypted port, default `6768`.
- Pairing PIN.
- Optional Commander API token.

During pairing:

1. Build the encrypted base URL from the entered host and port.
2. Create a temporary `URLSession` with a delegate that handles the self-signed certificate.
3. For the pairing request only, allow the TLS challenge to continue after extracting the server certificate.
4. Compute the SHA-256 fingerprint of the leaf certificate.
5. Send the PIN to:

```http
POST /api/client-encryption/pair
Content-Type: application/json

{
  "pin": "123456"
}
```

6. Confirm the server response fingerprint matches the certificate fingerprint observed during the TLS challenge.
7. Store the base URL and pinned fingerprint in Keychain.
8. Use normal pinned HTTPS requests for all future Commander API calls.

Successful response:

```json
{
  "base_url": "https://<server-ip>:6768",
  "certificate_fingerprint_sha256": "AA:BB:CC:..."
}
```

If the server returns `401`, show:

```text
The pairing PIN is invalid or expired.
```

If the certificate fingerprint from the TLS challenge does not match the server response, do not store the pairing. Show:

```text
Commander certificate verification failed. Check the server address and try pairing again.
```

## Trust Challenge Rules

After pairing, the app must not generally trust self-signed certificates. It should trust only the pinned Commander certificate fingerprint.

Recommended behavior:

- For unpaired servers, allow a temporary trust challenge only while calling `/api/client-encryption/pair`.
- For paired servers, compute the presented leaf certificate SHA-256 fingerprint.
- If the fingerprint matches the stored pin, allow the request.
- If it does not match, cancel the request and require re-pairing.

Do not disable certificate validation globally. Do not accept every self-signed certificate.

## Swift Fingerprint Sketch

This is a minimal outline. Adapt error handling and storage to the app's architecture.

```swift
final class CommanderPinnedSessionDelegate: NSObject, URLSessionDelegate {
    let expectedFingerprint: String?
    let pairingMode: Bool
    var observedFingerprint: String?

    init(expectedFingerprint: String?, pairingMode: Bool) {
        self.expectedFingerprint = expectedFingerprint
        self.pairingMode = pairingMode
    }

    func urlSession(
        _ session: URLSession,
        didReceive challenge: URLAuthenticationChallenge,
        completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void
    ) {
        guard
            challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
            let trust = challenge.protectionSpace.serverTrust,
            let certificate = SecTrustGetCertificateAtIndex(trust, 0)
        else {
            completionHandler(.cancelAuthenticationChallenge, nil)
            return
        }

        let data = SecCertificateCopyData(certificate) as Data
        let fingerprint = sha256Fingerprint(data)
        observedFingerprint = fingerprint

        if pairingMode {
            completionHandler(.useCredential, URLCredential(trust: trust))
            return
        }

        if fingerprint == expectedFingerprint {
            completionHandler(.useCredential, URLCredential(trust: trust))
        } else {
            completionHandler(.cancelAuthenticationChallenge, nil)
        }
    }
}
```

Use CryptoKit or CommonCrypto to compute SHA-256. Format it as uppercase hex pairs separated by colons to match Commander:

```text
AA:BB:CC:DD
```

## API Authentication

Client Encryption does not replace Commander API token authentication. If API auth is enabled, keep sending:

```http
X-Commander-Token: <token>
```

Store the token in Keychain. Do not log the token, pairing PIN, stdout, or stderr.

## App Transport Security

The encrypted endpoint uses HTTPS, but the certificate is self-signed. The app still needs custom trust handling for the pinned certificate.

If the app also supports the default HTTP server for non-encrypted mode, configure a narrow local-network ATS allowance rather than disabling ATS globally. Prefer the encrypted endpoint for normal iPhone use.

## Re-Pairing

Require re-pairing when:

- Commander regenerates its certificate.
- The Windows user deletes `data/client-encryption-cert.pem` or `data/client-encryption-key.pem`.
- The app detects a certificate fingerprint mismatch.
- The user changes to a different Commander server.

On re-pairing, replace the old pinned fingerprint only after a successful PIN pairing response and matching TLS-observed fingerprint.
