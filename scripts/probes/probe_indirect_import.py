"""MUST BE REFUSED: this file imports a helper beside it, and the helper imports the package."""
import probe_helper

print(probe_helper.heard(30870.0, 44100.0))
