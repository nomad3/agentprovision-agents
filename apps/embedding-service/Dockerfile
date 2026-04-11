# Use latest Rust on bookworm to match the runtime image's GLIBC version
FROM rust:slim-bookworm AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    pkg-config libssl-dev protobuf-compiler libprotobuf-dev g++ \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Pre-download ONNX Runtime for fastembed load-dynamic
ARG ORT_VERSION=1.21.0
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "aarch64" ]; then ORT_ARCH="aarch64"; else ORT_ARCH="x64"; fi && \
    curl -sSL "https://github.com/microsoft/onnxruntime/releases/download/v${ORT_VERSION}/onnxruntime-linux-${ORT_ARCH}-${ORT_VERSION}.tgz" \
    | tar xz -C /opt && \
    mv /opt/onnxruntime-linux-* /opt/onnxruntime

WORKDIR /usr/src/embedding-service
COPY . .

ENV ORT_DYLIB_PATH=/opt/onnxruntime/lib/libonnxruntime.so
RUN cargo build --release

# Final runtime image
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y \
    openssl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy ONNX Runtime
COPY --from=builder /opt/onnxruntime/lib /usr/local/lib/ort/

# Copy binary
WORKDIR /usr/local/bin
COPY --from=builder /usr/src/embedding-service/target/release/embedding-service .

ENV ORT_DYLIB_PATH=/usr/local/lib/ort/libonnxruntime.so
ENV LD_LIBRARY_PATH=/usr/local/lib/ort

EXPOSE 50051
CMD ["./embedding-service"]
