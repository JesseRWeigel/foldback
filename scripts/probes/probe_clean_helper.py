"""Not a probe. The second hop of probe_clean, and it stays out of the package too."""
import math


def reflected(frequency, rate):
    remainder = math.fmod(frequency, rate)
    return remainder if remainder <= rate / 2.0 else rate - remainder
