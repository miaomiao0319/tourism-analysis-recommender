"""Adapter for C's AppError; no Flask or HTTP mapping is performed here."""

KNOWN = {'INVALID_PARAMETER', 'INVALID_FILTER', 'DATASET_NOT_READY', 'DATASET_INVALID',
         'PRICE_POLICY_NOT_READY', 'STATISTIC_NOT_AVAILABLE'}


class RepositoryAdapter:
    def __init__(self, repository, app_error, dependency_errors):
        self.repository = repository
        self.app_error = app_error
        self.dependency_errors = tuple(dependency_errors)

    def _translate(self, error):
        if isinstance(error, self.dependency_errors):
            return self.app_error('DEPENDENCY_UNAVAILABLE', '数据库暂时不可用', {})
        if isinstance(error, ValueError):
            code = str(error)
            if code in KNOWN:
                return self.app_error(code, '数据查询未能完成', {})
        return None

    def _call(self, method, *args, **kwargs):
        try:
            return getattr(self.repository, method)(*args, **kwargs)
        except Exception as error:
            mapped = self._translate(error)
            if mapped is None:
                raise
            raise mapped from error

    def load_dataset(self, *args, **kwargs):
        return self._call('load_dataset', *args, **kwargs)

    def list_attractions(self, *args, **kwargs):
        return self._call('list_attractions', *args, **kwargs)

    def get_attraction(self, *args, **kwargs):
        return self._call('get_attraction', *args, **kwargs)

    def list_statistics(self, *args, **kwargs):
        return self._call('list_statistics', *args, **kwargs)

    def iter_recommendation_candidates(self, *args, **kwargs):
        try:
            yield from self.repository.iter_recommendation_candidates(*args, **kwargs)
        except Exception as error:
            mapped = self._translate(error)
            if mapped is None:
                raise
            raise mapped from error
