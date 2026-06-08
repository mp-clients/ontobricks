"""Code-registered Action Types. Importing this package registers them on
``back.objects.actions.registry.default_registry``."""
from back.objects.actions.registry import default_registry
from back.objects.actions.types.flag_customer_high_risk import FlagCustomerHighRisk

default_registry.register(FlagCustomerHighRisk())
