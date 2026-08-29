"""Not a probe. The second hop of probe_indirect_import, and the reason the walk is recursive."""
from foldback import fold


def heard(frequency, rate):
    return fold.alias_of(frequency, rate)
