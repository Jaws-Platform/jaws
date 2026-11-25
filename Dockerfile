# jaws (Jaws): the CLI, a pinned Terraform, and every stack (site, bot,
# databricks-account, databricks-workspace and the platform's foundation,
# monitoring and data-access) with their modules and providers vendored. Only
# the S3 backend touches the network at run time. Two targets:
#   generic  - Jaws's image, with no configuration inside (the default target).
#   jaws-cli - generic plus this repository's config/ and datasets/.
#
# Build the generic image:
#   docker build --build-arg TERRAFORM_VERSION=<terraform.version from src/jaws/product.yaml> .
# Build the jaws-cli image:
#   docker build --target jaws-cli --build-arg TERRAFORM_VERSION=<same> .
# The CLI refuses to run if the Terraform inside differs from src/jaws/product.yaml.

ARG PYTHON_VERSION=3.13
ARG UV_VERSION=0.11.15

# uv is copied out of its release image; `COPY --from` cannot expand variables,
# so the image gets a named stage.
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# --- stage 1: Terraform binary, verified against HashiCorp's checksums ---------
FROM debian:bookworm-slim AS terraform
ARG TERRAFORM_VERSION
ARG TARGETARCH
RUN test -n "$TERRAFORM_VERSION" || (echo "TERRAFORM_VERSION build-arg is required" && exit 1)
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /tmp/terraform
RUN curl -fsSLO "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${TARGETARCH}.zip" \
    && curl -fsSLO "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_SHA256SUMS" \
    && grep "terraform_${TERRAFORM_VERSION}_linux_${TARGETARCH}.zip" "terraform_${TERRAFORM_VERSION}_SHA256SUMS" | sha256sum -c - \
    && unzip -q "terraform_${TERRAFORM_VERSION}_linux_${TARGETARCH}.zip" terraform \
    && chmod 0755 terraform

# --- stage 2: the Python package and the vendored stack -------------------------
# Alpine for both stages: the virtual environment is copied between them, so
# the wheels (musl) must match. Terraform is a static binary and every
# dependency ships musl wheels. git: the registry serves GitHub-hosted modules
# as git:: sources, which terraform init clones.
FROM python:${PYTHON_VERSION}-alpine AS build
RUN apk add --no-cache ca-certificates git
COPY --from=uv /uv /uvx /usr/local/bin/
# The virtual environment is created at its final path: console-script
# shebangs are absolute, so a venv moved after creation does not start.
# No bytecode compilation: it adds tens of MB for a start-up gain nobody notices.
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/jaws/venv
WORKDIR /src
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
# --no-editable: an editable install points at /src, which the runtime stage does not have.
RUN uv sync --locked --no-dev --no-editable
# botocore ships API definitions for every AWS service; the tool uses eight.
# Keep those plus botocore's shared files (endpoints, partitions, retries).
RUN cd /opt/jaws/venv/lib/python3.13/site-packages/botocore/data \
    && find . -mindepth 1 -maxdepth 1 -type d ! -name s3 ! -name sts ! -name cloudfront ! -name ssm ! -name ec2 ! -name logs ! -name ecr ! -name pricing -exec rm -rf {} + \
    && find /opt/jaws/venv -type d -name __pycache__ -prune -exec rm -rf {} +

COPY --from=terraform /tmp/terraform/terraform /usr/local/bin/terraform
# Every stack ships: the project stacks (stacks/*) and the platform's own, so a
# hub's image built FROM this one can run all of them. The .dockerignore leaves
# out each stack's backend (a platform's runs write their own from `state`) and
# its tests, and its lock file, so each stack's init takes the newest provider
# its constraints allow and the mirror holds each provider once (CI checks).
# Fetch the library modules and mirror the providers so run-time init is offline,
# from the vendored modules and the mirror. The unpacked copies that `init`
# leaves under .terraform/providers are the single largest thing in the image and
# run time never reads them, so they go. The modules stay.
COPY stacks /opt/jaws/stacks
COPY foundation /opt/jaws/stacks/foundation
COPY monitoring /opt/jaws/stacks/monitoring
COPY data-access /opt/jaws/stacks/data-access
RUN for stack in /opt/jaws/stacks/*/; do \
      cd "$stack" \
      && terraform init -backend=false -input=false \
      && terraform providers mirror /opt/jaws/plugins \
      && rm -rf .terraform/providers \
      && find .terraform/modules -type d \( -name .git -o -name examples -o -name tests -o -name docs \) -prune -exec rm -rf {} + \
      || exit 1; \
    done

# --- stage 3: the generic image: the runtime, with no configuration ---------------
FROM python:${PYTHON_VERSION}-alpine AS generic
ARG TERRAFORM_VERSION
LABEL org.opencontainers.image.title="jaws" \
      org.opencontainers.image.source="https://github.com/Jaws-Platform/jaws" \
      org.opencontainers.image.description="Jaws: the CLI, a pinned Terraform and every stack, with their modules and providers vendored. A platform's image adds the platform's configuration." \
      terraform.version="${TERRAFORM_VERSION}"
# No git at run time: the library modules are already in the image. No pip
# either: the virtual environment is complete and nothing installs at run time.
RUN apk add --no-cache ca-certificates \
    && python -m pip uninstall -y pip setuptools wheel >/dev/null 2>&1 || true \
    && rm -rf /usr/local/lib/python3.13/ensurepip /usr/local/lib/python3.13/idlelib \
       /usr/local/lib/python3.13/tkinter /usr/local/lib/python3.13/test /root/.cache
COPY --from=build /opt/jaws/venv /opt/jaws/venv
COPY --from=build /usr/local/bin/terraform /usr/local/bin/terraform
COPY --from=build /opt/jaws/stacks /opt/jaws/stacks
COPY --from=build /opt/jaws/plugins /opt/jaws/plugins
ENV PATH="/opt/jaws/venv/bin:${PATH}" \
    TF_IN_AUTOMATION=1 \
    TF_INPUT=0 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
# The workspace (a site repository checkout) is mounted here. Root inside the
# container so files it writes into the mounted workspace stay deletable by the
# runner; nothing in the image needs privileges.
WORKDIR /work
ENTRYPOINT ["jaws"]
CMD ["--help"]

# --- stage 4: the jaws-cli image: generic plus this repository's configuration ------
# What today's callers run (the composite action pulls jaws-cli:<tag>). It has the
# shape of every platform's image: generic plus the platform's configuration. It goes
# with config/ at cleanup (spec 6.10, step 7).
FROM generic AS jaws-cli
COPY config /etc/jaws/config
COPY datasets /etc/jaws/datasets

# The last stage is the default target: a plain `docker build .` builds the generic image.
FROM generic
