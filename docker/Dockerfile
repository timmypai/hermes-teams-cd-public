# Official Python 3.13.18 slim-bookworm linux/arm64/v8 manifest.
# Manifest sha256 and its linux/arm64 config independently verified before pinning.
# The build context is the exact approved application checkout, NOT the helper repo.
FROM python@sha256:aed314f1f0c7e988b7aee5d889414ec977430bad37770966c52aff5366a13a06
WORKDIR /app
COPY apps/sevenbot-flow-probe/server.py /app/server.py
USER 65532:65532
# -I ignores ambient Python configuration; -B avoids writes on read-only runtime.
# No default source identity: the application requires explicit --source-sha.
ENTRYPOINT ["python3", "-I", "-B", "/app/server.py"]
