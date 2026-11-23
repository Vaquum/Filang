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

# The shared Filang engine the bench asks everything of: the browser package of one published release, checked
# against that release's checksums. The bench has no engine of its own, so an image without it is not built.
ARG FILANG_ENGINE_VERSION
COPY bindings/fetch_browser.py /work/fetch_browser.py
RUN test -n "$FILANG_ENGINE_VERSION" || { echo "set FILANG_ENGINE_VERSION to the Filang release the bench runs on" >&2; exit 1; }; \
    python /work/fetch_browser.py "$FILANG_ENGINE_VERSION" --out /work/engine

# Stage two holds only what a browser asks for: the bench, the engine's browser package, and the recording.
FROM node:22-slim
WORKDIR /app
COPY study/data-provenance.json study/
# cube.mjs is the server's own: it reads Cube's bridge when CUBE_URL names one, and is never served.
COPY query/index.html query/serve.mjs query/cube.mjs query/
COPY query/bench query/bench
COPY query/shared query/shared
COPY --from=recording /work/data/recorded-bars.csv data/study/recorded-bars.csv
COPY --from=recording /work/engine engine
ENV PORT=8493 FILANG_QUERY_ENGINE_DIR=/app/engine
USER 65534:65534
CMD ["node", "query/serve.mjs"]
