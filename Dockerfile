# StrongARM / VCO sizing console — everything is real SPICE, so the image is built around
# ngspice rather than around the web app.
#
# Three stages: build the frontend with Node, build ngspice from source, then assemble a
# slim runtime. ngspice is compiled rather than apt-installed because the version matters:
# the `pre_osdi` command this project uses for the ASAP7 BSIM-CMG backend needs a recent
# ngspice with OSDI support, and every measurement in the repo (offset budgets, tuning
# curves, phase noise) was taken on ngspice-46. A distro package pinned to 38 or 44 would
# quietly produce different numbers.

# ---------------------------------------------------------------- frontend
FROM node:22-bookworm-slim AS web
WORKDIR /app/webapp
# lockfile first so `npm ci` is cached independently of source edits
COPY webapp/package.json webapp/package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY webapp/ ./
# `npm run build` typechecks before bundling (a green vite build once shipped a call to a
# function that did not exist), so a type error fails the image build here
RUN npm run build


# ---------------------------------------------------------------- ngspice
FROM debian:bookworm-slim AS ngspice
ARG NGSPICE_VERSION=46
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential ca-certificates curl bison flex \
      libxaw7-dev libreadline-dev libtool automake autoconf pkg-config \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN curl -fsSL -o ngspice.tar.gz \
      "https://downloads.sourceforge.net/project/ngspice/ng-spice-rework/${NGSPICE_VERSION}/ngspice-${NGSPICE_VERSION}.tar.gz" \
 && tar xzf ngspice.tar.gz && rm ngspice.tar.gz
WORKDIR /src/ngspice-${NGSPICE_VERSION}
# --enable-osdi is the point of building from source: it is what loads the compiled
# Verilog-A models (BSIM-CMG) the asap7 backend runs on.
# --with-ngshared is deliberately NOT used; the project shells out to the binary.
RUN ./configure --disable-debug --enable-openmp --enable-osdi \
      --without-x --with-readline=yes --prefix=/usr/local \
 && make -j"$(nproc)" && make install && strip /usr/local/bin/ngspice


# ---------------------------------------------------------------- runtime
FROM python:3.12-slim-bookworm AS runtime

# ngspice's runtime needs, and nothing else: the compiler toolchain stays in its stage
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgomp1 libreadline8 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ngspice /usr/local/bin/ngspice /usr/local/bin/ngspice
COPY --from=ngspice /usr/local/share/ngspice /usr/local/share/ngspice

# numpy/scikit-learn power the optimizer's GP surrogate. Both are imported inside
# try/except, so the app runs without them — it just falls back to evaluating every
# candidate in SPICE, which is far slower. Installed deliberately, not incidentally.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

WORKDIR /app
# source, vendored device models, and the Verilog-A source for rebuilding the OSDI
COPY run_sim.py vco_sim.py layout.py wicked.py vco_wicked.py mcp_server.py ./
COPY models/ ./models/
COPY scripts/ ./scripts/
COPY third_party/bsimcmg107/ ./third_party/bsimcmg107/
COPY webapp/server.py ./webapp/server.py
COPY tests/ ./tests/
COPY README.md ./
COPY --from=web /app/webapp/dist ./webapp/dist

# The console binds 0.0.0.0 here rather than localhost; NGSPICE_MAX_PROCS caps the
# simulator semaphore, which otherwise sizes itself to the host's CPU count and will
# oversubscribe a container with a smaller cpu quota.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STRONGARM_HOST=0.0.0.0 \
    STRONGARM_PORT=8770 \
    SKY130_NGSPICE_LIB=/pdk/sky130A/libs.tech/ngspice/sky130.lib.spice

EXPOSE 8770

# Reports which backends actually work, so an unhealthy container is distinguishable from
# one that is merely missing an optional PDK: ptm45 and gaa2nm are vendored and must always
# be present, so the check requires them and stays quiet about the other two.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,json,sys; \
d=json.load(urllib.request.urlopen('http://127.0.0.1:8770/api/health',timeout=8)); \
m=d['availability']['models']; \
sys.exit(0 if d['ok'] and m['ptm45']['available'] and m['gaa2nm']['available'] else 1)"

CMD ["python", "webapp/server.py"]
