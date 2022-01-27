FROM python:3-slim

WORKDIR /usr/src/app

RUN pip install --no-cache-dir paho-mqtt asyncio smartrent.py

COPY ./smartrentmqttbridge.py .
ENTRYPOINT ["python", "-u"]
CMD ["./smartrentmqttbridge.py"]

