# RL Inference Container
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements (minimal for inference)
COPY requirements-inference.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements-inference.txt

# Copy source code
COPY src/ ./src/
COPY config/ ./config/

# Create necessary directories
RUN mkdir -p /app/logs /app/models

# Set environment variables
ENV PYTHONPATH=/app
ENV INFERENCE_MODE=true

# Health check
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import src.rl.health_check; src.rl.health_check.check_inference_health()" || exit 1

# Expose port for health checks and metrics
EXPOSE 8080

# Default command
CMD ["python", "-m", "src.rl.inference.server"]