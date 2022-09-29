from typing import Dict

from ops.manifests import ManifestLabel, Manifests


class MultusManifests(Manifests):
    def __init__(self, charm, charm_config):
        manipulations = [
            ManifestLabel(self),
        ]

        super().__init__("multus", charm.model, "upstream/multus", manipulations)
        self.charm_config = charm_config

    @property
    def config(self) -> Dict:
        """Returns config mapped from charm config and joined relations."""
        config = dict(**self.charm_config)

        for key, value in dict(**config).items():
            if value == "" or value is None:
                del config[key]

        config["release"] = config.pop("release", None)
        return config
