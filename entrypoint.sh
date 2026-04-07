#!/bin/sh
# Fix ownership of mounted volumes, then drop to non-root user
# On macOS Docker Desktop, bind mounts may not support chown — use chmod as fallback
chown appuser:appgroup /imports /exports 2>/dev/null || true
chmod 777 /imports /exports 2>/dev/null || true

# Verify write access; if still read-only, warn but continue
if ! su -s /bin/sh appuser -c "touch /imports/.write_test 2>/dev/null && rm /imports/.write_test"; then
    echo "WARNING: /imports is not writable by appuser — uploads may fail" >&2
fi

exec su -s /bin/sh appuser -c "python -m influencers_club_mcp"
