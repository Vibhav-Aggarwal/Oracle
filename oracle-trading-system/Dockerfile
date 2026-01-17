FROM python:3.11-slim

# Create non-root user
RUN groupadd -r oracle && useradd -r -g oracle oracle

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY src/ ./src/
COPY config/ ./config/

# Create directories and set permissions
RUN mkdir -p /app/logs /app/data && chown -R oracle:oracle /app

# Set Python path
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run as non-root
USER oracle

# Expose metrics port
EXPOSE 8080

# Entry point
CMD ["python3", "-m", "src.main"]
