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

# Create exports and imports directories (overridden by bind mounts at runtime)
RUN mkdir -p /exports /imports

ENV PYTHONPATH=/app/deps

EXPOSE 8090

# Run as non-root user. If you get permission errors on /imports or /exports,
# ensure the host directories are writable (chmod 777 or chown to UID 1000).
USER appuser

ENTRYPOINT ["python", "-m", "influencers_club_mcp"]
