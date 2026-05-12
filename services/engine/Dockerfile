FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY localsignal_engine ./localsignal_engine

CMD ["python", "-m", "localsignal_engine.run_demo"]
