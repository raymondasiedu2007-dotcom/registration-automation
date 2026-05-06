from __future__ import annotations

import ast


def safe_load(text: str):
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ModuleNotFoundError:
        return _minimal_yaml_load(text)


def _minimal_yaml_load(text: str):
    root: dict = {}
    stack: list[tuple[int, object]] = [(-1, root)]
    lines = [line.split('#', 1)[0].rstrip() for line in text.splitlines()]
    for raw in lines:
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(' '))
        line = raw.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if line.startswith('- '):
            if not isinstance(parent, list):
                raise ValueError('Unsupported YAML list placement')
            parent.append(_parse_scalar(line[2:].strip()))
            continue
        key, _, value = line.partition(':')
        key = key.strip().strip('"\'')
        if value.strip():
            assert isinstance(parent, dict)
            parent[key] = _parse_scalar(value.strip())
            continue
        next_container: object = [] if _next_nonempty_starts_list(lines, raw) else {}
        assert isinstance(parent, dict)
        parent[key] = next_container
        stack.append((indent, next_container))
    return root


def _next_nonempty_starts_list(lines: list[str], current: str) -> bool:
    seen = False
    cur_indent = len(current) - len(current.lstrip(' '))
    for line in lines:
        if line is current:
            seen = True
            continue
        if not seen or not line.strip():
            continue
        indent = len(line) - len(line.lstrip(' '))
        if indent <= cur_indent:
            return False
        return line.strip().startswith('- ')
    return False


def _parse_scalar(value: str):
    if value.lower() == 'true':
        return True
    if value.lower() == 'false':
        return False
    if value in {'null', '~'}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return ast.literal_eval(value)
    return value
