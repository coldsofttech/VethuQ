# The worker image: vethuq-worker, VethuQ, the add-ons and the OCR models, for GitHub runners.
#
# Built by .github/workflows/github-image.yml, never by hand: the build context holds `wheels/`
# (every wheel the image installs, built from the checked-out sources and gated for shipping).
# The add-on wheels are compiled and licence-gated at runtime; the image is public, so it carries
# no secret, token or key. Jobs run with no network: the models are baked in here.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VETHUQ_MODELS=/opt/vethuq/models \
    HOME=/tmp

# Shared libraries the OCR engine's image and maths wheels load.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY wheels /wheels
# --pre: wheels built between tags carry development versions.
RUN pip install --pre --find-links /wheels "vethuq-worker[run]" vethuq-entitlements \
        vethuq-addon-english vethuq-addon-pdf vethuq-addon-txt vethuq-addon-csv vethuq-addon-tsv \
        vethuq-addon-markdown vethuq-addon-png vethuq-addon-jpg vethuq-addon-tiff \
        vethuq-addon-html vethuq-addon-xml vethuq-addon-css vethuq-addon-js vethuq-addon-json vethuq-addon-yaml vethuq-addon-parquet \
        vethuq-addon-docx vethuq-addon-doc vethuq-addon-xlsx vethuq-addon-xls vethuq-addon-pptx \
        vethuq-addon-ppt vethuq-addon-rtf vethuq-addon-eml \
        vethuq-addon-telugu vethuq-addon-hindi vethuq-addon-urdu vethuq-addon-french vethuq-addon-spanish vethuq-addon-paddle \
        vethuq-addon-ocr-quick vethuq-addon-ocr-moderate vethuq-addon-ocr-deep \
        vethuq-addon-like vethuq-addon-exact vethuq-addon-lexical vethuq-addon-full-text \
        vethuq-addon-proximity vethuq-addon-fuzzy vethuq-addon-noise-fuzzy \
        vethuq-addon-semantic vethuq-addon-autoscale \
        vethuq-addon-case vethuq-addon-unicode vethuq-addon-leetspeak \
    && rm -rf /wheels

# The one step that needs the network: fetch the models and prove each engine loads.
RUN mkdir -p "$VETHUQ_MODELS" \
    && vethuq-worker bake-models --models "$VETHUQ_MODELS" \
    && chmod -R a+rX /opt/vethuq

# Runs as whatever user the workflow passes (the runner's own, so it can write the result).
# Without one it is an unprivileged user, never root.
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["vethuq-worker"]
CMD ["--help"]
