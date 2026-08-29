"""MUST BE ACCEPTED: the package is named in a comment and in a string, and never imported.

This is the probe that separates an ast walk from a grep. A grep for the package name matches
three times in this file and would refuse it, and refusing a file that only talks about the
package is a checker that has to be worked around rather than trusted.
"""
import math

# import foldback would be the wrong thing to do here, so it is not done.
NOTE = "the numbers this file checks come from foldback, which it does not import"

print(NOTE, math.tau)
