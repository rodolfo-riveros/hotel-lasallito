#!/usr/bin/env python
import os
import sys


def main():
    # En Render (variable RENDER) siempre producción, aunque falte DJANGO_SETTINGS_MODULE: nunca DEBUG.
    os.environ.setdefault(
        "DJANGO_SETTINGS_MODULE",
        "config.settings.prod" if os.environ.get("RENDER") else "config.settings.dev",
    )
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
