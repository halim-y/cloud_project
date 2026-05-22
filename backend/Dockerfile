# app/Dockerfile

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt ./
COPY ./main.py ./
COPY ./weather.py ./
COPY ./database.py ./
COPY ./voice.py ./
COPY ./audio.py ./
COPY ./announcements.py ./

RUN pip3 install -r requirements.txt


ENTRYPOINT ["python"]
CMD ["main.py"]
