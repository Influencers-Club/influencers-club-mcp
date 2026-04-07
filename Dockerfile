FROM python:3.12-slim-bookworm AS builder

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY influencers_club_mcp/ ./influencers_club_mcp/

RUN pip install --no-cache-dir --target /app/deps .

FROM python:3.12-slim-bookworm

RUN groupadd --system appgroup && \
    useradd --system --gid appgroup --create-home --shell /bin/false appuser

WORKDIR /app

COPY --from=builder /app/deps /app/deps
COPY --from=builder /app/influencers_club_mcp /app/influencers_club_mcp

# Create exports and imports directories
RUN mkdir -p /exports /imports && chown appuser:appgroup /exports /imports

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PYTHONPATH=/app/deps

EXPOSE 8090

# Start as root so entrypoint can fix volume permissions, then drop to appuser
ENTRYPOINT ["/entrypoint.sh"]
