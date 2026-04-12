#!/bin/sh
# Mosquitto entrypoint: hash plaintext passwords on first run, then start broker.
#
# If the password file contains plaintext entries (no $7$ prefix),
# mosquitto_passwd -U will hash them in-place.

PASSWD_FILE="/mosquitto/config/passwd"

if [ -f "$PASSWD_FILE" ]; then
    # Check if any line is NOT hashed (hashed lines start with username:$)
    if grep -qvE '^[^:]+:\$' "$PASSWD_FILE" 2>/dev/null; then
        echo "Hashing plaintext passwords in $PASSWD_FILE..."
        mosquitto_passwd -U "$PASSWD_FILE"
        echo "Passwords hashed."
    else
        echo "Password file already hashed."
    fi
else
    echo "WARNING: No password file found at $PASSWD_FILE"
    echo "Create one with: mosquitto_passwd -c -b $PASSWD_FILE <user> <pass>"
fi

exec mosquitto -c /mosquitto/config/mosquitto.conf
