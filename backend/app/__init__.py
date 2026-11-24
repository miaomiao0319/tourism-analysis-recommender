"""Flask entry point; data and analytics imports do not require web dependencies."""


def create_app(config=None, repository=None):
    from .web_app import create_app as build
    return build(config, repository)
