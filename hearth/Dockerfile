# Pinned base rather than a Railway buildpack, so a redeploy in three months builds the
# same image. The model itself is not a pickle -- it is a coefficient lookup in
# model.json, scored by pure numpy -- so scikit-learn never enters this image and the
# serving runtime is not coupled to the one that fitted it.
FROM python:3.14-slim

WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY src/features.py src/scorer.py ./src/
# The offline rep tool, served at /tool. Self-contained -- the container does not
# score it, it just hands the file over.
COPY tool/lead_queue.html ./tool/

# Only the three artifacts the dashboard actually serves. The raw pack -- leads_history,
# activities, the call tables, the transcripts -- never enters the image. What ships is
# the scoring window's intake columns, the exported model, and precomputed aggregates.
# model.json is byte-for-byte the file submission.csv and the browser tool were built from.
COPY output/app_data/leads.parquet output/app_data/analytics.json output/app_data/model.json ./output/app_data/
# Historical bundle for the /tool Historical tab. Served only behind auth.
COPY output/app_data/historical.json.gz ./output/app_data/
ENV APP_DATA_DIR=/srv/output/app_data

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
