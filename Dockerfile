FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY lisa ./lisa
COPY web ./web
COPY tenants ./tenants
ENV PYTHONPATH=/app
ENV PORT=8095
EXPOSE 8095
CMD ["uvicorn", "lisa.server:app", "--host", "0.0.0.0", "--port", "8095"]
