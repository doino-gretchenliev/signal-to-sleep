#!/bin/bash
# Generate TLS certificates for Signal-to-Sleep MQTT broker.
#
# Creates a self-signed CA + server certificate.
# Sensor Logger accepts self-signed certs when you toggle "TLS" in its MQTT settings.
#
# For production, replace these with certs from Let's Encrypt or another CA.
#
# Output directory: mosquitto/certs/

set -euo pipefail

CERT_DIR="$(dirname "$0")/../../mosquitto/certs"
mkdir -p "$CERT_DIR"

DAYS=3650  # 10 years for dev convenience
SUBJ_CA="/C=US/ST=CA/O=Signal-to-Sleep/CN=Signal-to-Sleep CA"
SUBJ_SERVER="/C=US/ST=CA/O=Signal-to-Sleep/CN=signal-to-sleep-mqtt"

# Allow passing server IP/hostname as argument for SAN
SERVER_HOST="${1:-localhost}"

echo "Generating TLS certificates in $CERT_DIR"
echo "  Server hostname/IP: $SERVER_HOST"
echo

# 1. CA key + cert
echo "[1/3] Generating CA..."
openssl genrsa -out "$CERT_DIR/ca.key" 2048 2>/dev/null
openssl req -new -x509 \
    -key "$CERT_DIR/ca.key" \
    -out "$CERT_DIR/ca.crt" \
    -days $DAYS \
    -subj "$SUBJ_CA" 2>/dev/null

# 2. Server key + CSR
echo "[2/3] Generating server key and CSR..."
openssl genrsa -out "$CERT_DIR/server.key" 2048 2>/dev/null

# Create SAN config for the server cert (important for WebSocket TLS validation)
cat > "$CERT_DIR/server.cnf" << EOF
[req]
default_bits = 2048
prompt = no
distinguished_name = dn
req_extensions = v3_req

[dn]
C = US
ST = CA
O = Signal-to-Sleep
CN = $SERVER_HOST

[v3_req]
subjectAltName = @alt_names

[alt_names]
DNS.1 = $SERVER_HOST
DNS.2 = localhost
DNS.3 = mosquitto
IP.1 = 127.0.0.1
EOF

openssl req -new \
    -key "$CERT_DIR/server.key" \
    -out "$CERT_DIR/server.csr" \
    -config "$CERT_DIR/server.cnf" 2>/dev/null

# 3. Sign server cert with CA
echo "[3/3] Signing server certificate..."
openssl x509 -req \
    -in "$CERT_DIR/server.csr" \
    -CA "$CERT_DIR/ca.crt" \
    -CAkey "$CERT_DIR/ca.key" \
    -CAcreateserial \
    -out "$CERT_DIR/server.crt" \
    -days $DAYS \
    -extensions v3_req \
    -extfile "$CERT_DIR/server.cnf" 2>/dev/null

# Clean up intermediate files
rm -f "$CERT_DIR/server.csr" "$CERT_DIR/server.cnf" "$CERT_DIR/ca.srl"

# Set permissions
chmod 644 "$CERT_DIR/ca.crt" "$CERT_DIR/server.crt"
chmod 600 "$CERT_DIR/ca.key" "$CERT_DIR/server.key"

echo
echo "Certificates generated:"
echo "  CA cert:     $CERT_DIR/ca.crt"
echo "  Server cert: $CERT_DIR/server.crt"
echo "  Server key:  $CERT_DIR/server.key"
echo
echo "To verify:"
echo "  openssl verify -CAfile $CERT_DIR/ca.crt $CERT_DIR/server.crt"
