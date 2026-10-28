"""Tells the assistant the current date/time (small models cannot know it)."""
from datetime import datetime


def get_time() -> str:
    now = datetime.now().astimezone()
    return now.strftime("%A %d %B %Y, %H:%M:%S ") + str(now.tzinfo)


def register(register_tool):
    register_tool(name="get_time", signature="get_time()   # current local date and time", perm="misc",
                  fn=get_time, describe=lambda a: "Checking the time")
