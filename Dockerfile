# Speckle Automate — Facade Panel Generator
# Runs on Speckle's Linux infrastructure (CPU-only, no GPU required).

FROM python:3.11-slim

WORKDIR /home/speckle

# Install dependencies first (Docker layer cache)
COPY pyproject.toml /home/speckle/

RUN pip install --no-cache-dir .

# Copy source
COPY . /home/speckle

CMD ["python", "-u", "main.py"]