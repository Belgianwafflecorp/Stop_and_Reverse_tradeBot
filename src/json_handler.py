"""
JSON Handler for loading and managing configuration files.
Provides centralized JSON loading functions to avoid code duplication.
"""

import json
import os
import sys


def load_json(path):
    """
    Load JSON data from a file.
    
    :param path: Path to JSON file
    :return: Parsed JSON data as dictionary
    :raises FileNotFoundError: If file doesn't exist
    """
    with open(path, 'r') as f:
        return json.load(f)


def get_config_path(config_file=None, project_root=None):
    """
    Resolve configuration file path.
    
    :param config_file: Optional config file path (absolute or relative to project root)
    :param project_root: Optional project root directory (if None, auto-detects)
    :return: Absolute path to configuration file
    """
    # Auto-detect project root if not provided
    if project_root is None:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
    
    # Determine config file path
    if config_file:
        # Use provided config file path
        if os.path.isabs(config_file):
            config_path = config_file
        else:
            config_path = os.path.join(project_root, config_file)
    else:
        # Default to config.json in configs folder
        config_path = os.path.join(project_root, 'configs', 'config.json')
    
    # Resolve to absolute path
    return os.path.abspath(config_path)


def load_config(config_file=None):
    """
    Load configuration from JSON file.
    
    :param config_file: Optional config file path (if None, uses default config.json)
    :return: Configuration dictionary
    :raises FileNotFoundError: If config file doesn't exist
    """
    config_path = get_config_path(config_file)
    
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    return load_json(config_path)


def load_api_keys(project_root=None):
    """
    Load API keys from api-keys.json.
    
    :param project_root: Optional project root directory (if None, auto-detects)
    :return: API keys dictionary
    :raises FileNotFoundError: If api-keys.json doesn't exist
    """
    if project_root is None:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
    
    keys_path = os.path.join(project_root, 'api-keys.json')
    
    if not os.path.exists(keys_path):
        raise FileNotFoundError(f"API keys file not found: {keys_path}")
    
    return load_json(keys_path)
