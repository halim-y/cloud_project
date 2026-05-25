# app/Dockerfile

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt ./
COPY ./main.py ./
COPY services/weather.py ./
COPY services/database.py ./
COPY services/voice.py ./
COPY services/audio.py ./
COPY services/announcements.py ./

RUN pip3 install -r requirements.txt


ENTRYPOINT ["python"]
CMD ["main.py"]
