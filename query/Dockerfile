# Filang query bench. Build from the repository root:
#   docker build -f query/Dockerfile -t query .
#
# Stage one recreates the pinned BTCUSDT 15m recording exactly as CI does: the Limen fixture and the Composer
# encoder at their pinned commits, read by study/prepare_recording.py, which refuses any byte that differs
# from study/data-provenance.json and study/recording-lock.json. The recording is never taken on trust.
FROM python:3.12-slim AS recording
RUN pip install --no-cache-dir polars==1.42.1 pyarrow==23.0.1
ADD https://raw.githubusercontent.com/Vaquum/Limen/383d4accbfa20fe062cd09de83e265886542aa8f/tests/fixtures/spot_15m_20250101_20250531.parquet /work/source.parquet
ADD https://raw.githubusercontent.com/Vaquum/Composer/133e3017ba9143f7dc255df7218ff7bfe46d9d06/bars.py /work/bars.py
WORKDIR /work/study
COPY study/prepare_recording.py study/data-provenance.json study/recording-lock.json ./
RUN FILANG_STUDY_DATA=/work/data python prepare_recording.py --parquet /work/source.parquet --encoder /work/bars.py

# Stage two holds only what a browser asks for: the bench, the engine modules it imports, and the recording.
FROM node:22-slim
WORKDIR /app
COPY study/src study/src
COPY study/composer/patterns.js study/composer/patterns.js
COPY study/extensions study/extensions
COPY study/data-provenance.json study/nyse-sessions.json study/
COPY query/index.html query/serve.mjs query/
COPY query/bench query/bench
COPY query/shared query/shared
COPY --from=recording /work/data/recorded-bars.csv data/study/recorded-bars.csv
ENV PORT=8493
USER 65534:65534
CMD ["node", "query/serve.mjs"]
