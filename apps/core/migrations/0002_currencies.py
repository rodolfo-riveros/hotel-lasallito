from django.db import migrations


def create_currencies(apps, schema_editor):
    Currency = apps.get_model("core", "Currency")
    for code, name, symbol in [("PEN", "Sol peruano", "S/"), ("USD", "Dólar estadounidense", "US$")]:
        Currency.objects.get_or_create(code=code, defaults={"name": name, "symbol": symbol, "decimals": 2})


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [migrations.RunPython(create_currencies, migrations.RunPython.noop)]
