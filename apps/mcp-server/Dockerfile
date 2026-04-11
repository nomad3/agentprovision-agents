FROM mcr.microsoft.com/playwright/python:v1.50.0-noble

WORKDIR /app

# Create non-root user (use high UID/GID to avoid conflicts with base image)
RUN groupadd -g 2001 mcpuser && \
    useradd -r -u 2001 -g mcpuser -m mcpuser

# Install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir --break-system-packages .

# Copy source
COPY src/ src/
COPY .env.example .env

# Set ownership
RUN chown -R mcpuser:mcpuser /app

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8086/agentprovision/v1/health || exit 1

# Expose MCP port
EXPOSE 8086

# Run as non-root
USER mcpuser

# Run server
CMD ["python", "-m", "src.server"]
