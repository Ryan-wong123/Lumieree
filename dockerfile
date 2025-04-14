FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y \
    zbar-tools \
    libzbar0 \
    gcc \
    build-essential && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy code
COPY . .

# Install Python dependencies
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Expose port for Railway
EXPOSE 8080

# Run app with Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app"]
