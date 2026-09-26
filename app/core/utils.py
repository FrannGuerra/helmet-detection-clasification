def format_timestamp(timestamp):
    from datetime import datetime
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

def load_config(config_path='config/config.yaml'):
    import yaml
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)