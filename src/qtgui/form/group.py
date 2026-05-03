from dataclasses import dataclass
from typing import Optional, List


@dataclass
class FormGroup:
    name: str
    description: Optional[str] = None
    parameters: List[str] = None

    def __post_init__(self):
        if self.parameters is None:
            self.parameters = []


def form_group(group_name: str, description: str = None, parameters: List[
    str] = None):
    """Decorator to specify form groups for a class or function."""

    def decorator(obj):
        if not hasattr(obj, '_form_groups'):
            obj._form_groups = []
        obj._form_groups.append(FormGroup(group_name, description,
                                          parameters=parameters))
        return obj

    return decorator


def form_group_members(*param_names: str):
    """Decorator to specify which parameters belong to the last defined group."""

    def decorator(obj):
        if hasattr(obj, '_form_groups') and obj._form_groups:
            obj._form_groups[-1].parameters.extend(param_names)
        return obj

    return decorator
