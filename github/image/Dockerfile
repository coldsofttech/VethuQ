# syntax=docker/dockerfile:1.7
# The worker image, in variants (packages/worker/src/vethuq_worker/variants.py): vethuq-worker,
# VethuQ and the add-ons a variant carries, for GitHub runners.
#
# Built by .github/workflows/github-image.yml, never by hand: the build context holds `wheels/`
# (every wheel any variant installs, built from the checked-out sources and gated for shipping) and
# `lists/` (`base.txt`, and one `<variant>.txt` of the add-ons beyond it). The add-on wheels are
# compiled and licence-gated at runtime; the image is public, so it carries no secret, token or key.
#
# The OCR models are NOT in the image. The build downloads them once to prove every engine loads and
# records each file's size and sha256 in `models.lock.json`, which stays; the models don't. A runner
# downloads them on its first job (`vethuq-worker fetch-models`, the one step with a network, run
# without the job's key or payload), keeps them in a cache, and the worker checks every file against
# the lock before it reads a page. The job itself runs with no network.
#
#   docker build --build-arg VARIANT=slim -t vethuq-worker:slim context/
#
# Stages: `os` (the system libraries), `base` (every variant starts from this one, so its layers are
# shared between variants), `variant` (adds the variant's own add-ons), `locked` (downloads the
# models to write the lock) and `final`.

FROM python:3.12-slim-bookworm AS os

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/opt/venv/bin:$PATH \
    HOME=/tmp

# Shared libraries the OCR engine's image and maths wheels load. Nothing else: no documentation,
# manual pages or locales.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt /usr/share/doc /usr/share/man /usr/share/info \
              /usr/share/locale /usr/share/lintian

FROM os AS base
# What every variant has: the worker, the entitlements runtime, what VethuQ itself requires, and
# every language. The environment has no pip of its own: the system pip installs into it.
RUN --mount=type=bind,source=wheels,target=/wheels \
    --mount=type=bind,source=lists/base.txt,target=/lists/base.txt \
    --mount=type=bind,source=slim.py,target=/slim.py \
    python -m venv --without-pip /opt/venv \
    && pip --python /opt/venv/bin/python install --no-compile --pre --find-links /wheels \
        "vethuq-worker[run]" vethuq-entitlements -r /lists/base.txt \
    && python /slim.py /opt/venv

FROM base AS variant
ARG VARIANT=slim
COPY lists/${VARIANT}.txt /lists/variant.txt
# An empty list (slim) installs nothing. Layers of `base` are not rewritten: only new files land here.
RUN --mount=type=bind,source=wheels,target=/wheels \
    --mount=type=bind,source=slim.py,target=/slim.py \
    if [ -s /lists/variant.txt ]; then \
        pip --python /opt/venv/bin/python install --no-compile --pre --find-links /wheels \
            -r /lists/variant.txt; \
    fi \
    && python /slim.py /opt/venv

# The one step that needs the network: fetch the models into a throwaway folder, prove each engine
# loads, and record what they are. Only the lock leaves this stage.
FROM variant AS locked
RUN mkdir -p /opt/vethuq /tmp/models \
    && vethuq-worker bake-models --models /tmp/models --lock /opt/vethuq/models.lock.json

FROM variant AS final
ARG VARIANT=slim
ENV VETHUQ_MODELS=/opt/vethuq/models \
    VETHUQ_MODELS_LOCK=/opt/vethuq/models.lock.json
LABEL org.opencontainers.image.title="vethuq-worker" \
      org.opencontainers.image.description="VethuQ OCR worker (${VARIANT})" \
      org.opencontainers.image.source="https://github.com/coldsofttech/VethuQ" \
      org.vethuq.variant="${VARIANT}"
# The folder a runner mounts its cached models on; empty here.
RUN mkdir -p /opt/vethuq/models && chmod 0777 /opt/vethuq/models
COPY --from=locked /opt/vethuq/models.lock.json /opt/vethuq/models.lock.json

# Runs as whatever user the workflow passes (the runner's own, so it can write the result and the
# model cache). Without one it is an unprivileged user, never root.
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["vethuq-worker"]
CMD ["--help"]
