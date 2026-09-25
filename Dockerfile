FROM python:3.12-slim-bookworm
COPY . /opt/hehelohe
WORKDIR /opt/hehelohe
RUN pip install --no-cache-dir .
ENTRYPOINT ["hehelohe"]
