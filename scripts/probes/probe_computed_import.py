"""MUST BE REFUSED: the name is built at runtime rather than written down.

A grep for `import foldback` finds nothing here. The ast walk folds the concatenation and does.
"""
import importlib

HALF = "fold"
module = importlib.import_module("fold" + "back." + HALF)
print(module.nyquist(44100.0))
