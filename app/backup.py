from dataclasses import dataclass
from datetime import datetime


MAX_ARCHIVE_NAME_LENGTH = 60


class ArchiveNameError(ValueError):
    pass

@dataclass(frozen=True)
class ModelTarget:
    workspace: str = ''
    model: str = ''
    workspace_id: str = ''
    model_id: str = ''
    tags: tuple[str,...] = ()

def backup_name(model: str, suffix_format: str, now: datetime) -> str:
    if not isinstance(model, str) or not model.strip():
        raise ArchiveNameError('The source model name must not be empty.')
    if not isinstance(suffix_format, str) or not suffix_format:
        raise ArchiveNameError('backup.suffix_format must not be empty.')
    suffix = now.strftime(suffix_format)
    if not suffix:
        raise ArchiveNameError('backup.suffix_format produced an empty suffix.')
    if len(suffix) >= MAX_ARCHIVE_NAME_LENGTH:
        raise ArchiveNameError(
            f'The generated archive suffix is {len(suffix)} characters; it must be shorter '
            f'than {MAX_ARCHIVE_NAME_LENGTH} characters so the model name is retained.'
        )
    max_base = MAX_ARCHIVE_NAME_LENGTH - len(suffix)
    name = f'{model.strip()[:max_base]}{suffix}'
    if len(name) > MAX_ARCHIVE_NAME_LENGTH:
        raise ArchiveNameError(
            f'The generated archive name exceeds {MAX_ARCHIVE_NAME_LENGTH} characters.'
        )
    return name


def plan_archive_names(targets: list[ModelTarget], suffix_format: str,
                       now: datetime) -> list[tuple[ModelTarget, str]]:
    plans = []
    seen = {}
    for target in targets:
        name = backup_name(target.model, suffix_format, now)
        workspace_key = (target.workspace_id or target.workspace).strip().lower()
        key = (workspace_key, name.casefold())
        if key in seen:
            previous = seen[key]
            raise ArchiveNameError(
                f'Archive-name collision in workspace {target.workspace!r}: models '
                f'{previous.model!r} and {target.model!r} both produce {name!r}. '
                'Change backup.suffix_format or the configured model names.'
            )
        seen[key] = target
        plans.append((target, name))
    return plans

def enabled_targets(cfg: dict) -> list[ModelTarget]:
    out=[]
    for x in cfg.get('backup',{}).get('models',[]):
        if x.get('enabled'):
            tags=tuple(str(tag).strip() for tag in (x.get('tags') or []))
            out.append(ModelTarget(x.get('workspace_name',x.get('workspace','')),x.get('model_name',x.get('model','')),x.get('workspace_id','') or '',x.get('model_id','') or '',tags))
    return out
