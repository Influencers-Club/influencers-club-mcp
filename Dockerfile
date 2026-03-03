FROM python:3.12-slim-bookworm AS builder

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY influencers_club_mcp/ ./influencers_club_mcp/

RUN pip install --no-cache-dir --target /app/deps .

FROM python:3.12-slim-bookworm

WORKDIR /app

COPY --from=builder /app/deps /app/deps
COPY --from=builder /app/influencers_club_mcp /app/influencers_club_mcp

ENV PYTHONPATH=/app/deps

ENTRYPOINT ["python", "-m", "influencers_club_mcp"]
