"""Compatibility entry: build a candidate ZIP; publishing is a separate explicit step."""
from release_tools import build_windows
if __name__=='__main__':print(build_windows())
