#!/usr/bin/env python
import os
import sys


def main():
    # En Render (variable RENDER) siempre producción: nunca DEBUG, aunque en el panel quede
    # DJANGO_SETTINGS_MODULE=config.settings.dev (por ejemplo, al importar un .env de desarrollo).
    if os.environ.get("RENDER"):
        os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.prod"
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
