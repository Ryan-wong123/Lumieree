# Dockerfile for Railway deployment with pyzbar + zbar support

FROM python:3.11-slim

# Install zbar shared library and build essentials
RUN apt-get update && \
    apt-get install -y zbar-tools libzbar0 gcc && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy all files
COPY . .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run Flask app with Gunicorn on port 8080
CMD ["gunicorn", "-b", "0.0.0.0:8080", "app:app"]
