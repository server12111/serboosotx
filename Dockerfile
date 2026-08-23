FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 boosty \
    && mkdir -p /app/data \
    && chown -R boosty:boosty /app
USER boosty

VOLUME /app/data

CMD ["python", "run.py"]
