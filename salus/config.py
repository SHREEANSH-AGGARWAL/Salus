"""
Salus ICP node configuration.

Loaded from YAML config files and environment variables using Pydantic Settings.
Defines all configurable parameters for a Salus Incident Command Post node.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RaftConfig(BaseSettings):
    """Raft consensus algorithm configuration.

    Timeouts are in milliseconds. Defaults are tuned for a local
    Docker cluster — production deployments over satellite/mesh radio
    should increase timeouts significantly.
    """

    # Election
    election_timeout_min_ms: int = Field(
        150, ge=50, description="Minimum election timeout (ms)"
    )
    election_timeout_max_ms: int = Field(
        300, ge=100, description="Maximum election timeout (ms) — randomized per node"
    )
    heartbeat_interval_ms: int = Field(
        50, ge=10, description="Leader heartbeat interval (ms) — must be << election timeout"
    )

    # Log
    max_log_entries_before_compaction: int = Field(
        10000, ge=100, description="Trigger log compaction after this many entries"
    )
    snapshot_chunk_size_bytes: int = Field(
        1024 * 1024, ge=1024, description="Snapshot transfer chunk size (bytes)"
    )

    # Quorum
    max_append_entries_batch: int = Field(
        100, ge=1, description="Max entries per AppendEntries RPC"
    )

    model_config = SettingsConfigDict(env_prefix="SALUS_RAFT_")


class GRPCConfig(BaseSettings):
    """gRPC inter-node communication settings."""

    host: str = Field("0.0.0.0", description="gRPC server bind address")
    port: int = Field(50051, ge=1024, le=65535, description="gRPC server port")
    max_message_size_bytes: int = Field(
        16 * 1024 * 1024, description="Max gRPC message size (16MB default)"
    )
    connect_timeout_ms: int = Field(5000, ge=100, description="Connection timeout (ms)")
    request_timeout_ms: int = Field(2000, ge=100, description="Per-request timeout (ms)")

    model_config = SettingsConfigDict(env_prefix="SALUS_GRPC_")


class APIConfig(BaseSettings):
    """FastAPI REST server settings."""

    host: str = Field("0.0.0.0", description="API server bind address")
    port: int = Field(8000, ge=1024, le=65535, description="API server port")
    workers: int = Field(1, ge=1, description="Uvicorn worker count")
    cors_origins: list[str] = Field(
        ["*"], description="Allowed CORS origins"
    )

    model_config = SettingsConfigDict(env_prefix="SALUS_API_")


class RAGConfig(BaseSettings):
    """RAG knowledge layer settings."""

    embedding_model: str = Field(
        "all-MiniLM-L6-v2", description="Sentence-transformer model name"
    )
    chroma_persist_dir: str = Field(
        "./data/chroma", description="ChromaDB persistence directory"
    )
    chunk_size: int = Field(1000, ge=100, description="Document chunk size (characters)")
    chunk_overlap: int = Field(200, ge=0, description="Chunk overlap (characters)")
    top_k: int = Field(5, ge=1, le=20, description="Number of chunks to retrieve")

    model_config = SettingsConfigDict(env_prefix="SALUS_RAG_")


class LLMConfig(BaseSettings):
    """LLM and agent pipeline settings."""

    provider: str = Field("openai", description="LLM provider: 'openai' or 'ollama'")
    model: str = Field("gpt-4o", description="Model name")
    ollama_base_url: str = Field(
        "http://localhost:11434", description="Ollama API base URL"
    )
    timeout_seconds: float = Field(
        5.0, ge=1.0, le=30.0,
        description="LLM timeout — triggers circuit-breaker fallback to rule-based dispatch"
    )
    temperature: float = Field(0.1, ge=0.0, le=2.0, description="LLM temperature")
    max_retries: int = Field(1, ge=0, le=3, description="LLM call retries before fallback")

    model_config = SettingsConfigDict(env_prefix="SALUS_LLM_")


class ClusterPeer(BaseSettings):
    """A peer ICP node in the Raft cluster."""

    node_id: str = Field(..., description="Unique node identifier")
    grpc_address: str = Field(..., description="gRPC endpoint (host:port)")
    api_address: str = Field("", description="REST API endpoint (host:port)")


class NodeConfig(BaseSettings):
    """Top-level configuration for a Salus ICP node.

    Combines all sub-configs. Loaded from environment variables
    (SALUS_ prefix) and optionally from a YAML config file.

    Each ICP node represents one agency's Incident Command Post
    in the disaster response coordination network.
    """

    # Node identity
    node_id: str = Field("node-1", description="This node's unique identifier")
    icp_name: str = Field("ICP Alpha", description="Incident Command Post display name")
    icp_code: str = Field("ICP-A", description="ICP short code")

    # Agency
    agency_name: str = Field("Fire Department", description="Agency operating this ICP")
    agency_type: str = Field("fire_department", description="Agency type identifier")

    # Cluster membership
    peers: list[ClusterPeer] = Field(
        default_factory=list,
        description="Other ICP nodes in the cluster",
    )

    # Sub-configs
    raft: RaftConfig = Field(default_factory=RaftConfig)
    grpc: GRPCConfig = Field(default_factory=GRPCConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)

    # Storage
    data_dir: str = Field("./data", description="Base data directory for this node")
    wal_dir: str = Field("./data/wal", description="Write-ahead log directory")

    model_config = SettingsConfigDict(
        env_prefix="SALUS_",
        env_nested_delimiter="__",
    )
