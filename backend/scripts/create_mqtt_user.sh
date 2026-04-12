#!/bin/bash
# Create or update MQTT user credentials for Mosquitto.
#
# Usage:
#   ./create_mqtt_user.sh <username> <password>
#
# Writes hashed credentials to mosquitto/passwd
# Mosquitto uses this file for authentication.

set -euo pipefail

if [ $# -lt 2 ]; then
    echo "Usage: $0 <username> <password>"
    echo "Example: $0 sleeptracker mysecretpassword"
    exit 1
fi

USERNAME="$1"
PASSWORD="$2"
PASSWD_FILE="$(dirname "$0")/../mosquitto/passwd"

# Create the password file entry
# Format: username:password (will be hashed by mosquitto_passwd if available)
mkdir -p "$(dirname "$PASSWD_FILE")"

# Check if mosquitto_passwd is available (it is in the Docker container)
if command -v mosquitto_passwd &>/dev/null; then
    if [ -f "$PASSWD_FILE" ]; then
        mosquitto_passwd -b "$PASSWD_FILE" "$USERNAME" "$PASSWORD"
    else
        mosquitto_passwd -c -b "$PASSWD_FILE" "$USERNAME" "$PASSWORD"
    fi
    echo "User '$USERNAME' added with hashed password to $PASSWD_FILE"
else
    # Fallback: create a plaintext file that will be hashed on first broker start
    # Mosquitto will hash it when using `mosquitto_passwd -U`
    if [ -f "$PASSWD_FILE" ]; then
        # Remove existing entry for this user
        grep -v "^${USERNAME}:" "$PASSWD_FILE" > "${PASSWD_FILE}.tmp" || true
        mv "${PASSWD_FILE}.tmp" "$PASSWD_FILE"
    fi
    echo "${USERNAME}:${PASSWORD}" >> "$PASSWD_FILE"
    echo "User '$USERNAME' added (plaintext) to $PASSWD_FILE"
    echo "Run inside Docker: mosquitto_passwd -U /mosquitto/config/passwd"
    echo "  to hash the passwords."
fi

chmod 600 "$PASSWD_FILE"
