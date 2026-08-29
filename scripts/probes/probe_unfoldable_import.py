"""MUST BE REFUSED: the name comes from somewhere this checker cannot follow.

A walk that shrugged here would be a walk that anything could get past by reading its module name
out of a file. Not knowing where a call goes is not the same as knowing it is safe, so an
unfoldable name is treated as reaching the package.
"""
import importlib
import os

module = importlib.import_module(os.environ.get("WHICH_MODULE", "math"))
print(module)
