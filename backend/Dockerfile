# app/Dockerfile

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt ./
RUN pip3 install -r requirements.txt

COPY ./main.py ./
RUN mkdir -p backend/services
RUN touch backend/__init__.py backend/services/__init__.py
COPY services/weather.py       backend/services/weather.py
COPY services/database.py      backend/services/database.py
COPY services/voice.py         backend/services/voice.py
COPY services/audio.py         backend/services/audio.py
COPY services/announcements.py backend/services/announcements.py

# main.py imports via `backend.services.*` (package-style).
# Service files import each other with flat names (`from weather import ...`).
# PYTHONPATH makes both work without changing any source file.
ENV PYTHONPATH=/app/backend/services

ENTRYPOINT ["python"]
CMD ["main.py"]
