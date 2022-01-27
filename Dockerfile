FROM ubuntu:20.04

RUN apt-get update && \
apt-get install -y --no-install-recommends \
    python3 python3-pip && \
rm -rf /var/lib/apt/lists/* && \
pip3 install --upgrade sultan

RUN pip3 install -U paho-mqtt asyncio smartrent.py
ADD ./smartrentmqttbridge.py /opt/smartrentmqttbridge.py
ENTRYPOINT ["python3", "/opt/smartrentmqttbridge.py"]
