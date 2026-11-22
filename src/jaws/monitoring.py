"""The monitoring stack's secrets: what the owner sets in SSM before the stack runs.

They are the Grafana admin's user and password, and each Slack channel's
incoming-webhook URL, all SecureStrings under /jaws/monitoring/. The owner
writes them with `jaws monitoring secrets set`; Terraform never manages them.
The node and the watchdog report `missing secret <name>` while one is absent.
"""

from __future__ import annotations

from .errors import ConfigError
from .settings import MONITORING_SECRETS_PREFIX, MonitoringSection

#: The Grafana admin's secrets, at /jaws/monitoring/<name>.
GRAFANA_ADMIN_SECRETS = ("grafana-admin-user", "grafana-admin-password")
#: `slack/<channel>` names a channel's webhook, at the parameter the channel names.
SLACK_PREFIX = "slack/"


def secret_parameters(section: MonitoringSection) -> dict[str, str]:
    """Every secret the configuration implies, by name, with its SSM parameter."""
    secrets = {name: f"{MONITORING_SECRETS_PREFIX}{name}" for name in GRAFANA_ADMIN_SECRETS}
    if section.slack is not None:
        for channel, parameter in section.slack.channels.items():
            secrets[f"{SLACK_PREFIX}{channel}"] = parameter
    return secrets


def secret_parameter(section: MonitoringSection, name: str) -> str:
    """The SSM parameter of one secret; a name the configuration does not imply
    is a ConfigError that says which ones it does."""
    secrets = secret_parameters(section)
    if name in secrets:
        return secrets[name]
    channel = name.removeprefix(SLACK_PREFIX)
    if name.startswith(SLACK_PREFIX) and channel:
        if section.slack is None:
            raise ConfigError(
                f"{name}: there is no monitoring.slack in config/monitoring.yaml, so no "
                "channel has a webhook"
            )
        raise ConfigError(
            f"{name}: {channel} is not a channel in monitoring.slack.channels "
            f"({', '.join(section.slack.channels)})"
        )
    raise ConfigError(f"{name} is not a monitoring secret; use one of {', '.join(secrets)}")
