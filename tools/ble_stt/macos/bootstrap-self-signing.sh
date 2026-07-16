#!/bin/bash
set -euo pipefail

REPOSITORY="${REPOSITORY:-aporicho/M5StopWatch-UserDemo}"
VALID_DAYS="${VALID_DAYS:-3650}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/m5stopwatch-signing.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT HUP INT TERM

for command_name in openssl gh; do
    command -v "$command_name" >/dev/null 2>&1 \
        || { printf '%s is required.\n' "$command_name" >&2; exit 1; }
done
gh auth status >/dev/null

PASSWORD="$(openssl rand -hex 24)"
cat >"$WORK/certificate.cnf" <<'EOF'
[req]
distinguished_name = subject
x509_extensions = extensions
prompt = no

[subject]
CN = M5StopWatch Local Code Signing
O = aporicho
OU = Local Release

[extensions]
basicConstraints = critical,CA:TRUE
keyUsage = critical,digitalSignature,keyCertSign
extendedKeyUsage = codeSigning
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always
EOF

openssl req -new -newkey rsa:3072 -nodes -x509 -sha256 \
    -days "$VALID_DAYS" \
    -config "$WORK/certificate.cnf" \
    -keyout "$WORK/signing.key" \
    -out "$WORK/signing.pem"
openssl pkcs12 -export \
    -legacy \
    -inkey "$WORK/signing.key" \
    -in "$WORK/signing.pem" \
    -name 'M5StopWatch Local Code Signing' \
    -passout "pass:$PASSWORD" \
    -out "$WORK/signing.p12"
openssl x509 -in "$WORK/signing.pem" -outform DER -out "$WORK/signing.der"
FINGERPRINT="$(shasum -a 256 "$WORK/signing.der" | awk '{print toupper($1)}')"

base64 <"$WORK/signing.p12" | gh secret set MACOS_SIGNING_P12_BASE64 --repo "$REPOSITORY"
printf '%s' "$PASSWORD" | gh secret set MACOS_SIGNING_P12_PASSWORD --repo "$REPOSITORY"
gh variable set MACOS_SIGNING_CERT_SHA256 --repo "$REPOSITORY" --body "$FINGERPRINT"

# Optional one-time local export for validating the exact same identity before
# publishing. Keep this outside the repository and delete it after the test.
if [ -n "${BLE_STT_SIGNING_EXPORT_DIR:-}" ]; then
    mkdir -p "$BLE_STT_SIGNING_EXPORT_DIR"
    chmod 700 "$BLE_STT_SIGNING_EXPORT_DIR"
    cp "$WORK/signing.p12" "$BLE_STT_SIGNING_EXPORT_DIR/signing.p12"
    cp "$WORK/signing.pem" "$BLE_STT_SIGNING_EXPORT_DIR/signing.pem"
    printf '%s' "$PASSWORD" >"$BLE_STT_SIGNING_EXPORT_DIR/password"
    chmod 600 \
        "$BLE_STT_SIGNING_EXPORT_DIR/signing.p12" \
        "$BLE_STT_SIGNING_EXPORT_DIR/signing.pem" \
        "$BLE_STT_SIGNING_EXPORT_DIR/password"
fi

printf '\nConfigured persistent local signing for %s.\n' "$REPOSITORY"
printf 'Certificate SHA-256: %s\n' "$FINGERPRINT"
printf 'Keep this fingerprint in release records; the private key was not written to the repository.\n'
if [ -n "${BLE_STT_SIGNING_EXPORT_DIR:-}" ]; then
    printf 'Temporary local validation copy: %s (delete it after validation).\n' "$BLE_STT_SIGNING_EXPORT_DIR"
fi
