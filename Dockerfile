# aha-paper needs three things the base image does not have together: a Python
# runtime, a Node runtime (scripts/pi-models.mjs reads the provider catalogue
# through @earendil-works/pi-ai), and ffmpeg/ffprobe for the narration track.
#
# Starting from the Node image and adding Debian's own Python keeps this to one
# apt install with no third-party package sources.
FROM node:22-bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# Debian marks the system interpreter externally managed, so the app gets its own.
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN python3 -m venv "$VIRTUAL_ENV"

WORKDIR /app

# Dependencies before source: editing a .py file must not reinstall onnxruntime.
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --omit=dev

COPY . .

# The only paths written at runtime. Both are volumes: papers and everything
# generated from them, and the credential store, which must outlive the image.
RUN mkdir -p data .runtime && chown -R node:node /app
VOLUME ["/app/data", "/app/.runtime"]

ENV PI_CREDENTIAL_FILE=/app/.runtime/credentials.json
USER node
EXPOSE 8321

# No curl in the slim image; the interpreter is already here.
# /api/ping, not /api/health: with AHA_ACCESS_PASSWORD set, the gate answers
# /api/health with a 401 and the container is restarted forever while it is
# serving perfectly well. /api/ping is open on purpose and says only {ok}.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python3 -c "import os,urllib.request,sys; p=os.environ.get('PORT','8321'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{p}/api/ping',timeout=4).status==200 else 1)"

# Railway, Render and Fly hand the port in through $PORT; 8321 is the local
# default. exec keeps uvicorn as PID 1 so the platform can stop it cleanly.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8321}"]
