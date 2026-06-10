# ── Stage 1: build rsgain + TagLib 2.x ───────────────────────────────────────
FROM ubuntu:22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive
ARG RSGAIN_VERSION=3.7
ARG TAGLIB_VERSION=2.0.2

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates xz-utils cmake make g++ pkg-config \
    libavcodec-dev libavformat-dev libavutil-dev libswresample-dev \
    libebur128-dev libinih-dev libfmt-dev libutfcpp-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Build TagLib 2.x (Ubuntu 22.04 only ships 1.x)
RUN curl -fsSL "https://taglib.org/releases/taglib-${TAGLIB_VERSION}.tar.gz" \
        | tar -xz -C /tmp \
    && cmake -S /tmp/taglib-${TAGLIB_VERSION} -B /tmp/taglib-build \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/opt/taglib \
        -DBUILD_SHARED_LIBS=ON \
    && cmake --build /tmp/taglib-build --parallel \
    && cmake --install /tmp/taglib-build

RUN curl -fsSL "https://github.com/complexlogic/rsgain/releases/download/v${RSGAIN_VERSION}/rsgain-${RSGAIN_VERSION}-source.tar.xz" \
        | tar -xJ -C /tmp \
    && cmake -S /tmp/rsgain-${RSGAIN_VERSION} -B /tmp/rsgain-build -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_PREFIX_PATH=/opt/taglib \
    && cmake --build /tmp/rsgain-build --parallel \
    && strip /tmp/rsgain-build/rsgain

# ── Stage 2: runtime image ───────────────────────────────────────────────────
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    libchromaprint-tools \
    ffmpeg \
    gcc \
    g++ \
    curl \
    ca-certificates \
    unzip \
    libebur128-1 \
    libinih1 \
    libfmt8 \
    zlib1g \
    && rm -rf /var/lib/apt/lists/*

# Copy TagLib 2.x from builder
COPY --from=builder /opt/taglib /opt/taglib
RUN ldconfig /opt/taglib/lib

# Install rclone from official releases (apt version too old for SMB backend)
RUN curl -fsSL https://downloads.rclone.org/rclone-current-linux-amd64.zip -o /tmp/rclone.zip \
    && unzip -q /tmp/rclone.zip -d /tmp/rclone \
    && cp /tmp/rclone/rclone-*/rclone /usr/local/bin/ \
    && chmod +x /usr/local/bin/rclone \
    && rm -rf /tmp/rclone*

# Copy only the rsgain binary from the builder
COPY --from=builder /tmp/rsgain-build/rsgain /usr/local/bin/rsgain

# Install uv (manages Python 3.14 automatically)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY . .

ENV CPLUS_INCLUDE_PATH=/opt/taglib/include
ENV LIBRARY_PATH=/opt/taglib/lib
ENV LD_LIBRARY_PATH=/opt/taglib/lib
ENV PKG_CONFIG_PATH=/opt/taglib/lib/pkgconfig
ENV CONFIG_DIR=/config

# Pre-install webui.py dependencies at build time so container startup is instant.
# uv installs all PEP 723 deps, then PREINSTALL_ONLY causes immediate exit.
RUN PREINSTALL_ONLY=1 uv run webui.py
VOLUME /config

EXPOSE 8000

CMD ["uv", "run", "webui.py"]
