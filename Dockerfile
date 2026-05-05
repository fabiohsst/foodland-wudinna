# Foodland Wudinna — Order App
# Builds a Python environment with all dependencies.
# The project folder is mounted as a volume at runtime,
# so code and data updates don't require a rebuild.

FROM python:3.10-slim

# Install OS-level dependencies for openpyxl / lightgbm
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only requirements first — this layer is cached until requirements change
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

EXPOSE 8501

CMD ["python", "-m", "streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
