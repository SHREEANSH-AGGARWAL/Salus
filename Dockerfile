# Multi-stage Dockerfile for Salus ICP Node daemon
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast wheel building
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy project definition and source
COPY pyproject.toml README.md ./
COPY proto/ proto/
COPY salus/ salus/
COPY simulation/ simulation/

# Compile proto files
RUN uv pip install --system grpcio-tools && \
    python -m grpc_tools.protoc -Iproto --python_out=salus/grpc --grpc_python_out=salus/grpc proto/raft.proto && \
    sed -i 's/import raft_pb2 as raft__pb2/from salus.grpc import raft_pb2 as raft__pb2/' salus/grpc/raft_pb2_grpc.py

# Install package
RUN uv pip install --system --no-cache .

# Production runtime stage
FROM python:3.12-slim AS runner

WORKDIR /app

RUN groupadd -r salus && useradd -r -g salus salus

# Copy installed packages and bin from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/salus-node /usr/local/bin/salus-node
COPY --from=builder /usr/local/bin/salus-simulate /usr/local/bin/salus-simulate
COPY --from=builder /build/salus /app/salus
COPY --from=builder /build/proto /app/proto

# Create data directory
RUN mkdir -p /app/data/wal && chown -R salus:salus /app

USER salus

# Ports: gRPC (50051), REST/WebSocket (8000)
EXPOSE 50051 8000

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["salus-node"]
