import yaml
from typing import Dict


def load_config(config_path: str) -> Dict:
    """
    טעינת קובץ הקונפיגורציה
    """
    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Config file not found: {config_path}") from None
    except yaml.YAMLError as error:
        raise ValueError(f"Config file {config_path} is not valid YAML: {error}") from error

    if not isinstance(config, dict):
        raise ValueError(f"Config file {config_path} is empty or not a mapping")

    return config
