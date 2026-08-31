FROM python:3.12-slim

WORKDIR /app

# System dependencies for gRPC compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]" 2>/dev/null || pip install --no-cache-dir .

# Copy application code
COPY . .

# Install the package
RUN pip install --no-cache-dir -e .

# Expose ports: gRPC (50051) + REST API (8000)
EXPOSE 50051 8000

# Health check via REST API
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health')" || exit 1

# Default entrypoint — starts a single ICP node
ENTRYPOINT ["python", "-m", "salus.main"]
