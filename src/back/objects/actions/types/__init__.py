"""Code-registered Action Types. Importing this package registers them on
``back.objects.actions.registry.default_registry``."""
from back.objects.actions.registry import default_registry
from back.objects.actions.types.review_transaction import ReviewTransaction

default_registry.register(ReviewTransaction())
