from abc import ABC, abstractmethod

class _Registry(ABC):
    source = 'github'
    strategy = ''
    description = ''
    _implementations = {}

    @classmethod
    def register(cls, implementation):
        key = (implementation.source, implementation.strategy)
        if key in cls._implementations:
            raise ValueError('知识策略重复：' + str(key))
        cls._implementations[key] = implementation
        return implementation

    @classmethod
    def create(cls, source, strategy, *args, **kwargs):
        try:
            implementation = cls._implementations[(source, strategy)]
        except KeyError as exc:
            raise ValueError(f'未知知识策略：{source}/{strategy}') from exc
        return implementation(*args, **kwargs)

    @classmethod
    def describe(cls):
        return [{'source': source, 'strategy': strategy, 'description': implementation.description,
                 'output_format': getattr(implementation, 'output_format', 'mrg-materials-v1')}
                for (source, strategy), implementation in sorted(cls._implementations.items())]


class KDiscovery(_Registry):
    _implementations = {}

    @abstractmethod
    def extract(self, meta, files, request, job_id, progress):
        """Return the strategy's declared format; new requirement MRGs bypass legacy M1."""
