FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app.py /app/app.py
COPY load_test.py /app/load_test.py
COPY s3_inspect.py /app/s3_inspect.py
COPY otlp_summarize.py /app/otlp_summarize.py
COPY verify_stack.py /app/verify_stack.py

CMD ["python", "/app/app.py"]
