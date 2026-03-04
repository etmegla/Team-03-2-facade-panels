# Speckle Automate — Facade Panel Generator

FROM python:3.11-slim

WORKDIR /home/speckle

# Copy project files
COPY . /home/speckle

# Install Python dependencies
RUN pip install --no-cache-dir \
    rhino3dm \
    compute-rhino3d \
    specklepy \
    requests

# Run automation
CMD ["python", "-u", "main.py"]